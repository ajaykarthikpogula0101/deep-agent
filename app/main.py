"""FastAPI app: /chat (SSE), /track (session origin beacon), /healthz, /admin/*, static chat page + embeddable widget."""
from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, BeforeValidator, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

import re
from html import escape as html_escape
from urllib.parse import quote as quote_param

from fastapi import File, Form, UploadFile
from fastapi.responses import Response

from app import backup, conversations, digest, email_ask, gaps, geoip_update, guidance, health, host_page, identity, inbox, links, mailer, media, memory, nudge, outcomes, outreach, precall, reminders, session_memory, store_bookings, suggestions, team, templates, titles, tracking, visitors
from app.booking import availability as avail
from app.booking import browser_booking
from app.booking import email_html, flow, ics, zoom_mail
from app.booking.service import BookingService
from app.leader import Leader
from app.booking.email import send_host_brief, send_test
from app import chat as chat_mod
from app import help as help_center
from app.chat import respond, sse
from app.config import settings
from app.db import init_schema, log_event, spend_today
from app.ingest.pipeline import run_ingest
from app.security.limits import RateLimiter, limiter, spend_cap_reached

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

STATIC = Path(__file__).resolve().parent.parent / "static"
APP_VERSION = "2026.10.29.3"  # bump when the widget changes; appended as ?v= to static URLs and shown in the console/footer
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

from app import setup_page  # noqa: E402  (first-run /setup; local-only, gone once data/setup_done exists)

app.include_router(setup_page.router)

_scheduler = BackgroundScheduler()
_leader = Leader()   # app/leader.py: which process runs the scheduled jobs
_track_limiter = RateLimiter(per_minute=60, per_day=3000)  # beacons and visitor-scoped reads (history, bookings, availability); separate from the chat budget
_booking_limiter = RateLimiter(per_minute=4, per_day=12)     # confirm attempts per session (plus the per-email active cap)
_booking_service = BookingService()                         # shared: schedule cache + Zoom token
_outreach_limiter = RateLimiter(per_minute=60, per_day=3000)  # a few checks per page view (app/outreach.py)


@app.on_event("startup")
def _startup() -> None:
    init_schema()
    try:  # sessions a write path missed (booking-only sessions before 2026.10.15) get their row
        tracking.backfill_orphans()
    except Exception as e:
        log.warning("orphan backfill failed: %s", e)
    _scheduler.add_job(run_ingest, CronTrigger.from_crontab(settings.recrawl_cron, timezone=settings.recrawl_tz),
                       id="recrawl", replace_existing=True, misfire_grace_time=3600)
    _scheduler.add_job(tracking.purge, CronTrigger.from_crontab("10 3 * * *", timezone=settings.recrawl_tz),
                       id="tracking_purge", replace_existing=True, misfire_grace_time=3600)
    # session_memory retention (app/session_memory.py); 03:25 keeps clear of the gap drafts at 03:20
    _scheduler.add_job(session_memory.purge, CronTrigger.from_crontab("25 3 * * *", timezone=settings.recrawl_tz),
                       id="memory_purge", replace_existing=True, misfire_grace_time=3600)
    # Ask Deep from booking emails: link analytics after TRACK_RETENTION_DAYS, claims after MEMORY_RETENTION_DAYS
    _scheduler.add_job(email_ask.purge, CronTrigger.from_crontab("30 3 * * *", timezone=settings.recrawl_tz),
                       id="email_ask_purge", replace_existing=True, misfire_grace_time=3600)
    # lookups still pending or failed (provider down, quota, a row that got its IP late) are retried
    _scheduler.add_job(tracking.retry_pending, CronTrigger.from_crontab("*/10 * * * *", timezone=settings.recrawl_tz),
                       id="geo_retry", replace_existing=True, misfire_grace_time=600)
    chain = tracking.providers()
    if "ipapi" in chain:
        log.warning("GEOIP_PROVIDER includes ipapi (ip-api.com): plain HTTP and non-commercial use only")
    if geoip_update.configured():  # MaxMind GeoLite2 for the mmdb provider (app/geoip_update.py)
        if "mmdb" not in chain:
            log.warning("MAXMIND_LICENSE_KEY is set but GEOIP_PROVIDER=%s has no mmdb: the GeoLite2 files are downloaded but "
                        "never read; set GEOIP_PROVIDER=mmdb,ipwho", settings.geoip_provider)
        if geoip_update.start_background():
            log.info("GeoLite2 files missing or stale in %s: downloading in the background", geoip_update.data_dir())
        # weekly, Wednesday 04:50 host time: MaxMind publishes on Tuesdays and Fridays; the EULA allows files up to 30 days old
        _scheduler.add_job(geoip_update.run, CronTrigger.from_crontab("50 4 * * 3", timezone=settings.host_timezone),
                           id="geoip_update", replace_existing=True, misfire_grace_time=6 * 3600)
    if "mmdb" in chain and tracking.mmdb_problem():
        log.warning("GEOIP_PROVIDER includes mmdb but %s; it is skipped%s", tracking.mmdb_problem(),
                    " until the download finishes" if geoip_update.configured() else " (set MAXMIND_LICENSE_KEY to download them)")
    # every minute: team replies the visitor has not read for TEAM_EMAIL_AFTER_MINUTES are emailed to them (app/team.py)
    _scheduler.add_job(team.notify_unread_replies, CronTrigger.from_crontab("* * * * *", timezone=settings.host_timezone),
                       id="team_reply_emails", replace_existing=True, misfire_grace_time=120)
    if settings.backup_enabled:  # nightly pg_dump outside Docker (app/backup.py); one now if the newest is over a day old
        _scheduler.add_job(backup.run, CronTrigger.from_crontab(settings.backup_cron, timezone=settings.host_timezone),
                           id="db_backup", replace_existing=True, misfire_grace_time=6 * 3600)
        backup.take_if_stale_async()
    if settings.help_enabled:  # starter help center + missing article vectors, in the background (app/help.py)
        help_center.seed_async()
    if settings.health_checks:  # every 10 min: model key, credit, failed answers, database, email, booking robot (app/health.py)
        _scheduler.add_job(health.run, CronTrigger.from_crontab(settings.health_cron, timezone=settings.host_timezone),
                           id="health", replace_existing=True, misfire_grace_time=600, next_run_time=datetime.now(timezone.utc))
    if settings.browser_booking_enabled and zoom_mail.enabled():  # every 10 min: join links Zoom emailed late (app/booking/zoom_mail.py)
        _scheduler.add_job(zoom_mail.backfill, CronTrigger.from_crontab("*/10 * * * *", timezone=settings.host_timezone),
                           id="zoom_link_backfill", replace_existing=True, misfire_grace_time=600)
    if settings.digest_enabled:  # weekly digest to the host (app/digest.py)
        _scheduler.add_job(digest.run, CronTrigger.from_crontab(settings.digest_cron, timezone=settings.host_timezone),
                           id="weekly_digest", replace_existing=True, misfire_grace_time=6 * 3600)
    if settings.nudge_enabled:  # hourly: remind visitors whose Zoom hand-off is still unconfirmed (app/nudge.py)
        _scheduler.add_job(nudge.run, CronTrigger.from_crontab("15 * * * *", timezone=settings.host_timezone),
                           id="nudges", replace_existing=True, misfire_grace_time=1800)
    if settings.reminder_enabled:  # hourly: the day-before reminder for upcoming bookings (app/reminders.py)
        _scheduler.add_job(reminders.run, CronTrigger.from_crontab("45 * * * *", timezone=settings.host_timezone),
                           id="reminders", replace_existing=True, misfire_grace_time=1800)
    if settings.precall_enabled and settings.hot_lead_alerts:  # hourly: hot leads who left an email but booked nothing (app/precall.py)
        _scheduler.add_job(precall.run_alerts, CronTrigger.from_crontab("30 * * * *", timezone=settings.host_timezone),
                           id="hot_leads", replace_existing=True, misfire_grace_time=1800)
    if settings.gap_loop_enabled:  # nightly: drafted answers for unanswered questions; every 15 min: send approved answers (app/gaps.py)
        _scheduler.add_job(gaps.run, CronTrigger.from_crontab(settings.gap_cron, timezone=settings.host_timezone),
                           id="gap_drafts", replace_existing=True, misfire_grace_time=6 * 3600)
        _scheduler.add_job(gaps.send_due, CronTrigger.from_crontab("*/15 * * * *", timezone=settings.host_timezone),
                           id="gap_followups", replace_existing=True, misfire_grace_time=900)
    if settings.outcomes_enabled:  # hourly: "how did the call go?" to the host; nightly: re-learn the lead score (app/outcomes.py)
        _scheduler.add_job(outcomes.send_asks, CronTrigger.from_crontab("5 * * * *", timezone=settings.host_timezone),
                           id="outcome_asks", replace_existing=True, misfire_grace_time=1800)
        _scheduler.add_job(outcomes.learn, CronTrigger.from_crontab("40 3 * * *", timezone=settings.host_timezone),
                           id="score_learning", replace_existing=True, misfire_grace_time=6 * 3600)
    if settings.outreach_enabled:  # starter outreach rules, once each (app/outreach.py)
        outreach.seed_if_empty()
        outreach.seed_v2()
    p = links.public_problem()
    if p:
        log.warning("%s: buttons in emails (booking page, manage, outcome) will not open from a phone", p)
    elif links.plain_http():
        log.warning("PUBLIC_BASE_URL is plain http: email link tokens travel unencrypted")
    if not settings.link_secret:
        log.warning("LINK_SECRET is not set: email links are signed with a key derived from ADMIN_TOKEN; rotating it breaks every link already sent")
    if settings.domain_check:
        try:
            import dns.resolver  # noqa: F401  (app/enrich.py checks business email domains with it)
        except ImportError:
            log.warning("dnspython missing: email domains read as not checked")
    # emails a restart left unsent go out again (app/mailer.py); only the scheduler leader runs this
    _scheduler.add_job(mailer.default.recover, CronTrigger.from_crontab("*/5 * * * *", timezone=settings.host_timezone),
                       id="outbox_recover", replace_existing=True, misfire_grace_time=300)
    # the jobs run in one process only: start paused, the holder of the scheduler lock resumes it (app/leader.py)
    _scheduler.start(paused=True)
    _leader.start(on_lead=_scheduler.resume, on_lose=_scheduler.pause)
    log.info("recrawl scheduled: '%s' (%s); tracking=%s geo=%s ip_mode=%s retention=%sd",
             settings.recrawl_cron, settings.recrawl_tz, settings.tracking_enabled, ",".join(chain) or "none",
             settings.track_ip_mode, settings.track_retention_days)


