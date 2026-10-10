"""FastAPI app: /chat (SSE), /track (session origin beacon), /healthz, /admin/*, static chat page + embeddable widget."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

import re

from fastapi import File, Form, UploadFile
from fastapi.responses import Response

from app import conversations, digest, guidance, identity, inbox, mailer, media, memory, nudge, outreach, store_bookings, suggestions, templates, titles, tracking
from app.booking import availability as avail
from app.booking import flow, ics
from app.booking.service import BookingService
from app.booking.email import send_host_brief, send_test
from app.chat import respond, sse
from app.config import settings
from app.db import init_schema, log_event, spend_today
from app.ingest.pipeline import run_ingest
from app.security.limits import RateLimiter, limiter, spend_cap_reached

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

STATIC = Path(__file__).resolve().parent.parent / "static"
APP_VERSION = "2026.10.11.1"  # bump when the widget changes; appended as ?v= to static URLs and shown in the console/footer
app = FastAPI(title="deependhq assistant", docs_url=None, redoc_url=None)


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    """Local development must never show a stale widget: no-store for HTML and static files while WIDGET_DEMO is on.
    In production static files are cached briefly and busted by the ?v= version query."""
    response = await call_next(request)
    p = request.url.path
    if p.startswith("/static/") or p in ("/", "/site", "/widget", "/legacy", "/demo", "/admin"):
        response.headers["Cache-Control"] = "no-store" if settings.widget_demo else "public, max-age=300, must-revalidate"
        response.headers["X-Assistant-Version"] = APP_VERSION
    return response

# Allowed origins only; never '*'. Credentials off (we use no cookies).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_methods=["POST", "GET", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Session-Id", "X-Visitor-Id", "X-Visitor-Token", "X-Admin-Token"],
    allow_credentials=False,
)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

_scheduler = BackgroundScheduler()
_track_limiter = RateLimiter(per_minute=30, per_day=2000)  # one beacon per chat open; separate from the chat budget
_booking_limiter = RateLimiter(per_minute=4, per_day=12)     # confirm attempts per session (plus the per-email active cap)
_booking_service = BookingService()                         # shared: schedule cache + Zoom token
_outreach_limiter = RateLimiter(per_minute=60, per_day=3000)  # a few checks per page view (app/outreach.py)


@app.on_event("startup")
def _startup() -> None:
    init_schema()
    _scheduler.add_job(run_ingest, CronTrigger.from_crontab(settings.recrawl_cron, timezone=settings.recrawl_tz),
                       id="recrawl", replace_existing=True, misfire_grace_time=3600)
    _scheduler.add_job(tracking.purge, CronTrigger.from_crontab("10 3 * * *", timezone=settings.recrawl_tz),
                       id="tracking_purge", replace_existing=True, misfire_grace_time=3600)
    if settings.digest_enabled:  # weekly digest to the host (app/digest.py)
        _scheduler.add_job(digest.run, CronTrigger.from_crontab(settings.digest_cron, timezone=settings.host_timezone),
                           id="weekly_digest", replace_existing=True, misfire_grace_time=6 * 3600)
    if settings.nudge_enabled:  # hourly: remind visitors whose Zoom hand-off is still unconfirmed (app/nudge.py)
        _scheduler.add_job(nudge.run, CronTrigger.from_crontab("15 * * * *", timezone=settings.host_timezone),
                           id="nudges", replace_existing=True, misfire_grace_time=1800)
    if settings.outreach_enabled:  # starter outreach rules, once (app/outreach.py)
        outreach.seed_if_empty()
    _scheduler.start()
    log.info("recrawl scheduled: '%s' (%s); tracking=%s geo=%s ip_mode=%s retention=%sd",
             settings.recrawl_cron, settings.recrawl_tz, settings.tracking_enabled, settings.geoip_provider,
             settings.track_ip_mode, settings.track_retention_days)


@app.on_event("shutdown")
def _shutdown() -> None:
    _scheduler.shutdown(wait=False)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=40)
    timezone: str = Field(default="UTC", max_length=64)
    user_name: str | None = Field(default=None, max_length=120)   # unverified hints from the host app
    user_email: str | None = Field(default=None, max_length=200)
    attachments: list[str] = Field(default_factory=list, max_length=5)  # upload ids from POST /upload (this session's)


def _visitor(request: Request, hint_name: str | None = None, hint_email: str | None = None) -> dict:
    return identity.describe(identity.verify(request.headers.get("x-visitor-token")), hint_name, hint_email)


class TrackIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    visitor_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    page: str | None = Field(default=None, max_length=2000)
    referrer: str | None = Field(default=None, max_length=2000)
    timezone: str | None = Field(default=None, max_length=64)
    lang: str | None = Field(default=None, max_length=16)
    screen: str | None = Field(default=None, max_length=16)


class OutreachCheckIn(BaseModel):
    """Activity snapshot from the loader (docs/OUTREACH.md). Nothing here is stored except the page of a firing."""
    visitor_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    page: str | None = Field(default=None, max_length=2000)
    path: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=200)
    first_page: str | None = Field(default=None, max_length=2000)
    pages: list[str] = Field(default_factory=list, max_length=60)
    dwell_s: int = Field(default=0, ge=0, le=1_000_000)
    scroll_pct: int = Field(default=0, ge=0, le=100)
    referrer: str | None = Field(default=None, max_length=2000)
    visits: int = Field(default=0, ge=0, le=100_000)
    shown: list[int] = Field(default_factory=list, max_length=60)


class OutreachEventIn(BaseModel):
    event_id: int
    action: str = Field(pattern=r"^(opened|dismissed)$")
    visitor_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class OutreachRuleIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=100)
    cooldown_hours: int | None = Field(default=None, ge=0, le=720)
    trigger: dict | None = None
    message: dict | None = None


class OutreachSettingsIn(BaseModel):
    default_greeting: bool


class OutreachTryIn(BaseModel):
    """Dry run from the console: which rule would fire for this activity (nothing is recorded)."""
    path: str = Field(default="/", max_length=500)
    pages: list[str] = Field(default_factory=list, max_length=60)
    dwell_s: int = Field(default=0, ge=0, le=100_000)
    scroll_pct: int = Field(default=0, ge=0, le=100)
    referrer: str | None = Field(default=None, max_length=2000)
    visits: int = Field(default=1, ge=0, le=100_000)
    booking: bool = False
    first_name: str | None = Field(default=None, max_length=60)


class FeedbackIn(BaseModel):
    message_id: int
    rating: int  # 1 or -1
    note: str | None = Field(default=None, max_length=1000)


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class HandoverIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=1, max_length=2000)


class GuidanceIn(BaseModel):
    text: str = Field(default="", max_length=4000)


class CustomAnswerIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=1, max_length=3000)
    link: str | None = Field(default=None, max_length=500)


class TemplatesIn(BaseModel):
    templates: dict[str, str] = Field(default_factory=dict)


class TestMailIn(BaseModel):
    kind: str = Field(pattern=r"^(host|visitor_booking|visitor_handover|visitor_nudge|visitor_confirmed|host_booking)$")


class ConfirmIn(BaseModel):
    schedule_slug: str = Field(min_length=1, max_length=120)
    start: str = Field(min_length=10, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    company: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    timezone: str = Field(default="UTC", max_length=64)


class CustomAnswerPatch(BaseModel):
    enabled: bool | None = None
    question: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=3000)
    link: str | None = Field(default=None, max_length=500)


def _client_ip(req: Request) -> str:
    return tracking.client_ip(req.headers, req.client.host if req.client else None)


def _require_admin(token: str | None) -> None:
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(403, "forbidden")


def _origin_ok(req: Request) -> bool:
    """Belt and braces on top of CORS: non-browser callers must still present an allowed Origin/Referer.
    Not authentication (headers can be forged); it just stops casual abuse of the endpoint."""
    origin = req.headers.get("origin") or req.headers.get("referer") or ""
    if not origin:
        return "@localhost" in settings.database_url or "@127.0.0.1" in settings.database_url  # local dev only
    host = req.headers.get("host", "")
    same_origin = bool(host) and origin.split("://", 1)[-1].split("/", 1)[0].lower() == host.lower()
    return same_origin or any(origin.startswith(o) for o in settings.origins) or origin.startswith("http://localhost")


@app.post("/track")
async def track(body: TrackIn, request: Request):
    """Session origin beacon, sent once when the chat opens. Records IP (geolocated in the background),
    landing page, referrer, UTM, timezone. Returns immediately; never blocks the chat."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    ip = _client_ip(request)
    if not _track_limiter.allow(ip):
        raise HTTPException(429, "too many requests")
    try:
        return tracking.start_session(body.session_id, body.visitor_id, ip, request.headers.get("user-agent"),
                                      body.page, body.referrer, body.timezone, body.lang, body.screen)
    except Exception as e:  # a tracking failure is never the visitor's problem
        log.warning("track failed: %s", e)
        return {"ok": False, "tracked": False}