@app.on_event("shutdown")
def _shutdown() -> None:
    _scheduler.shutdown(wait=False)
    _leader.stop()


def _clipped(n: int) -> BeforeValidator:
    return BeforeValidator(lambda v: v[:n] if isinstance(v, str) else v)


# Page context the browser sends (landing URL, referrer, path, title, language): cut to size, never a 422. A visitor who
# landed on a long tracking or redirect URL must still be able to chat and book; the tail of a URL is not worth a request.
PageUrl = Annotated[str | None, _clipped(2000)]
PagePath = Annotated[str | None, _clipped(500)]
PageTitle = Annotated[str | None, _clipped(200)]
PageShort = Annotated[str | None, _clipped(16)]   # navigator.language, screen size


class BeaconIn(BaseModel):
    """The /track fields, carried by /chat and /booking/confirm while the widget has no confirmed /track (lost beacon,
    blocked path). Kept only as first values, like the beacon's."""
    page: PageUrl = None
    referrer: PageUrl = None
    lang: PageShort = None
    screen: PageShort = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=40)
    timezone: str = Field(default="UTC", max_length=64)
    user_name: str | None = Field(default=None, max_length=120)   # unverified hints from the host app
    user_email: str | None = Field(default=None, max_length=200)
    attachments: list[str] = Field(default_factory=list, max_length=5)  # upload ids from POST /upload (this session's)
    beacon: BeaconIn | None = None
    outreach_event: int | None = Field(default=None, ge=1)  # the pop-up this chat was opened from (first message only)
    ask_auto: bool = False  # the question a booking email's Ask Deep chip carried, sent by the page (not typed)


def _visitor(request: Request, hint_name: str | None = None, hint_email: str | None = None) -> dict:
    return identity.describe(identity.verify(request.headers.get("x-visitor-token")), hint_name, hint_email)


class TrackIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    visitor_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    page: PageUrl = None
    referrer: PageUrl = None
    timezone: str | None = Field(default=None, max_length=64)
    lang: PageShort = None
    screen: PageShort = None


class OutreachCheckIn(BaseModel):
    """Activity snapshot from the loader (docs/OUTREACH.md). Nothing here is stored except the page of a firing."""
    visitor_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    page: PageUrl = None
    path: PagePath = None
    title: PageTitle = None
    first_page: PageUrl = None
    pages: list[str] = Field(default_factory=list, max_length=60)
    dwell_s: int = Field(default=0, ge=0, le=1_000_000)
    scroll_pct: int = Field(default=0, ge=0, le=100)
    referrer: PageUrl = None
    visits: int = Field(default=0, ge=0, le=100_000)
    shown: list[int] = Field(default_factory=list, max_length=60)
    gpc: bool = False                                        # Global Privacy Control or DNT: no visitors row, no lookup
    tz: str | None = Field(default=None, max_length=64)      # browser timezone (privacy region, country sanity check)


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
    default_greeting: bool | None = None
    ip_context: bool | None = None   # the console's soft switch for the visitor's network in pop-ups


class OutreachTryIn(BaseModel):
    """Dry run from the console: which rule would fire for this activity (nothing is recorded)."""
    path: Annotated[str, _clipped(500)] = "/"
    pages: list[str] = Field(default_factory=list, max_length=60)
    dwell_s: int = Field(default=0, ge=0, le=100_000)
    scroll_pct: int = Field(default=0, ge=0, le=100)
    referrer: PageUrl = None
    visits: int = Field(default=1, ge=0, le=100_000)
    booking: bool = False
    first_name: str | None = Field(default=None, max_length=60)
    net_kind: str | None = Field(default=None, max_length=20)
    org: str | None = Field(default=None, max_length=60)
    country_code: str | None = Field(default=None, max_length=2)
    country: str | None = Field(default=None, max_length=60)
    engaged: str | None = Field(default=None, pattern=r"^(never|chatted|booked)$")
    approved: bool = False


class OrgPatchIn(BaseModel):
    """Owner edits to one organisation in Outreach → Organisations visiting."""
    org: str | None = Field(default=None, max_length=60)
    industry: str | None = Field(default=None, max_length=40)
    line: str | None = Field(default=None, max_length=170)
    status: str | None = Field(default=None, pattern=r"^(approved|off|auto)$")


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
    kind: str = Field(pattern=r"^(host|visitor_booking|visitor_handover|visitor_nudge|visitor_confirmed|host_booking|visitor_rescheduled|visitor_cancelled|visitor_reminder|visitor_gap)$")


class AttendeeIn(BaseModel):
    name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=200)


class ConfirmIn(BaseModel):
    attendees: list[AttendeeIn] = Field(default_factory=list, max_length=10)  # extra guests; flow.clean_attendees caps at 5
    schedule_slug: str = Field(min_length=1, max_length=120)
    start: str = Field(min_length=10, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    company: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    timezone: str = Field(default="UTC", max_length=64)
    beacon: BeaconIn | None = None


class RescheduleIn(BaseModel):
    start: str = Field(min_length=10, max_length=40)
    timezone: str = Field(default="UTC", max_length=64)


class CustomAnswerPatch(BaseModel):
    enabled: bool | None = None
    question: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=3000)
    link: str | None = Field(default=None, max_length=500)


def _client_ip(req: Request) -> str:
    return tracking.client_ip(req.headers, req.client.host if req.client else None)


def _ensure(request: Request, sid: str | None, vid: str | None, beacon: BeaconIn | None = None, tz: str | None = None, *,
            message: bool = False) -> None:
    """Make sure this session has its sessions row (visitor id, IP, and the page if a beacon came along)."""
    if not tracking.valid_sid(sid):
        return
    b = beacon or BeaconIn()
    tracking.ensure_session(sid, visitor_id=tracking.clean_vid(vid), ip=_client_ip(request),
                            user_agent=request.headers.get("user-agent"), page=b.page, referrer=b.referrer, lang=b.lang,
                            screen=b.screen, client_tz=tz if beacon else None,  # the bodies default tz to 'UTC'
                            message=message)


def _require_admin(token: str | None) -> None:
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(403, "forbidden")


def _origin_ok(req: Request) -> bool:
    """Belt and braces on top of CORS: non-browser callers must still present an allowed Origin/Referer.
    Not authentication (headers can be forged); it just stops casual abuse of the endpoint."""
    origin = req.headers.get("origin") or req.headers.get("referer") or ""
    if not origin:  # local dev / single-machine installs only (the embedded database is local by construction)
        db = settings.database_url
        return "@localhost" in db or "@127.0.0.1" in db or "host=/" in db or bool(os.environ.get("ROBIN_EMBEDDED_DB"))
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
    ip = _client_ip(request)
    if not _outreach_limiter.allow(ip):
        raise HTTPException(429, "too many requests")
    t0 = time.perf_counter()
    vid = tracking.clean_vid(body.visitor_id or x_visitor_id)
    payload = body.model_dump()
    vis = visitors.observe(vid, ip, request.headers.get("user-agent"), payload, request.headers.get("host"))
    out = {**outreach.check(payload, vid, visitor=vis), "enabled": True}
    ms = (time.perf_counter() - t0) * 1000
    if ms > 50:
        log.debug("outreach check took %.0f ms", ms)
    return out


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


class AskClaimIn(BaseModel):
    token: str = Field(min_length=10, max_length=160)
    q: str | None = Field(default=None, max_length=24, pattern=r"^[a-z_]+$")
    gpc: bool = False                                   # Global Privacy Control or DNT: booking context only, no memory binding
    timezone: str | None = Field(default=None, max_length=64)


_ask_limiter = RateLimiter(per_minute=10, per_day=200)  # claims per token


@app.get("/ask")
def ask_page():
    """Ask Deep from a booking email (app/email_ask.py): the assistant page. The signed token rides in the URL fragment,
    which never reaches this server; the page exchanges it by POST /ask/claim. This GET reads and writes nothing, so a
    mail scanner opening the link changes nothing."""
    return FileResponse(STATIC / "index.html", headers=_PRIVATE)


@app.post("/ask/claim")
def ask_claim(body: AskClaimIn, request: Request, x_session_id: str | None = Header(default=None),
              x_visitor_id: str | None = Header(default=None)):
    """The page opened from an email link: tie this chat session to that booking and say what to show. Sends no message,
    creates no lead, changes no booking and proves no address."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    if not settings.email_ask_enabled:
        raise HTTPException(404, "not found")
    if not tracking.valid_sid(x_session_id):
        raise HTTPException(400, "X-Session-Id is required")
    if not _ask_limiter.allow(email_ask.token_id(body.token)):
        raise HTTPException(429, "too many requests")
    grant = email_ask.verify(body.token)
    if not grant:
        email_ask.event("invalid", session_id=x_session_id)
        raise HTTPException(404, "This link is not valid.")
    if grant.get("expired"):
        email_ask.event("expired", grant, session_id=x_session_id)
        raise HTTPException(410, "This link has expired.")
    vid = tracking.clean_vid(x_visitor_id)
    tracking.ensure_session(x_session_id, visitor_id=vid, ip=_client_ip(request), user_agent=request.headers.get("user-agent"),
                            client_tz=body.timezone)   # never the page or referrer: the token stays out of storage
    gpc = body.gpc or request.headers.get("sec-gpc") == "1" or request.headers.get("dnt") == "1"
    return email_ask.claim(grant, x_session_id, vid, body.q, gpc=gpc)


@app.post("/chat")
async def chat(body: ChatIn, request: Request, x_session_id: str | None = Header(default=None),
               x_visitor_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    session_id = x_session_id or str(uuid.uuid4())
    if not limiter.allow(_client_ip(request)):
        log_event("rate_limited", session_id, {"ip": _client_ip(request)})
        raise HTTPException(429, "Too many messages. Please try again in a minute.")
    # one upsert: message count, the visitor id (the widget's Messages list) and, while untracked, the beacon fields
    auto = body.ask_auto and not body.history   # an email chip's question: the first turn only, and not counted as typed
    _ensure(request, session_id, x_visitor_id, body.beacon, body.timezone, message=not auto)
    visitor = _visitor(request, body.user_name, body.user_email)
    if visitor.get("signed_in"):
        tracking.attach_user(session_id, visitor)
    if spend_cap_reached():
        log_event("spend_cap", session_id, {"usd": spend_today()})

        def capped():
            yield sse({"type": "refusal", "reason": "spend_cap"})
            yield sse({"type": "token", "text": "The assistant has hit its daily budget. Please book directly at "
                                                f"{settings.zoom_booking_base} or email {settings.host_email}."})
            yield sse({"type": "done"})

        return StreamingResponse(capped(), media_type="text/event-stream")

    extra, attached = media.attachments_block(body.attachments, session_id) if body.attachments else ("", [])
    # the memory reads run off the event loop (profile() is ~20 ms of DB work)
    mem, data, pending, ocx, bcx = await run_in_threadpool(_prompt_parts, x_visitor_id, visitor.get("sub") if visitor.get("signed_in") else None,
                                                           session_id, len(body.history), body.outreach_event, auto)
    if pending:  # earlier sessions the model has not read yet: their gists are ready a turn or two later
        session_memory.catch_up_async(pending)
    gen = respond(body.message, body.history, body.timezone, session_id, visitor=visitor, extra_context=extra, attachments=attached,
                  memory=mem, memory_data=data, outreach_context=ocx, booking_context=bcx, user_reason="email_chip" if auto and bcx else None)
    return StreamingResponse(iterate_in_threadpool(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Session-Id": session_id})


def _prompt_parts(visitor_id: str | None, user_id: str | None, session_id: str, n_history: int,
                  outreach_event: int | None = None, auto: bool = False) -> tuple[str, str, list[str], str, str]:
    """_memory_parts() plus the outreach DATA message (the pop-up this chat was opened from and its network guess,
    app/outreach.chat_context) and the Booking context DATA message of a chat opened from a booking email
    (app/email_ask.data_block); '' when there is none. A typed message in such a chat is marked for the score."""
    mem, data, pending = _memory_parts(visitor_id, user_id, session_id, n_history)
    ocx = ""
    if settings.outreach_enabled:
        try:
            ocx = outreach.data_block(outreach.chat_context(session_id, tracking.clean_vid(visitor_id), outreach_event))
        except Exception as e:  # pop-up context is optional: never the chat's problem
            log.warning("outreach chat context failed: %s", e)
    bcx = ""
    if settings.email_ask_enabled:
        bcx = email_ask.data_block(session_id)
        if bcx and not auto:
            email_ask.mark_typed(session_id)
    return mem, data, pending, ocx, bcx


def _memory_parts(visitor_id: str | None, user_id: str | None, session_id: str, n_history: int) -> tuple[str, str, list[str]]:
    """(system section, DATA message, earlier sessions to catch up). Without a visitor id the current conversation still
    gives booking and form facts."""
    if not settings.visitor_memory:
        return "", "", []
    p = memory.profile(visitor_id, user_id, session_id)
    if settings.working_memory:
        sm = session_memory.get(session_id)
    else:  # CURRENT CONVERSATION off: neither working memory nor form facts
        sm, p = None, dict(p, form=None)
    data = memory.data_block(p, sm, window_full=n_history >= chat_mod.MAX_HISTORY)
    return memory.prompt_block(p), data, p.get("memory_pending") or []


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


@app.get("/bookings")
def bookings_list(request: Request, x_visitor_id: str | None = Header(default=None)):
    """The History page's "Your bookings": upcoming, past and cancelled bookings of this visitor, with what each one can
    still do (join, confirm on Zoom, add to calendar, reschedule, cancel, book again)."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    vid, uid = _owner(request, x_visitor_id)  # a visitor-scoped read; not counted against the beacon limiter
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    items = []
    for b in store_bookings.list_for_visitor(vid, uid):
        v = flow._booking_view(dict(b, **flow.manage_urls(int(b["id"]), b.get("manage_token") or "", _base_url(request))))
        active = b.get("status") in ("confirmed", "pending_zoom")
        upcoming = active and b["start_utc"] > now
        movable = b.get("method") == "handoff" or (b.get("method") == "browser" and bool(b.get("zoom_reschedule_url")))
        tz = b.get("visitor_tz") or settings.host_timezone
        from app.booking.zoom import Slot

        v.update(state="cancelled" if b.get("status") == "cancelled" else "upcoming" if upcoming else "past",
                 can_reschedule=upcoming and movable and b["start_utc"] > now + timedelta(minutes=30),
                 can_cancel=upcoming and b["start_utc"] > now + timedelta(minutes=5),
                 old_label_visitor=Slot(b["previous_start_utc"], b.get("duration_min") or 0).label(tz) if b.get("previous_start_utc") else None,
                 rescheduled_at=b.get("rescheduled_at").isoformat() if b.get("rescheduled_at") else None,
                 cancelled_at=b.get("cancelled_at").isoformat() if b.get("cancelled_at") else None,
                 created_at=b.get("created_at").isoformat() if b.get("created_at") else None)
        v.pop("passcode", None)
        items.append(v)
    return {"items": items, "upcoming": sum(1 for i in items if i["state"] == "upcoming")}