@app.post("/outreach/check")
def outreach_check(body: OutreachCheckIn, request: Request, x_visitor_id: str | None = Header(default=None)):
    """Which outreach rule, if any, should open the greeting bubble now (docs/OUTREACH.md). Called by the loader on
    page load and again when a time-on-page or scroll threshold a rule waits for is reached."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not settings.outreach_enabled:
        return {"rule": None, "recheck": {}, "default": True, "enabled": False}
    if not _outreach_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    vid = (body.visitor_id or x_visitor_id or "").strip()[:64] or None
    return {**outreach.check(body.model_dump(), vid), "enabled": True}


@app.post("/outreach/event")
def outreach_event(body: OutreachEventIn, request: Request, x_visitor_id: str | None = Header(default=None)):
    """The bubble a rule opened was tapped (into chat session `session_id`) or dismissed."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _outreach_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    try:
        ok = outreach.mark(body.event_id, body.action, body.visitor_id or x_visitor_id, body.session_id)
    except Exception as e:
        log.warning("outreach event failed: %s", e)
        ok = False
    return {"ok": ok}


@app.post("/chat")
async def chat(body: ChatIn, request: Request, x_session_id: str | None = Header(default=None),
               x_visitor_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    session_id = x_session_id or str(uuid.uuid4())
    if not limiter.allow(_client_ip(request)):
        log_event("rate_limited", session_id, {"ip": _client_ip(request)})
        raise HTTPException(429, "Too many messages. Please try again in a minute.")
    tracking.touch(session_id, _client_ip(request), request.headers.get("user-agent"))
    visitor = _visitor(request, body.user_name, body.user_email)
    if visitor.get("signed_in"):
        tracking.attach_user(session_id, visitor)
    if x_visitor_id:  # the widget's persistent visitor id, so the session shows up in that visitor's Messages list
        tracking.attach_visitor(session_id, x_visitor_id)
    if spend_cap_reached():
        log_event("spend_cap", session_id, {"usd": spend_today()})

        def capped():
            yield sse({"type": "refusal", "reason": "spend_cap"})
            yield sse({"type": "token", "text": "The assistant has hit its daily budget. Please book directly at "
                                                f"{settings.zoom_booking_base} or email {settings.host_email}."})
            yield sse({"type": "done"})

        return StreamingResponse(capped(), media_type="text/event-stream")

    extra, attached = media.attachments_block(body.attachments, session_id) if body.attachments else ("", [])
    mem = ""
    if settings.visitor_memory and (x_visitor_id or visitor.get("signed_in")):
        mem = memory.prompt_block(memory.profile(x_visitor_id, visitor.get("sub") if visitor.get("signed_in") else None, session_id))
    gen = respond(body.message, body.history, body.timezone, session_id, visitor=visitor, extra_context=extra, attachments=attached, memory=mem)
    return StreamingResponse(iterate_in_threadpool(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Session-Id": session_id})


@app.post("/feedback")
def feedback(body: FeedbackIn, request: Request, x_session_id: str | None = Header(default=None)):
    """Thumbs up/down on an answer. The session that received the answer is the only one that can rate it."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    try:
        return {"ok": inbox.set_feedback(body.message_id, body.rating, body.note, x_session_id)}
    except Exception as e:
        log.warning("feedback failed: %s", e)
        return {"ok": False}


# ---- the visitor's own conversations (widget Messages screen)
def _owner(request: Request, x_visitor_id: str | None) -> tuple[str | None, str | None]:
    v = _visitor(request)
    uid = v.get("sub") if v.get("signed_in") else None
    vid = (x_visitor_id or "").strip()[:64] or None
    if not vid and not uid:
        raise HTTPException(400, "X-Visitor-Id or a visitor token is required")
    return vid, uid


@app.get("/conversations")
def conversations_list(request: Request, x_visitor_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    vid, uid = _owner(request, x_visitor_id)
    items = conversations.list_for(vid, uid)
    return {"items": items, "unread_conversations": sum(1 for i in items if i["unread"] > 0)}


@app.get("/conversations/{session_id}")
def conversations_get(session_id: str, request: Request, x_visitor_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    vid, uid = _owner(request, x_visitor_id)
    h = conversations.history(session_id, vid, uid)
    if h is None:
        raise HTTPException(404, "no such conversation")
    return h


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@app.patch("/conversations/{session_id}")
def conversations_rename(session_id: str, body: TitleIn, request: Request, x_visitor_id: str | None = Header(default=None)):
    """Visitor renames one of their conversations (title_source becomes 'user'; never auto-regenerated)."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    vid, uid = _owner(request, x_visitor_id)
    t = titles.rename(session_id, body.title, vid, uid)
    if t is None:
        raise HTTPException(404, "no such conversation")
    return {"title": t, "title_source": "user"}


@app.post("/conversations/{session_id}/title")
def conversations_title(session_id: str, request: Request, force: bool = False, x_visitor_id: str | None = Header(default=None)):
    """Generate the title now (normally it happens in the background after the first exchange). ?force=1 regenerates."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    vid, uid = _owner(request, x_visitor_id)
    if conversations.history(session_id, vid, uid) is None:
        raise HTTPException(404, "no such conversation")
    return titles.generate(session_id, force=force)


@app.post("/conversations/{session_id}/read")
def conversations_read(session_id: str, request: Request, x_visitor_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    vid, uid = _owner(request, x_visitor_id)
    return {"ok": conversations.mark_read(session_id, vid, uid)}


# ---- composer media: uploads, GIFs, speech
@app.get("/widget-config")
def widget_config(request: Request):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    return {**media.widget_config(), "version": APP_VERSION, "suggestions": suggestions.current()}


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), x_session_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    sid = (x_session_id or "").strip()[:64]
    if not sid:
        raise HTTPException(400, "X-Session-Id required")
    data = await file.read(int(settings.upload_max_mb * 1024 * 1024) + 1)
    try:
        return media.save_upload(sid, file.filename or "file", data)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/uploads/{uid}")
def upload_get(uid: str):
    u = media.get_upload(uid)
    if not u or not Path(u["path"]).exists():
        raise HTTPException(404, "not found")
    return FileResponse(u["path"], media_type=u["mime"], filename=u["name"] if not u["mime"].startswith("image/") else None)


@app.get("/gifs")
def gifs(request: Request, q: str = ""):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    return media.gif_search(q)


@app.post("/stt")
async def stt(request: Request, file: UploadFile = File(...), language: str | None = Form(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    if not media.stt_available():
        raise HTTPException(501, "speech-to-text is not configured on the server")
    data = await file.read(media.AUDIO_MAX_BYTES + 1)
    try:
        return {"text": media.transcribe(data, file.filename or "audio.webm", file.content_type or "audio/webm", language)}
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        log.warning("stt failed: %s", e)
        raise HTTPException(502, "transcription failed")


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@app.post("/tts")
def tts(body: TtsIn, request: Request):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    if not media.tts_available():
        raise HTTPException(501, "text-to-speech is not configured on the server")
    try:
        audio, mime = media.speak(body.text)
    except Exception as e:
        log.warning("tts failed: %s", e)
        raise HTTPException(502, "speech synthesis failed")
    return Response(content=audio, media_type=mime)


@app.get("/me")
def me(request: Request, x_visitor_id: str | None = Header(default=None), x_session_id: str | None = Header(default=None)):
    """What the widget may prefill for this visitor (signed-in name/email from the X-Visitor-Token header) plus the
    return-visitor memory for the device (X-Visitor-Id): greeting copy, upcoming booking, details typed before."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    v = _visitor(request)
    out = {k: v.get(k) for k in ("signed_in", "name", "email", "verified", "via")}
    if settings.visitor_memory and (x_visitor_id or v.get("signed_in")):
        p = memory.profile((x_visitor_id or "").strip()[:64] or None, v.get("sub") if v.get("signed_in") else None, (x_session_id or "").strip()[:64] or None)
        out["memory"] = memory.public(p)
        if not v.get("signed_in"):  # hints from their own earlier forms; the booking/hand-over forms prefill them, unverified
            out["name"] = out.get("name") or p.get("name")
            out["email"] = out.get("email") or p.get("email")
    return out


@app.post("/handover")
def handover(body: HandoverIn, request: Request):
    """Visitor asks for a human: store it as a lead, email the host with the recent conversation."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    v = _visitor(request)
    name, email = body.name, body.email
    if v.get("signed_in") and v.get("verified"):  # a verified identity beats whatever the form says
        name, email = v.get("name") or name, v.get("email") or email
        tracking.attach_user(body.session_id, v)
    if not _EMAIL.match(email.strip()):
        raise HTTPException(422, "that email address doesn't look right")
    try:
        result = inbox.save_handover(body.session_id, name, email, body.message, send_host_brief)
    except Exception as e:
        log.error("handover failed: %s", e)
        raise HTTPException(500, "could not save the request; please email " + settings.host_email)
    return {"ok": True, **result, "host_email": settings.host_email}


# ---- in-chat booking (docs/BOOKING.md)
def _base_url(request: Request) -> str:
    return settings.public_base_url or str(request.base_url).rstrip("/")


@app.get("/booking/availability")
def booking_availability(request: Request, schedule: str = "", days: int | None = None, tz: str = "UTC"):
    """Every slot of the next BOOKING_DAYS_AHEAD days for one call type, open or not, in the visitor's timezone."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    return avail.availability(_booking_service, schedule, days, tz, busy_fn=store_bookings.busy_between)


@app.post("/booking/confirm")
def booking_confirm(body: ConfirmIn, request: Request, x_session_id: str | None = Header(default=None)):
    """The visitor pressed 'Confirm booking': re-check the slot, book on Zoom, store, queue both emails."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    sid = (x_session_id or "").strip()[:64] or None
    if not _booking_limiter.allow(sid or _client_ip(request)):
        raise HTTPException(429, "Too many booking attempts. Please wait a minute and try again.")
    v = _visitor(request)
    name, email = body.name, body.email
    if v.get("signed_in") and v.get("verified"):  # a verified identity beats whatever the form says
        name, email = v.get("name") or name, v.get("email") or email
        if sid:
            tracking.attach_user(sid, v)
    req = flow.ConfirmRequest(schedule_slug=body.schedule_slug, start=body.start, name=name, email=email, visitor_tz=body.timezone,
                              company=body.company, notes=body.notes, session_id=sid, extra={"base_url": _base_url(request)})
    _booking_service.session_id = sid
    try:
        res = flow.confirm(_booking_service, req)
    except Exception as e:
        log.error("booking confirm failed: %s", e)
        return {"status": "error", "message": "Zoom or the server did not respond. Please try again.", "retry": True}
    if res.get("status") in ("confirmed", "pending_zoom") and sid:
        b = res["booking"]
        line = (f"Booking confirmed: {b['schedule_name']} on {b['label_visitor']}." if res["status"] == "confirmed"
                else f"Time held: {b['schedule_name']} on {b['label_visitor']}; the visitor still has to confirm on Zoom.")
        inbox.log_message(sid, "assistant", line, outcome="booking", question=f"[confirm] {b['schedule_slug']} {b['start_iso']}")
    return res


def _booking_or_404(booking_id: int, t: str) -> dict:
    b = store_bookings.get(booking_id)
    if not b or not t or b.get("manage_token") != t:
        raise HTTPException(404, "booking not found")
    return b


@app.get("/booking/{booking_id}/ics")
def booking_ics(booking_id: int, t: str = ""):
    b = _booking_or_404(booking_id, t)
    return Response(content=ics.build(b, templates.get_templates().get("host_name") or "Deep"), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="deep-call-{booking_id}.ics"'})


def _manage_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                        f"<title>{title}</title></head><body style='margin:0;background:#000;color:#F2F3F5;font-family:-apple-system,Segoe UI,Roboto,sans-serif'>"
                        f"<div style='max-width:520px;margin:48px auto;padding:28px;background:#0F0F10;border:1px solid #1F1F22;border-radius:16px'>"
                        f"<div style='color:#F28C28;font-weight:700;font-size:13px;margin-bottom:12px'>ask deep &gt;_</div><h1 style='font-size:20px'>{title}</h1>{body}"
                        f"</div></body></html>")


@app.get("/booking/{booking_id}/manage")
def booking_manage(booking_id: int, t: str = ""):
    b = _booking_or_404(booking_id, t)
    v = flow._booking_view(b)
    if b.get("status") == "cancelled":
        return _manage_page("This booking is cancelled", f"<p>{v['schedule_name']} on {v['label_visitor']} was cancelled.</p>"
                            f"<p><a style='color:#F28C28' href='{settings.site_base_url}'>Book a new time in the chat</a></p>")
    return _manage_page("Your booking", f"<p><b>{v['schedule_name']}</b><br>{v['label_visitor']}<br>{v['duration_min']} min with Deep</p>"
                        + (f"<p><a style='color:#F28C28' href='{v['join_url']}'>Join Zoom</a></p>" if v.get("join_url") else "")
                        + f"<p><a style='color:#F28C28' href='{v['ics_url']}'>Add to calendar (.ics)</a></p>"
                        f"<p style='margin-top:24px'>Need a different time? Cancel below, then pick a new one in the chat on "
                        f"<a style='color:#F28C28' href='{settings.site_base_url}'>{settings.site_base_url.replace('https://', '')}</a>.</p>"
                        f"<form method='post' action='/booking/{booking_id}/cancel?t={t}'><button style='background:#E5484D;color:#fff;border:0;"
                        f"padding:12px 20px;border-radius:999px;font-size:15px;cursor:pointer'>Cancel this booking</button></form>")


@app.post("/booking/{booking_id}/cancel")
def booking_cancel(booking_id: int, t: str = ""):
    b = _booking_or_404(booking_id, t)
    r = flow.cancel(b, _booking_service)
    if b.get("session_id"):
        inbox.log_message(b["session_id"], "assistant", f"Booking cancelled: {b.get('schedule_name')} on {flow._booking_view(b)['label_visitor']}.",
                          outcome="booking")
    return _manage_page("Booking cancelled", "<p>Done. Both you and Deep get an email.</p>"
                        + (f"<p style='color:#8A8D93'>{r.get('zoom_note')}</p>" if r.get("zoom_note") else "")
                        + f"<p><a style='color:#F28C28' href='{settings.site_base_url}'>Pick a new time in the chat</a></p>")


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": APP_VERSION, "spend_today_usd": round(spend_today(), 4), "origins": settings.origins}


@app.post("/admin/recrawl")
def recrawl(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return run_ingest()


@app.get("/admin/sessions")
def admin_sessions(days: int = 7, limit: int = 200, x_admin_token: str | None = Header(default=None)):
    """Where chat sessions came from: per-session rows plus country/channel summaries. Needs X-Admin-Token."""
    _require_admin(x_admin_token)
    return tracking.recent_sessions(days, limit)


@app.post("/admin/tracking/purge")
def admin_purge(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return tracking.purge()


# ---- inbox & reporting
@app.get("/admin/metrics")
def admin_metrics(days: int = 7, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return inbox.metrics(days)


@app.get("/admin/conversations")
def admin_conversations(days: int = 7, limit: int = 100, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"days": days, "items": inbox.conversations(days, limit)}


@app.get("/admin/conversations/{session_id}")
def admin_transcript(session_id: str, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return inbox.transcript(session_id)


@app.get("/admin/gaps")
def admin_gaps(days: int = 30, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return inbox.gaps(days)


# ---- owner-editable behaviour
@app.get("/admin/guidance")
def admin_guidance_get(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"text": guidance.get_guidance(), "max_chars": guidance.GUIDANCE_MAX_CHARS}


@app.put("/admin/guidance")
def admin_guidance_put(body: GuidanceIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"text": guidance.set_guidance(body.text)}


@app.get("/admin/custom-answers")
def admin_custom_list(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"items": guidance.list_custom_answers(), "min_score": settings.custom_answer_min_score}


@app.post("/admin/custom-answers")
def admin_custom_add(body: CustomAnswerIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"id": guidance.add_custom_answer(body.question, body.answer, body.link)}


@app.patch("/admin/custom-answers/{answer_id}")
def admin_custom_patch(answer_id: int, body: CustomAnswerPatch, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": guidance.update_custom_answer(answer_id, enabled=body.enabled, question=body.question,
                                                answer=body.answer, link=body.link)}


@app.delete("/admin/custom-answers/{answer_id}")
def admin_custom_delete(answer_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": guidance.delete_custom_answer(answer_id)}


# ---- automations: weekly digest, follow-up nudges, smart suggestions (docs/AUTOMATIONS.md)
@app.get("/admin/digest")
def admin_digest_preview(days: int = 7, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return digest.build(days)


@app.post("/admin/digest/send")
def admin_digest_send(days: int = 7, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return digest.send(days)


@app.post("/admin/nudge/run")
def admin_nudge_run(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return nudge.run()


@app.post("/admin/leads/{lead_id}/confirm")
def admin_lead_confirm(lead_id: int, x_admin_token: str | None = Header(default=None)):
    """The host saw the Zoom confirmation: no reminder goes out and the digest counts it as booked."""
    _require_admin(x_admin_token)
    return {"ok": nudge.confirm(lead_id)}


@app.get("/admin/bookings")
def admin_bookings(days: int = 30, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"items": store_bookings.recent(days), "mail": mailer.default.stats()}


@app.post("/admin/bookings/{booking_id}/cancel")
def admin_booking_cancel(booking_id: int, x_admin_token: str | None = Header(default=None)):
    """Owner cancels a booking (also used by the browser suite to clean up its test bookings)."""
    _require_admin(x_admin_token)
    b = store_bookings.get(booking_id)
    if not b:
        raise HTTPException(404, "booking not found")
    return flow.cancel(b, _booking_service)


@app.get("/admin/suggestions")
def admin_suggestions(refresh: bool = False, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return suggestions.explain(force=refresh)


# ---- email templates
@app.get("/admin/outreach")
def admin_outreach(days: int = 30, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    rules = outreach.list_rules()
    st = outreach.stats(days)
    for r in rules:
        r["summary"] = outreach.summary(r["trigger"])
        r["stats"] = st["by_rule"].get(r["id"], {"fired": 0, "opened": 0, "dismissed": 0, "chatted": 0, "booked": 0})
    return {"enabled": settings.outreach_enabled, "default_greeting": outreach.default_greeting_enabled(), "rules": rules,
            "recent": st["recent"], "days": st["days"], "channels": list(outreach.CHANNELS), "max_rules": outreach.MAX_RULES}


@app.post("/admin/outreach/rules")
def admin_outreach_add(body: OutreachRuleIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    try:
        r = outreach.create_rule(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    r["summary"] = outreach.summary(r["trigger"])
    return r


@app.patch("/admin/outreach/rules/{rule_id}")
def admin_outreach_patch(rule_id: int, body: OutreachRuleIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    try:
        r = outreach.update_rule(rule_id, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not r:
        raise HTTPException(404, "no such rule")
    r["summary"] = outreach.summary(r["trigger"])
    return r


@app.delete("/admin/outreach/rules/{rule_id}")
def admin_outreach_delete(rule_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": outreach.delete_rule(rule_id)}


@app.put("/admin/outreach/settings")
def admin_outreach_settings(body: OutreachSettingsIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    outreach.set_default_greeting(body.default_greeting)
    return {"default_greeting": outreach.default_greeting_enabled()}


@app.post("/admin/outreach/try")
def admin_outreach_try(body: OutreachTryIn, x_admin_token: str | None = Header(default=None)):
    """Dry run: which rule would fire for this activity. Cooldowns and earlier firings are ignored; nothing is recorded."""
    _require_admin(x_admin_token)
    facts = {"returning": body.visits > 1, "visits": body.visits, "name": body.first_name,
             "upcoming": {"schedule_name": "Discovery Call", "label_visitor": "Thu 15 Oct, 16:30"} if body.booking else None}
    payload = {"path": body.path, "page": body.path, "pages": body.pages, "dwell_s": body.dwell_s, "scroll_pct": body.scroll_pct,
               "referrer": body.referrer, "first_page": body.path, "visits": body.visits}
    ctx = outreach.context(payload, facts)
    rules = [r for r in outreach.list_rules() if r["enabled"]]
    rows = [{"id": r["id"], "name": r["name"], **outreach.evaluate(r["trigger"], ctx)} for r in rules]
    hit = next((r for r, row in zip(rules, rows) if row["match"]), None)
    return {"context": {k: ctx[k] for k in ("path", "pages", "dwell_s", "scroll_pct", "referrer_host", "channel", "returning", "booking")},
            "fires": outreach.public_message(hit, ctx) if hit else None, "rules": rows, "default": outreach.default_greeting_enabled()}


@app.get("/admin/email-templates")
def admin_templates_get(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"templates": templates.get_templates(), "defaults": templates.DEFAULTS, "variables": templates.VARIABLES,
            "previews": templates.previews(), "host_email": settings.host_email, "smtp_configured": bool(settings.smtp_host)}


@app.put("/admin/email-templates")
def admin_templates_put(body: TemplatesIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    saved = templates.set_templates(body.templates)
    return {"templates": saved, "previews": templates.previews()}


@app.post("/admin/email-templates/preview")
def admin_templates_preview(body: TemplatesIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"previews": templates.previews(body.templates)}


@app.post("/admin/email-templates/test")
def admin_templates_test(body: TestMailIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return send_test(body.kind)


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


# ---- in-app widget demo (WIDGET_DEMO=true): a host page that embeds <deep-assistant> anonymously and signed in
@app.get("/demo")
def demo_page():
    if not settings.widget_demo:
        raise HTTPException(404, "demo disabled")
    return FileResponse(STATIC / "demo.html")


@app.get("/demo/token")
def demo_token():
    """A sample signed-in user for the demo page. The real host app mints this on ITS backend (docs/WIDGET.md)."""
    if not settings.widget_demo:
        raise HTTPException(404, "demo disabled")
    secret = settings.widget_signing_secret or "demo-only-secret-set-WIDGET_SIGNING_SECRET"
    return {"token": identity.mint("demo-user-1", settings.demo_user_name, settings.demo_user_email, 3600, secret=secret),
            "name": settings.demo_user_name, "email": settings.demo_user_email,
            "note": "" if settings.widget_signing_secret else "WIDGET_SIGNING_SECRET is not set: this token will not verify"}


@app.get("/")
def index_page():
    """The assistant: the web component in panel mode (full screen on phones). /site shows it the way
    deependhq.com embeds it (round launcher, greeting card, quick replies); /legacy is the old standalone page."""
    return FileResponse(STATIC / "index.html")


@app.get("/site")
def site_page():
    return FileResponse(STATIC / "embed-test.html")


@app.get("/widget")
def widget_page():
    return FileResponse(STATIC / "index.html")


@app.get("/legacy")
def legacy_page():
    return FileResponse(STATIC / "chat.html")