@app.get("/conversations/{session_id}")
def conversations_get(session_id: str, request: Request, x_visitor_id: str | None = Header(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    vid, uid = _owner(request, x_visitor_id)
    h = conversations.history(session_id, vid, uid)
    if h is None:
        raise HTTPException(404, "no such conversation")
    return h


class RatingIn(BaseModel):
    score: int = Field(ge=1, le=5)
    note: str | None = Field(default=None, max_length=1000)


@app.post("/conversations/{session_id}/rating")
def conversations_rate(session_id: str, body: RatingIn, request: Request, x_visitor_id: str | None = Header(default=None)):
    """The visitor rates the whole conversation 1-5 (app/team.py)."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    vid, uid = _owner(request, x_visitor_id)
    if not team.rate(session_id, vid, uid, body.score, body.note):
        raise HTTPException(404, "no such conversation")
    return {"ok": True}


@app.get("/conversations/{session_id}/updates")
def conversations_updates(session_id: str, request: Request, after: int = 0, x_visitor_id: str | None = Header(default=None)):
    """Team replies newer than `after` and where the hand-off stands; the widget polls this while a chat with the team is open."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    vid, uid = _owner(request, x_visitor_id)
    out = team.updates(session_id, vid, uid, after)
    if out is None:
        raise HTTPException(404, "no such conversation")
    return out


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
    return {**media.widget_config(), "version": APP_VERSION, "suggestions": suggestions.current(), "booking_mode": browser_booking.mode(),
            "reminders": settings.reminder_enabled, "help": settings.help_enabled, "host_photo": "/static/email/host.png",
            "host_name": getattr(settings, "host_full_name", "") or "Deep"}


# ---- help center (app/help.py): the widget's Help tab and Home search
def _help_guard(request: Request) -> None:
    if not settings.help_enabled:
        raise HTTPException(404, "help center is off")
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")


@app.get("/help")
def help_overview(request: Request):
    _help_guard(request)
    return help_center.overview()


@app.get("/help/collections/{slug}")
def help_collection(slug: str, request: Request):
    _help_guard(request)
    out = help_center.collection(slug)
    if out is None:
        raise HTTPException(404, "no such collection")
    return out


@app.get("/help/articles/{slug}")
def help_article(slug: str, request: Request):
    _help_guard(request)
    out = help_center.article(slug)
    if out is None:
        raise HTTPException(404, "no such article")
    return out


@app.get("/help/search")
def help_search(request: Request, q: str = ""):
    _help_guard(request)
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    return {"q": q[:200], "items": help_center.search(q)}


@app.get("/admin/help")
def admin_help(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return help_center.admin_list()


def _help_save(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.post("/admin/help/collections")
def admin_help_collection_new(body: dict, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return _help_save(help_center.save_collection, body)


@app.put("/admin/help/collections/{cid}")
def admin_help_collection_edit(cid: int, body: dict, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return _help_save(help_center.save_collection, body, cid)


@app.delete("/admin/help/collections/{cid}")
def admin_help_collection_delete(cid: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": help_center.delete_collection(cid)}


@app.post("/admin/help/articles")
def admin_help_article_new(body: dict, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return _help_save(help_center.save_article, body)


@app.put("/admin/help/articles/{aid}")
def admin_help_article_edit(aid: int, body: dict, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return _help_save(help_center.save_article, body, aid)


@app.delete("/admin/help/articles/{aid}")
def admin_help_article_delete(aid: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": help_center.delete_article(aid)}


@app.post("/admin/help/refresh")
def admin_help_refresh(x_admin_token: str | None = Header(default=None)):
    """Rebuild the articles made from deependhq.com pages (articles you edited are kept)."""
    _require_admin(x_admin_token)
    return help_center.seed(force_site=True)


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
async def stt(request: Request, file: UploadFile = File(...), language: str | None = Form(default=None), hints: str | None = Form(default=None)):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    if not media.stt_available():
        raise HTTPException(501, "speech-to-text is not configured on the server")
    data = await file.read(media.AUDIO_MAX_BYTES + 1)
    try:
        return media.transcribe(data, file.filename or "audio.webm", file.content_type or "audio/webm", language, hints)
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
        session_memory.catch_up_async(p.get("memory_pending"))  # a returning visitor: earlier sessions' gists before they write
        if not v.get("signed_in"):  # hints from their own earlier forms; the booking/hand-over forms prefill them, unverified
            out["name"] = out.get("name") or p.get("name")
            out["email"] = out.get("email") or p.get("email")
    return out


@app.post("/handover")
def handover(body: HandoverIn, request: Request, x_visitor_id: str | None = Header(default=None)):
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
    _ensure(request, body.session_id, x_visitor_id)
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
def booking_confirm(body: ConfirmIn, request: Request, x_session_id: str | None = Header(default=None),
                    x_visitor_id: str | None = Header(default=None)):
    """The visitor pressed 'Confirm booking': re-check the slot, book on Zoom, store, queue both emails."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    sid = (x_session_id or "").strip()[:64] or None
    if not _booking_limiter.allow(sid or _client_ip(request)):
        raise HTTPException(429, "Too many booking attempts. Please wait a minute and try again.")
    # the row (and its geo, on the background executor while Zoom books) exists before flow.confirm reads the origin
    _ensure(request, sid, x_visitor_id, body.beacon, body.timezone)
    v = _visitor(request)
    name, email = body.name, body.email
    if v.get("signed_in") and v.get("verified"):  # a verified identity beats whatever the form says
        name, email = v.get("name") or name, v.get("email") or email
        if sid:
            tracking.attach_user(sid, v)
    req = flow.ConfirmRequest(schedule_slug=body.schedule_slug, start=body.start, name=name, email=email, visitor_tz=body.timezone,
                              company=body.company, notes=body.notes, session_id=sid, extra={"base_url": _base_url(request)},
                              attendees=[a.model_dump() for a in body.attendees])
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
    """The visitor's own booking, by its manage token. Bytes compare: a non-ASCII token is a 404, never a 500."""
    b = store_bookings.get(booking_id)
    if not b or not t or len(t) > 128 or not hmac.compare_digest((b.get("manage_token") or "").encode(), t.encode()):
        raise HTTPException(404, "booking not found")
    return b


# pages behind a token in the URL: never cached, never sent on as a Referer, never indexed or framed
_PRIVATE = {"Cache-Control": "no-store, private", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow",
            "X-Frame-Options": "DENY"}


@app.get("/booking/{booking_id}/ics")
def booking_ics(booking_id: int, t: str = ""):
    b = _booking_or_404(booking_id, t)
    return Response(content=ics.build(b, templates.get_templates().get("host_name") or "Deep"), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="deep-call-{booking_id}.ics"', **_PRIVATE})


def _manage_page(title: str, body: str) -> HTMLResponse:
    title = html_escape(title)
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                        f"<title>{title}</title></head><body style='margin:0;background:#000;color:#F2F3F5;font-family:-apple-system,Segoe UI,Roboto,sans-serif'>"
                        f"<div style='max-width:520px;margin:48px auto;padding:28px;background:#0F0F10;border:1px solid #1F1F22;border-radius:16px'>"
                        f"<div style='color:#F28C28;font-weight:700;font-size:13px;margin-bottom:12px'>ask deep &gt;_</div><h1 style='font-size:20px'>{title}</h1>{body}"
                        f"</div></body></html>", headers=_PRIVATE)


_RED_PILL = "display:inline-block;background:#E5484D;color:#fff;border:0;padding:12px 20px;border-radius:999px;font-size:15px;text-decoration:none;cursor:pointer"


@app.get("/booking/{booking_id}/manage")
def booking_manage(booking_id: int, t: str = ""):
    b = _booking_or_404(booking_id, t)
    v = flow._booking_view(b)
    what, when = html_escape(v["schedule_name"] or ""), html_escape(v["label_visitor"])
    if b.get("status") == "cancelled":
        return _manage_page("This booking is cancelled", f"<p>{what} on {when} was cancelled.</p>"
                            f"<p><a style='color:#F28C28' href='{settings.site_base_url}'>Book a new time in the chat</a></p>")
    join = email_html.safe_url(v.get("join_url"))
    tq = quote_param(t)
    return _manage_page("Your booking", f"<p><b>{what}</b><br>{when}<br>{html_escape(str(v['duration_min']))} min with Deep</p>"
                        + (f"<p><a style='color:#F28C28' href='{html_escape(join)}'>Join Zoom</a></p>" if join else "")
                        + f"<p><a style='color:#F28C28' href='/booking/{booking_id}/ics?t={tq}'>Add to calendar (.ics)</a></p>"
                        f"<p style='margin-top:24px'>Need a different time? Open the chat on "
                        f"<a style='color:#F28C28' href='{settings.site_base_url}'>{settings.site_base_url.replace('https://', '')}</a> and say "
                        f"\"reschedule my call\". Or cancel below, then pick a new one in the chat on "
                        f"<a style='color:#F28C28' href='{settings.site_base_url}'>{settings.site_base_url.replace('https://', '')}</a>.</p>"
                        f"<p><a href='/booking/{booking_id}/cancel?t={tq}' style='{_RED_PILL}'>Cancel this booking…</a></p>")


@app.post("/booking/{booking_id}/reschedule")
def booking_reschedule(booking_id: int, body: RescheduleIn, request: Request, t: str = "", x_session_id: str | None = Header(default=None),
                       x_visitor_id: str | None = Header(default=None)):
    """Move a booking to a new open time: from the chat (the booking belongs to this visitor's sessions) or with the
    manage token from the email. Browser-made bookings are moved on Zoom Scheduler by the browser worker."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    b = store_bookings.get(booking_id)
    sid = (x_session_id or "").strip()[:64] or None
    vid = (x_visitor_id or "").strip()[:64] or None
    owned = bool(b) and ((t and b.get("manage_token") == t) or store_bookings.owned_by_visitor(booking_id, vid, sid)
                         or email_ask.booker_owns(booking_id, vid, sid))
    if not b or not owned:
        raise HTTPException(404, "booking not found")
    if not _booking_limiter.allow(sid or _client_ip(request)):
        raise HTTPException(429, "Too many booking attempts. Please wait a minute and try again.")
    _ensure(request, sid, vid)  # only after the ownership check: an unowned request writes nothing
    try:
        res = flow.reschedule(_booking_service, b, body.start, body.timezone)
    except Exception as e:
        log.error("reschedule failed: %s", e)
        return {"status": "error", "message": "Zoom or the server did not respond. Your original time still stands.", "retry": True}
    if res.get("status") in ("rescheduled", "pending_zoom") and sid:
        v = res["booking"]
        line = (f"Booking moved: {v['schedule_name']} to {v['label_visitor']}." if res["status"] == "rescheduled"
                else f"New time held: {v['schedule_name']} on {v['label_visitor']}; the visitor still has to confirm on Zoom.")
        inbox.log_message(sid, "assistant", line, outcome="booking", question=f"[reschedule] {b.get('schedule_slug')} {v['start_iso']}")
    return res


@app.delete("/booking/{booking_id}")
def booking_cancel_from_chat(booking_id: int, request: Request, t: str = "", x_session_id: str | None = Header(default=None),
                             x_visitor_id: str | None = Header(default=None)):
    """Cancel from the chat: the booking belongs to this visitor's sessions (or the manage token is given). Browser-made
    bookings are cancelled on Zoom Scheduler by the worker; Meetings-API ones through the API; hand-off holds just end."""
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    b = store_bookings.get(booking_id)
    sid = (x_session_id or "").strip()[:64] or None
    vid = (x_visitor_id or "").strip()[:64] or None
    owned = bool(b) and ((t and b.get("manage_token") == t) or store_bookings.owned_by_visitor(booking_id, vid, sid)
                         or email_ask.booker_owns(booking_id, vid, sid))
    if not b or not owned:
        raise HTTPException(404, "booking not found")
    if b.get("status") == "cancelled":
        return {"status": "cancelled", "already": True, "booking": flow._booking_view(b)}
    if not _booking_limiter.allow(sid or _client_ip(request)):
        raise HTTPException(429, "Too many attempts. Please wait a minute and try again.")
    _ensure(request, sid, vid)  # only after the ownership check: an unowned request writes nothing
    try:
        r = flow.cancel(b, _booking_service)
    except Exception as e:
        log.error("cancel from chat failed: %s", e)
        return {"status": "error", "message": "Zoom or the server did not respond. Your booking still stands.", "retry": True}
    v = flow._booking_view(b)
    if sid:
        inbox.log_message(sid, "assistant", f"Booking cancelled: {b.get('schedule_name')} on {v['label_visitor']}.", outcome="booking",
                          question=f"[cancel] {b.get('schedule_slug')} {v['start_iso']}")
    return {"status": "cancelled" if r.get("ok") else "error", "booking": dict(v, status="cancelled"), "zoom_note": r.get("zoom_note") or "",
            "message": f"Cancelled: {b.get('schedule_name')} on {v['label_visitor']}.", "emails_queued": True}


@app.get("/booking/{booking_id}/cancel")
def booking_cancel_confirm(booking_id: int, t: str = ""):
    """Are you sure? Opening a link changes nothing (mail scanners, mis-taps, old host emails): only the button POSTs."""
    b = _booking_or_404(booking_id, t)
    v = flow._booking_view(b)
    what, when = html_escape(v["schedule_name"] or ""), html_escape(v["label_visitor"])
    if b.get("status") == "cancelled":
        return _manage_page("This booking is cancelled", f"<p>{what} on {when} was cancelled.</p>"
                            f"<p><a style='color:#F28C28' href='{settings.site_base_url}'>Book a new time in the chat</a></p>")
    tq = quote_param(t)
    return _manage_page("Cancel this booking?", f"<p>{what}<br>{when}</p>"
                        f"<form method='post' action='/booking/{booking_id}/cancel?t={tq}'><button type='submit' style='{_RED_PILL}'>Yes, cancel it</button></form>"
                        f"<p style='margin-top:18px'><a style='color:#F28C28' href='/booking/{booking_id}/manage?t={tq}'>Keep it</a></p>")


@app.post("/booking/{booking_id}/cancel")
def booking_cancel(booking_id: int, t: str = ""):
    b = _booking_or_404(booking_id, t)
    r = flow.cancel(b, _booking_service)
    if r.get("already"):  # no second system row in the conversation
        return _manage_page("This booking was already cancelled",
                            f"<p><a style='color:#F28C28' href='{settings.site_base_url}'>Pick a new time in the chat</a></p>")
    if b.get("session_id"):
        inbox.log_message(b["session_id"], "assistant", f"Booking cancelled: {b.get('schedule_name')} on {flow._booking_view(b)['label_visitor']}.",
                          outcome="booking")
    return _manage_page("Booking cancelled", "<p>Done. Both you and Deep get an email.</p>"
                        + (f"<p style='color:#8A8D93'>{html_escape(r.get('zoom_note'))}</p>" if r.get("zoom_note") else "")
                        + f"<p><a style='color:#F28C28' href='{settings.site_base_url}'>Pick a new time in the chat</a></p>")


@app.get("/healthz")
def healthz():
    report = health.last()
    return {"ok": True, "version": APP_VERSION, "spend_today_usd": round(spend_today(), 4), "origins": settings.origins,
            "status": report.get("level", "unknown"), "checked_at": report.get("at")}


@app.get("/admin/health")
def admin_health(run: bool = False, x_admin_token: str | None = Header(default=None)):
    """The latest health report (app/health.py); run=true checks everything now (without sending alerts)."""
    _require_admin(x_admin_token)
    return health.run_checks() if run or not health.last() else health.last()


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
    out = inbox.metrics(days)
    try:
        out["email_ask"] = email_ask.metrics(days)
    except Exception as e:  # reporting only
        log.warning("email ask metrics failed: %s", e)
    return out


@app.get("/admin/conversations")
def admin_conversations(days: int = 7, limit: int = 100, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"days": days, "items": inbox.conversations(days, limit)}


@app.get("/admin/conversations/{session_id}")
def admin_transcript(session_id: str, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return inbox.transcript(session_id)


class TeamReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    author: str | None = Field(default=None, max_length=80)


@app.post("/admin/conversations/{session_id}/reply")
def admin_team_reply(session_id: str, body: TeamReplyIn, x_admin_token: str | None = Header(default=None)):
    """The team answers inside the visitor's chat (app/team.py); emailed to them if unread after a few minutes."""
    _require_admin(x_admin_token)
    out = team.reply(session_id, body.text, body.author)
    if out is None:
        raise HTTPException(404, "no such conversation")
    return out


class TeamStatusIn(BaseModel):
    status: str | None = None   # waiting | replied | closed | null (assistant only)


@app.post("/admin/conversations/{session_id}/status")
def admin_team_status(session_id: str, body: TeamStatusIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    if not team.set_status(session_id, body.status):
        raise HTTPException(400, "unknown status or conversation")
    return {"ok": True, "team_status": body.status}


def _memory_profile(session_id: str) -> dict:
    """The profile the chat would build for this session: its visitor and user id, or the session alone (form-only)."""
    from app.db import conn

    with conn() as c:
        r = c.execute("SELECT visitor_id, user_id FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
    return memory.profile(r[0] if r else None, r[1] if r else None, session_id)


@app.get("/admin/memory/{session_id}")
def admin_memory(session_id: str, x_admin_token: str | None = Header(default=None)):
    """The working memory of one conversation and exactly what the model sees (system section + DATA message)."""
    _require_admin(x_admin_token)
    row = session_memory.row(session_id) or {}
    p = _memory_profile(session_id)
    return {"session_id": session_id, "facts": row.get("facts") or {}, "gist": row.get("gist") or "", "extractor": row.get("extractor"),
            "rules_msg_id": row.get("rules_msg_id", 0), "model_msg_id": row.get("model_msg_id", 0), "model_fail": row.get("model_fail", 0),
            "forgotten_at": row.get("forgotten_at"), "updated_at": row.get("updated_at"), "form": p.get("form"),
            "rendered": {"system": memory.prompt_block(p), "data": memory.data_block(p, session_memory.get(session_id), window_full=True)}}


@app.delete("/admin/memory/{session_id}")
def admin_memory_forget(session_id: str, visitor: bool = False, x_admin_token: str | None = Header(default=None)):
    """Clear memory: a tombstone (facts and gist emptied, never re-learned). Transcripts, bookings and leads stay.
    ?visitor=1 clears every session of that device."""
    _require_admin(x_admin_token)
    if visitor:
        from app.db import conn

        with conn() as c:
            r = c.execute("SELECT visitor_id FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
        forgotten = session_memory.forget_visitor(session_id)
        if r and r[0]:
            visitors.erase(r[0])  # the device's page-view row and its pop-up context go too
        return {"forgotten": forgotten}
    session_memory.forget(session_id)
    return {"forgotten": [session_id]}


@app.post("/admin/memory/{session_id}/rebuild")
def admin_memory_rebuild(session_id: str, unforget: bool = False, more: bool = False, x_admin_token: str | None = Header(default=None)):
    """Re-extract from the transcript (at most 2 model batches per call). The console repeats with ?more=1 (no reset)
    while 'remaining' is true. A cleared conversation stays cleared unless ?unforget=1."""
    _require_admin(x_admin_token)
    if not more:
        session_memory.reset(session_id, unforget)
    return session_memory.update(session_id, "rebuild")


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
def admin_digest_preview(days: int = 7, rich: int = 0, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return digest.build(days, rich=bool(rich))   # rich=1: also compose the HTML part (model + Node) for the console preview


@app.post("/admin/digest/send")
def admin_digest_send(days: int = 7, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return digest.send(days)


@app.post("/admin/reminders/run")
def admin_reminders_run(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return reminders.run()


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
    items = store_bookings.recent(days)
    try:
        briefs = precall.stored([b["id"] for b in items])
    except Exception:
        briefs = {}
    for b in items:  # the lead score on every row; the full brief is one click away
        br = briefs.get(b["id"])
        b["lead"] = {"score": br.get("score"), "label": br.get("label"), "verdict": br.get("verdict")} if br else None
    return {"items": items, "mail": mailer.default.stats()}


# ---- pre-call brief (app/precall.py)
def _admin_booking_or_404(booking_id: int) -> dict:
    b = store_bookings.get(booking_id)
    if not b:
        raise HTTPException(404, "booking not found")
    return b


@app.get("/admin/bookings/{booking_id}/brief")
def admin_booking_brief(booking_id: int, refresh: bool = False, x_admin_token: str | None = Header(default=None)):
    """The stored brief (built on first open); refresh=1 rebuilds it from everything known now (one model call)."""
    _require_admin(x_admin_token)
    b = _admin_booking_or_404(booking_id)
    brief = precall.build_for_booking(b, refresh=refresh)
    return {"brief": brief, "text": precall.text(brief), "session_id": b.get("session_id"), "host_url": host_page.link(b),
            "booking": {k: b.get(k) for k in ("id", "name", "email", "status", "start_utc", "end_utc", "schedule_name", "outcome", "outcome_note",
                                              "outcome_at", "followup")}}


@app.post("/admin/bookings/{booking_id}/brief/email")
def admin_booking_brief_email(booking_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return precall.send_brief_now(_admin_booking_or_404(booking_id))


@app.get("/admin/leads/scored")
def admin_scored_leads(days: int = 7, x_admin_token: str | None = Header(default=None)):
    """Everyone who left an email and has no call booked, scored (rules only, no model call)."""
    _require_admin(x_admin_token)
    return {"items": precall.scored_leads(hours=24 * max(1, min(days, 90))), "threshold": settings.hot_lead_score}


@app.post("/admin/leads/alerts/run")
def admin_hot_lead_alerts_run(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return precall.run_alerts()


# ---- call outcomes, follow-up drafts and the learning lead score (app/outcomes.py)
class OutcomeIn(BaseModel):
    outcome: str = Field(pattern=r"^(good_fit|follow_up|not_fit|no_show)$")
    note: str | None = Field(default=None, max_length=2000)


class FollowupIn(BaseModel):
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=20, max_length=6000)


@app.post("/admin/bookings/{booking_id}/outcome")
def admin_booking_outcome(booking_id: int, body: OutcomeIn, x_admin_token: str | None = Header(default=None)):
    """Record how the call went; Good fit / Follow up / No-show also draft the follow-up email (one model call)."""
    _require_admin(x_admin_token)
    b = outcomes.record(booking_id, body.outcome, body.note, by="console")
    if not b:
        raise HTTPException(404, "booking not found")
    fu = b.get("followup") or {}
    draft = fu if fu.get("sent_at") else outcomes.draft_followup(b)
    return {"outcome": b["outcome"], "followup": draft}


@app.post("/admin/bookings/{booking_id}/followup/draft")
def admin_followup_draft(booking_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    b = _admin_booking_or_404(booking_id)
    if (b.get("followup") or {}).get("sent_at"):
        raise HTTPException(409, "the follow-up was already sent")
    d = outcomes.draft_followup(b)
    if not d:
        raise HTTPException(400, "rate the call Good fit, Follow up or No-show first")
    return {"followup": d}


@app.post("/admin/bookings/{booking_id}/followup/send")
def admin_followup_send(booking_id: int, body: FollowupIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return outcomes.send_followup(_admin_booking_or_404(booking_id), body.subject, body.body)


@app.get("/admin/score/learning")
def admin_score_learning(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return outcomes.learned()


@app.post("/admin/score/learn")
def admin_score_learn(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return outcomes.learn()


@app.post("/admin/outcomes/ask/run")
def admin_outcome_asks_run(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return outcomes.send_asks()


def _outcome_booking(booking_id: int, t: str) -> dict:
    b = store_bookings.get(booking_id) if links.check("outcome", booking_id, t) else None
    if not b:
        raise HTTPException(404, "link not valid")
    return b


@app.get("/outcome/{booking_id}", response_class=HTMLResponse)
def outcome_page(booking_id: int, t: str = "", o: str = ""):
    """The page behind the buttons in "How did the call go?": the choice is preselected, saving takes one press."""
    return HTMLResponse(outcomes.page_ask(_outcome_booking(booking_id, t), t, o))


@app.post("/outcome/{booking_id}", response_class=HTMLResponse)
def outcome_save(booking_id: int, t: str = "", o: str = Form(...), note: str = Form(default="")):
    _outcome_booking(booking_id, t)
    if o not in outcomes.OUTCOMES:
        raise HTTPException(400, "unknown outcome")
    b = outcomes.record(booking_id, o, note, by="email")
    fu = b.get("followup") or {}
    draft = fu if fu.get("sent_at") else outcomes.draft_followup(b)
    return HTMLResponse(outcomes.page_saved(b, t, draft))


@app.post("/outcome/{booking_id}/send", response_class=HTMLResponse)
def outcome_send(booking_id: int, t: str = "", subject: str = Form(...), body: str = Form(...)):
    b = _outcome_booking(booking_id, t)
    return HTMLResponse(outcomes.page_sent(b, outcomes.send_followup(b, subject, body)))


# ---- the host's private booking page (app/host_page.py): plain def, so its reads run in the threadpool
_HOST_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"


@app.get("/host/booking/sample", response_class=HTMLResponse)
def host_booking_sample():
    """The sample page (the [test] host email's button). Declared before the int route, where 'sample' would be a 422."""
    return HTMLResponse(host_page.render(host_page.sample()), headers=_PRIVATE | {"Content-Security-Policy": _HOST_CSP})


@app.get("/host/booking/{booking_id}", response_class=HTMLResponse)
def host_booking_page(booking_id: int, request: Request, t: str = ""):
    """Everything Deep needs before and after the call. Strictly read-only: mail scanners open every link."""
    if not _track_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "too many requests")
    b = store_bookings.get(booking_id)
    if not b or not host_page.check(b, t):
        raise HTTPException(404, "link not valid")
    log.info("host page opened: booking %s", booking_id)
    return HTMLResponse(host_page.render(host_page.load(b)), headers=_PRIVATE | {"Content-Security-Policy": _HOST_CSP})


# ---- knowledge-gap loop (app/gaps.py)
class GapApproveIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=10, max_length=3000)
    link: str | None = Field(default=None, max_length=500)
    email_askers: bool = True


@app.get("/admin/gaps/drafts")
def admin_gap_drafts(status: str = "draft", days: int = 7, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    if status not in ("draft", "approved", "dismissed"):
        raise HTTPException(400, "status must be draft, approved or dismissed")
    return {"items": gaps.list_drafts(status), "stats": gaps.stats(max(1, min(days, 90))), "since": gaps.since(),
            "followup": settings.gap_followup, "links": links.enabled()}


@app.post("/admin/gaps/run")
def admin_gap_run(x_admin_token: str | None = Header(default=None)):
    """Draft answers now instead of waiting for the night (one model call per new question group)."""
    _require_admin(x_admin_token)
    return gaps.run()


@app.post("/admin/gaps/drafts/{draft_id}/approve")
def admin_gap_approve(draft_id: int, body: GapApproveIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    try:
        return gaps.approve(draft_id, body.question, body.answer, body.link, body.email_askers)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/admin/gaps/drafts/{draft_id}/dismiss")
def admin_gap_dismiss(draft_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": gaps.set_status(draft_id, "dismissed")}


@app.post("/admin/gaps/drafts/{draft_id}/restore")
def admin_gap_restore(draft_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"ok": gaps.set_status(draft_id, "draft")}


@app.post("/admin/gaps/drafts/{draft_id}/redraft")
def admin_gap_redraft(draft_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    try:
        return gaps.redraft(draft_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/admin/gaps/drafts/{draft_id}/askers")
def admin_gap_askers(draft_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"items": gaps.askers(draft_id)}


@app.post("/admin/gaps/followups/send")
def admin_gap_followups_send(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return gaps.send_due()


@app.get("/email/optout", response_class=HTMLResponse)
def email_optout_page(e: str = "", t: str = ""):
    if not links.check("optout", e, t):
        raise HTTPException(404, "link not valid")
    return HTMLResponse(outcomes._page("No more emails like this?",
                        f"<p class='muted'>We'll stop sending answers and follow-ups to <b>{html_escape(e)}</b>. Booking emails you ask for still arrive.</p>"
                        f"<form method='post' action='/email/optout?e={quote_param(e)}&t={html_escape(t)}'><button type='submit'>Yes, stop these emails</button></form>"))


@app.post("/email/optout", response_class=HTMLResponse)
def email_optout(e: str = "", t: str = ""):
    if not links.check("optout", e, t):
        raise HTTPException(404, "link not valid")
    gaps.opt_out(e)
    return HTMLResponse(outcomes._page("Done", "<p class='ok'>You won't get emails like this again.</p>"))


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
            "recent": st["recent"], "days": st["days"], "channels": list(outreach.CHANNELS), "max_rules": outreach.MAX_RULES,
            "ip_context": outreach.ip_context_enabled(), "ip_context_env": settings.outreach_ip_context and settings.tracking_enabled,
            "visitors": visitors.summary(st["days"]), "variants": st["by_variant"], "candidates": visitors.candidates(),
            "provider_note": visitors.provider_note()}


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
    if body.default_greeting is not None:
        outreach.set_default_greeting(body.default_greeting)
    if body.ip_context is not None:
        outreach.set_ip_context(body.ip_context)
    return {"default_greeting": outreach.default_greeting_enabled(), "ip_context": outreach.ip_context_enabled()}


@app.get("/admin/outreach/orgs")
def admin_outreach_orgs(status: str = "", days: int = 30, x_admin_token: str | None = Header(default=None)):
    """Organisations visiting: devices, visits, pages and pop-up counts per organisation network (host-only)."""
    _require_admin(x_admin_token)
    return visitors.list_orgs(status, days)


@app.patch("/admin/outreach/orgs/{key:path}")
def admin_outreach_org_patch(key: str, body: OrgPatchIn, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    try:
        r = visitors.update_org(key, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not r:
        raise HTTPException(404, "no such organisation")
    return r


@app.delete("/admin/visitors/{visitor_id}")
def admin_visitor_erase(visitor_id: str, x_admin_token: str | None = Header(default=None)):
    """Forget a device's page-view row and the visitor id and context on its pop-up firings."""
    _require_admin(x_admin_token)
    return visitors.erase(visitor_id)


@app.post("/admin/outreach/try")
def admin_outreach_try(body: OutreachTryIn, x_admin_token: str | None = Header(default=None)):
    """Dry run: which rule would fire for this activity. Cooldowns and earlier firings are ignored; nothing is recorded."""
    _require_admin(x_admin_token)
    facts = {"returning": body.visits > 1, "visits": body.visits, "name": body.first_name,
             "upcoming": {"schedule_name": "Discovery Call", "label_visitor": "Thu 15 Oct, 16:30"} if body.booking else None}
    payload = {"path": body.path, "page": body.path, "pages": body.pages, "dwell_s": body.dwell_s, "scroll_pct": body.scroll_pct,
               "referrer": body.referrer, "first_page": body.path, "visits": body.visits}
    ctx = outreach.context(payload, facts, _try_visitor(body))
    rules = [r for r in outreach.list_rules() if r["enabled"]]
    rows = [{"id": r["id"], "name": r["name"], **outreach.evaluate(r["trigger"], ctx)} for r in rules]
    hit = next((r for r, row in zip(rules, rows) if row["match"]), None)
    msg = outreach.public_message(hit, ctx) if hit else None
    variant = msg["_variant"] if msg else None
    return {"context": {k: ctx[k] for k in ("path", "pages", "dwell_s", "scroll_pct", "referrer_host", "channel", "returning", "booking",
                                            "engaged", "company", "country")},
            "fires": outreach.pop_private(msg), "variant": variant, "rules": rows, "default": outreach.default_greeting_enabled()}


def _try_visitor(body: OutreachTryIn) -> dict:
    """A stand-in for visitors.observe() from the try-it form. The visit number stands in for the visits seen on the
    organisation's network; an approved organisation is named from the first."""
    from app import network

    kind = (body.net_kind or ("corporate" if body.org else "")).strip().lower()
    company = None
    org = network.clean_org(body.org or "")
    if org:
        ident = ("org:" + network.org_key(org), org, None)
        row = {"org": org, "net_kind": kind, "status": "approved" if body.approved else "auto", "industry": "", "line": None}
        company = visitors.company_context(ident, row, visitors.COMPANY_MIN_VISITS if body.approved else body.visits,
                                           body.country_code)
    country = (body.country or "").strip()
    phrase = ("the " + country if country in visitors.THE_COUNTRIES else country) if visitors.ip_context_on() else ""
    return {"visits": body.visits, "returning": body.visits > 1, "engaged": body.engaged or "never", "net_kind": kind,
            "country_code": (body.country_code or "").upper() if phrase else "", "country": phrase, "company": company}


@app.get("/admin/email-templates")
def admin_templates_get(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    return {"templates": templates.get_templates(), "defaults": templates.DEFAULTS, "variables": templates.VARIABLES,
            "previews": templates.previews(), "host_email": settings.host_email, "smtp_configured": bool(settings.smtp_host),
            "public_base_url": links.base_url(), "public_base_url_problem": links.public_problem(), "public_base_url_http": links.plain_http()}


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
