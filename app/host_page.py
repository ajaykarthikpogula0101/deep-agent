"""The host's private booking page: /host/booking/{id}?t=<signed token>, the page behind "View booking details" in
every host email about a booking (new booking, moved, cancelled, the day-before brief, "how did it go?").

* The signed link is bound to one booking row: the signature covers the kind 'host_booking', the booking id and that
  row's manage_token, so a rebuilt database that reuses the id does not open, and rotating the row's manage_token
  revokes the link (LINK_SECRET revokes all of them). The manage token itself is never shown or sent.
* GET is read-only, which matters because mail scanners open every link: no brief is built, no memory updated, no origin
  stored, no event logged. Outcome buttons go to the existing /outcome page, where saving needs a press.
* The page never shows an IP, user agent, lat/lon, the visitor's manage token or URLs, the handoff, zoom_reschedule or
  zoom_cancel URLs, or upload URLs.
* Free text (chat, notes, the typed company, the model-written brief) is escaped and never linked: model text comes
  from visitor text and could carry phishing URLs. Hrefs come only from safe_url() http(s) values, company_link(), the
  validated mailto, the console and the signed outcome links.

load(b) reads (one pooled connection, a savepoint per read); assemble(...) and render(d) are pure, so the real page and
/host/booking/sample share one path. precall, tracking and outcomes are imported inside functions: no import cycles.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app import links
from app.booking.email_html import _email_ok, company_link, esc, safe_url
from app.config import settings

log = logging.getLogger("host_page")

KIND = "host_booking"
TRANSCRIPT_MAX = 200
LONG_MSG = 600
EARLIER_MAX = 10
SAMPLE_PATH = "/host/booking/sample"


# ---------------------------------------------------------------- the signed link
def _value(b: dict[str, Any]) -> str:
    if not b.get("id") or not b.get("manage_token"):
        return ""
    return f"{int(b['id'])}:{b['manage_token']}"


def link(b: dict[str, Any]) -> str:
    """The host's page for this booking, '' without a manage token or a signing key."""
    if not _value(b) or not links.enabled():
        return ""
    return f"{links.base_url()}/host/booking/{int(b['id'])}?t={links.sign(KIND, _value(b))}"


def check(b: dict[str, Any], token: str | None) -> bool:
    return bool(_value(b)) and links.check(KIND, _value(b), token)


def sample_link() -> str:
    return links.base_url() + SAMPLE_PATH


def attach(b: dict[str, Any]) -> dict[str, Any]:
    """A copy of the booking with host_url set (for the host emails); the booking itself when there is no link."""
    u = link(b)
    return dict(b, host_url=u) if u else b


# ---------------------------------------------------------------- reads
def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception as e:
        log.warning("host page read failed: %s", e)
        return default


def _optional(c: Any, fn: Callable[..., Any], *args: Any) -> Any:
    try:
        with c.transaction():
            return fn(c, *args)
    except Exception as e:
        log.warning("host page %s failed: %s", fn.__name__, e)
        return None


def _read_transcript(c: Any, sid: str) -> tuple[list[dict[str, Any]], int]:
    rows = c.execute("SELECT ts, role, text, outcome FROM messages WHERE session_id = %s ORDER BY id LIMIT %s",
                     (sid, TRANSCRIPT_MAX + 1)).fetchall()
    total = len(rows)
    if total > TRANSCRIPT_MAX:
        total = int(c.execute("SELECT count(*) FROM messages WHERE session_id = %s", (sid,)).fetchone()[0])
    return [dict(zip(("ts", "role", "text", "outcome"), r)) for r in rows[:TRANSCRIPT_MAX]], total


def _read_visitor(c: Any, sid: str) -> str | None:
    r = c.execute("SELECT visitor_id FROM sessions WHERE session_id = %s", (sid,)).fetchone()
    return r[0] if r else None


EARLIER_COLS = ("session_id", "first_seen", "messages", "page", "channel", "referrer_host", "city", "country_code", "net_org",
                "isp", "net_kind", "net_flags", "via", "first_q")


def _read_earlier(c: Any, sid: str | None, vid: str | None, email: str) -> list[dict[str, Any]]:
    """Other visits of the same browser, or linked by the same (unverified) email. Never selects ip, user_agent, lat, lon."""
    rows = c.execute(
        """SELECT s.session_id, s.first_seen, s.messages, s.page, s.channel, s.referrer_host, s.city, s.country_code, s.net_org,
                  s.isp, s.net_kind, s.net_flags,
                  CASE WHEN %(vid)s::text IS NOT NULL AND s.visitor_id = %(vid)s THEN 'browser' ELSE 'email' END AS via,
                  (SELECT m.text FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user' ORDER BY m.id LIMIT 1) AS first_q
           FROM sessions s
           WHERE s.session_id IS DISTINCT FROM %(sid)s::text AND (
             (%(vid)s::text IS NOT NULL AND s.visitor_id = %(vid)s)
             OR s.session_id IN (SELECT session_id FROM bookings WHERE lower(email) = %(e)s AND session_id IS NOT NULL
                                 UNION SELECT session_id FROM leads WHERE lower(email) = %(e)s AND session_id IS NOT NULL)
             OR lower(s.user_email) = %(e)s)
             AND (s.messages > 0 OR EXISTS (SELECT 1 FROM bookings x WHERE x.session_id = s.session_id))
           ORDER BY s.first_seen DESC LIMIT %(n)s""", {"sid": sid, "vid": vid, "e": email, "n": EARLIER_MAX}).fetchall()
    return [dict(zip(EARLIER_COLS, r)) for r in rows]


def _read_earlier_bookings(c: Any, email: str, bid: int) -> list[dict[str, Any]]:
    rows = c.execute("""SELECT id, start_utc, schedule_name, status, outcome FROM bookings
                        WHERE lower(email) = lower(%s) AND id <> %s ORDER BY start_utc DESC LIMIT 10""", (email, bid)).fetchall()
    return [dict(zip(("id", "start_utc", "schedule_name", "status", "outcome"), r)) for r in rows]


def load(b: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Everything the page shows, read only (never raises; a failed read leaves its part empty)."""
    from app import precall, templates, tracking
    from app.db import conn

    bid, sid = int(b["id"]), b.get("session_id")
    email = (b.get("email") or "").strip().lower()
    sig = _safe(lambda: precall.gather(email, sid, b), {})
    brief = _safe(lambda: precall.stored([bid]).get(bid), None)
    live = False
    if not brief:  # nothing stored: the rules score as of now, no model call and nothing written
        brief, live = _safe(lambda: precall.score(sig), None), True
    origin = ""
    if settings.tracking_enabled:
        origin = _safe(lambda: tracking.describe_session(sid), "") or b.get("origin") or ""
    transcript, total, earlier, earlier_bookings = [], 0, [], []
    try:
        with conn() as c:
            if sid:
                transcript, total = _optional(c, _read_transcript, sid) or ([], 0)
            vid = _optional(c, _read_visitor, sid) if sid else None
            if vid or email:
                earlier = _optional(c, _read_earlier, sid, vid, email) or []
            if email:
                earlier_bookings = _optional(c, _read_earlier_bookings, email, bid) or []
    except Exception as e:
        log.warning("host page reads failed for booking %s: %s", bid, e)
    host_name = templates.get_templates().get("host_name") or "Deep"
    return assemble(b, sig=sig, brief=brief, brief_live=live, origin=origin, transcript=transcript, total=total,
                    earlier=earlier, earlier_bookings=earlier_bookings, now=now, host_name=host_name)


# ---------------------------------------------------------------- pure: what the page shows
def host_text(t: str | None) -> str:
    """Visitor text as the host should read it (as precall._visitor_text): attachments named without their URL, GIFs
    dropped. Newlines kept, clipped to 2000 characters."""
    s = re.sub(r"\[attached: ([^\]]+)\]\(\S+\)", r"[file: \1]", t or "").replace("[GIF]", "").strip()
    return s if len(s) <= 2000 else s[:1999].rstrip() + "…"


def _one_line(t: str, n: int) -> str:
    s = re.sub(r"\s+", " ", t or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _local(dt: Any, fmt: str) -> str:
    if not isinstance(dt, datetime):
        return ""
    try:
        tz = ZoneInfo(settings.host_timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    return dt.astimezone(tz).strftime(fmt)


def _iso(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def relative(start: datetime | None, end: datetime | None, now: datetime) -> str:
    """'in 2 days', 'starts in 40 min', 'in progress', 'ended 3 h ago'."""
    if not start:
        return ""
    end = end or start

    def span(d: timedelta) -> str:
        m = int(d.total_seconds() // 60)
        if m < 60:
            return f"{max(m, 1)} min"
        if m < 48 * 60:
            return f"{m // 60} h"
        return f"{m // 1440} days"

    if end <= now:
        return f"ended {span(now - end)} ago"
    if start <= now:
        return "in progress"
    d = start - now
    return f"starts in {span(d)}" if d < timedelta(hours=48) else f"in {span(d)}"


def _network_line(net: dict[str, Any]) -> str:
    """Where the visit came from, network-wise. Never under 'Company': a residential ISP is not their company."""
    if not net:
        return ""
    from app import network

    if net.get("kind") == "local":
        return "local test network (no lookup)"
    parts = (network.clean_org(net.get("org") or ""), network.label(net.get("kind"), net.get("mobile")), net.get("match_text") or "")
    return " · ".join(x for x in parts if x) + (" [dev test IP]" if net.get("dev") else "")


def _earlier_row(r: dict[str, Any]) -> dict[str, Any]:
    from app import network, precall

    flags = r.get("net_flags") if isinstance(r.get("net_flags"), dict) else {}
    org = network.clean_org(r.get("net_org") or r.get("isp") or "")
    net = network.label(r["net_kind"], flags.get("mobile")) + (f" ({org})" if org else "") if r.get("net_kind") else ""
    return {"date": _local(r.get("first_seen"), "%d %b %Y"), "first_q": _one_line(host_text(r.get("first_q")), 120),
            "path": precall._path(r.get("page")), "messages": int(r.get("messages") or 0),
            "channel": r.get("referrer_host") or r.get("channel") or "", "network": net,
            "via": "same browser" if r.get("via") == "browser" else "same email (unverified)"}


def _brief_view(brief: dict[str, Any] | None, live: bool, sig: dict[str, Any]) -> dict[str, Any] | None:
    from app import precall

    if not brief:
        return None
    ab = brief.get("at_booking") or {}
    return {"score": brief.get("score", 0), "label": brief.get("label") or "cold", "live": live,
            "headline": precall.headline(brief), "verdict": brief.get("verdict") or "",
            "evidence": precall.evidence_line(brief.get("evidence")),
            "old": not live and int(brief.get("version") or 1) < precall.VERSION, "groups": brief.get("groups") or {},
            "at_booking": ab.get("score") if ab.get("score") is not None and ab.get("score") != brief.get("score") else None,
            "summary": brief.get("summary") or "", "reasons": brief.get("reasons") or [],
            "asked": brief.get("asked") if brief.get("asked") is not None else (sig.get("questions") or [])[-6:],
            "talking_points": brief.get("talking_points") or [], "questions_to_ask": brief.get("questions_to_ask") or [],
            "watch": brief.get("watch_outs") or [f.get("text") for f in brief.get("flags") or [] if f.get("text")],
            "composer": brief.get("composer") or "", "built_at": _local(_iso(brief.get("built_at")), "%a %d %b, %H:%M")}


def _outcome(b: dict[str, Any], status: str, now: datetime) -> dict[str, Any] | None:
    """Rating buttons once the call has ended, as outcomes.due() asks: confirmed or pending_zoom, never cancelled."""
    from app import outcomes

    end = b.get("end_utc")
    if status not in ("confirmed", "pending_zoom") or not isinstance(end, datetime) or end > now:
        return None
    bid = int(b["id"])
    return {"links": [(label, outcomes.link(bid, key)) for key, label in outcomes.OUTCOMES.items()],
            "current": b.get("outcome") or "", "note": b.get("outcome_note") or "",
            "followup_sent": (b.get("followup") or {}).get("sent_at") if isinstance(b.get("followup"), dict) else None,
            "change_url": outcomes.link(bid)}


def assemble(b: dict[str, Any], *, sig: dict[str, Any], brief: dict[str, Any] | None, brief_live: bool, origin: str,
             transcript: list[dict[str, Any]], total: int, earlier: list[dict[str, Any]], earlier_bookings: list[dict[str, Any]],
             now: datetime | None = None, host_name: str = "Deep") -> dict[str, Any]:
    """Pure: the booking and what load() read -> everything render() shows."""
    from app import precall
    from app.booking.flow import _booking_view
    from app.booking.zoom import Slot

    now = now or datetime.now(timezone.utc)
    v = _booking_view(b)
    status = b.get("status") or ""
    bid = int(b["id"])
    moved = bool(b.get("rescheduled_at") and b.get("previous_start_utc"))
    email = (b.get("email") or "").strip()
    name = (b.get("name") or "").strip()
    guests = []
    for g in b.get("attendees") or []:
        if isinstance(g, dict) and (g.get("email") or g.get("name")):
            ge = (g.get("email") or "").strip()
            guests.append({"name": (g.get("name") or "").strip(), "email": ge, "mailto": f"mailto:{ge}" if _email_ok(ge) else ""})
    mailto = ""
    if _email_ok(email):
        mailto = ("mailto:" + urllib.parse.quote(email, safe="@.+-_~") + "?subject="
                  + urllib.parse.quote("Re: " + (b.get("schedule_name") or "our call")))
    rows = []
    for m in transcript:
        rows.append({"role": m.get("role"), "text": host_text(m.get("text")), "outcome": m.get("outcome") or "",
                     "time": _local(m.get("ts"), "%H:%M")})
    return {
        "id": bid, "name": name, "first": name.split(" ")[0] if name else "them", "email": email,
        "email_kind": {"business": "company email", "personal": "personal email"}.get(sig.get("email_kind") or "", ""),
        "schedule_name": b.get("schedule_name") or "", "duration": b.get("duration_min") or "", "method": b.get("method") or "",
        "status": status, "moved": moved,
        "was_label": Slot(b["previous_start_utc"], b.get("duration_min") or 0).label(settings.host_timezone) if moved else "",
        "cancelled_at": _local(b.get("cancelled_at"), "%d %b"),
        "label_host": v["label_host"], "label_visitor": v["label_visitor"],
        "relative": relative(b.get("start_utc"), b.get("end_utc"), now) if status != "cancelled" else "",
        "meeting_id": str(b.get("zoom_meeting_id") or b.get("meeting_id") or ""), "passcode": b.get("passcode") or "",
        "zoom_error": _one_line(str(b.get("zoom_error") or ""), 200),
        "company": precall.company_view(sig), "guests": guests, "notes": (b.get("notes") or "").strip(),
        "tracking": bool(settings.tracking_enabled), "origin": origin if settings.tracking_enabled else "",
        "network_line": _network_line(sig.get("network") or {}) if settings.tracking_enabled else "",
        "tz_note": precall._tz_note(sig), "pages": sig.get("pages") or [],
        "channel": sig.get("referrer_host") or sig.get("channel") or "", "visits": int(sig.get("visits") or 0),
        "first_seen": _local(sig.get("first_seen"), "%d %b %Y"),
        "brief": _brief_view(brief, brief_live, sig), "outcome": _outcome(b, status, now),
        "transcript": rows, "total": max(total, len(rows)), "truncated": total > len(rows),
        "earlier": [_earlier_row(r) for r in earlier[:EARLIER_MAX]],
        "earlier_bookings": [{"date": _local(x.get("start_utc"), "%d %b %Y"), "call": x.get("schedule_name") or "",
                              "status": x.get("status") or "", "outcome": x.get("outcome") or ""} for x in earlier_bookings],
        "urls": {"join": safe_url(b.get("join_url")) if status == "confirmed" else "",
                 "console": f"{links.base_url()}/admin#booking={bid}", "mailto": mailto},
        "host_name": host_name,
    }


# ---------------------------------------------------------------- the sample (/host/booking/sample, the [test] email)
def sample_inputs() -> dict[str, Any]:
    """assemble()'s arguments for the sample page: Ada Lovelace's call, ended, with a v3 brief. Touches no database."""
    from app import templates

    b = dict(templates.SAMPLE_BOOKING, session_id="sample", manage_token="", outcome=None, outcome_note=None, followup=None)
    first = datetime(2026, 10, 5, 9, 12, tzinfo=timezone.utc)
    sig = {"name": "Ada Lovelace", "email": "ada@lovelace.org", "domain": "lovelace.org", "email_kind": "business",
           "company_line": templates.SAMPLE_BOOKING["company_line"], "company_typed": "Lovelace Analytical Engines",
           "enrich_source": "homepage", "enrich_company": "Lovelace Analytical Engines", "company_verified": True, "domain_proof": "web",
           "network": {"kind": "corporate", "org": "Lovelace Analytical Engines", "mobile": False, "match": "email",
                       "match_text": "matches their email domain", "dev": False},
           "tz_mismatch": False, "pages": ["/pricing", "/data/fintech"], "channel": "social", "referrer_host": "linkedin.com",
           "visits": 2, "first_seen": first, "questions": ["Do you have EU fintech decision makers?", "Can we get sample data first?"]}
    reasons = [{"key": "business_email", "points": 15, "text": "company email (lovelace.org)", "group": "fit", "cls": "verified",
                "proof": "website"},
               {"key": "company_verified", "points": 0, "text": "the company they typed matches their email (Lovelace Analytical Engines)",
                "group": "fit", "cls": "verified"},
               {"key": "network_email", "points": 5, "text": "visited from their company's network, matching their email domain", "group": "fit",
                "cls": "verified"},
               {"key": "buying_topics", "points": 25, "text": "asked about pricing, a trial or sample data", "group": "intent", "cls": "observed"},
               {"key": "visits", "points": 8, "text": "came back for a second visit", "group": "engagement", "cls": "observed"},
               {"key": "questions", "points": 4, "text": "asked 2 questions", "group": "engagement", "cls": "observed"},
               {"key": "stated_facts", "points": 0, "text": "they say: role: head of data partnerships", "group": "fit", "cls": "claimed"}]
    brief = {"version": 3, "mode": "call", "score": 72, "label": "hot", "verdict": "hot", "composer": "model",
             "built_at": "2026-10-06T08:00:00+00:00", "evidence": {"verified": 20, "observed": 37, "claims": 1, "missing": []},
             "groups": {"fit": 20, "intent": 25, "engagement": 12, "risk": 0}, "reasons": reasons,
             "flags": [{"key": "open_booking", "text": "Already has another upcoming call booked with this email: check it is not a duplicate"},
                       {"key": "network_mismatch", "text": "Guest Charles Babbage uses a different company: ask who decides"}],
             "summary": "Ada runs data partnerships at Lovelace Analytical Engines and wants EU fintech decision makers, starting with a sample.",
             "talking_points": ["Show EU fintech coverage", "Offer a 500-contact sample", "Agree a next step before the call ends"],
             "questions_to_ask": ["Who else is involved in the decision?", "What volume do you need per quarter?"],
             "watch_outs": [], "asked": sig["questions"], "at_booking": {"version": 3, "score": 64, "label": "hot", "verdict": "hot"}}
    transcript = [
        {"ts": first, "role": "user", "text": "Do you have EU fintech decision makers?", "outcome": None},
        {"ts": first + timedelta(seconds=40), "role": "assistant", "text": "Yes: LakeB2B covers fintech across the EU, with "
         "decision makers by role, country and company size. Would a sample help?", "outcome": "answered"},
        {"ts": first + timedelta(minutes=2), "role": "user", "text": "[attached: brief.pdf](/uploads/x) Can we get sample data first?", "outcome": None},
    ]
    earlier = [{"session_id": "sample-0", "first_seen": first - timedelta(days=9), "messages": 3, "page": "https://deependhq.com/pricing",
                "channel": "search", "referrer_host": "google.com", "city": "London", "country_code": "GB",
                "net_org": "Lovelace Analytical Engines", "isp": "", "net_kind": "corporate", "net_flags": {}, "via": "browser",
                "first_q": "How do you price contact data?"}]
    return {"b": b, "sig": sig, "brief": brief, "brief_live": False, "origin": templates.SAMPLE_LEAD["origin"],
            "transcript": transcript, "total": 3, "earlier": earlier, "earlier_bookings": [],
            "now": b["end_utc"] + timedelta(hours=3), "host_name": templates.DEFAULTS["host_name"]}


def sample() -> dict[str, Any]:
    p = sample_inputs()
    d = assemble(p.pop("b"), **p)
    if d["outcome"]:  # a sample: the rating buttons go nowhere
        d["outcome"] = dict(d["outcome"], links=[(label, "#") for label, _ in d["outcome"]["links"]], change_url="#")
    return d


# ---------------------------------------------------------------- render
HOST_CSS = (
    ".card{max-width:680px}.sub{margin:0 0 10px;color:#68718A}"
    ".sec{margin:22px 0 0;padding-top:16px;border-top:1px solid #E9EBF2}"
    ".sec h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#F28C28;margin:0 0 10px}"
    ".pills{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 4px}"
    ".pill{display:inline-block;padding:4px 11px;border-radius:999px;font-size:13px;font-weight:700;background:#EEF0F6;color:#151B32}"
    ".pill.ok{background:#E8F5EE;color:#257A4D}.pill.wait{background:#FFF4E5;color:#8A5A00}"
    ".pill.bad{background:#FEECEB;color:#B42318}.pill.moved{background:#E9EDFF;color:#233B91}"
    ".facts{display:grid;grid-template-columns:120px 1fr;gap:6px 14px;margin:0}.facts dt{color:#68718A;font-size:13px}"
    ".facts dd{margin:0;font-weight:600;word-break:break-word}"
    ".btns{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 4px}"
    ".btns a{display:inline-flex;align-items:center;min-height:44px;box-sizing:border-box;padding:0 18px;border-radius:999px;"
    "border:2px solid #D9DDEA;color:#151B32;font-weight:700;text-decoration:none}"
    ".btns a.go{background:#F28C28;border-color:#F28C28;color:#1A1208}"
    ".big{font-size:19px;font-weight:700;margin:0}.note{font-size:14px;color:#68718A;margin:6px 0 0}"
    ".watch{background:#FFF4E5;border:1px solid #F5D9A8;border-radius:12px;padding:12px 16px;color:#7A4B00}"
    ".watch h2{color:#8A5A00}.watch ul{margin:0;padding-left:18px}"
    ".quote{margin:8px 0 0;padding:10px 14px;border-left:3px solid #D9DDEA;background:#F7F8FC;white-space:pre-wrap;word-break:break-word}"
    ".chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0}.chip{background:#F0F2F8;border-radius:8px;padding:2px 8px;font-size:13px}"
    ".score{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.score b{font-size:28px}"
    ".tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0}"
    ".tile{background:#F7F8FC;border:1px solid #E9EBF2;border-radius:10px;padding:8px 10px}.tile span{display:block;font-size:12px;color:#68718A}"
    ".tile b{font-size:18px}.tile.neg b{color:#B42318}"
    ".ev{font-size:12px;font-weight:600;margin-left:6px;white-space:nowrap}.ev.verified{color:#257A4D}.ev.observed{color:#68718A}"
    ".ev.risk{color:#B54708}"
    ".sec ul{margin:4px 0 10px;padding-left:20px}.sec h3{font-size:13px;margin:14px 0 4px;color:#68718A;letter-spacing:.04em;text-transform:uppercase}"
    ".bub{margin:8px 0;padding:10px 12px;border-radius:12px;white-space:pre-wrap;word-break:break-word;max-width:92%}"
    ".bub.v{background:#EEF1FF;margin-left:auto}.bub.a{background:#fff;border:1px solid #E4E7F2}"
    ".bub small{display:block;color:#68718A;font-size:11px;margin-top:4px}.bub.muted{opacity:.6}"
    ".bub details summary{cursor:pointer}"
    ".sys{text-align:center;margin:10px 0}.sys span{background:#F0F2F8;border-radius:999px;padding:3px 12px;font-size:13px;color:#68718A}"
    ".rows{list-style:none;padding:0;margin:0}.rows li{padding:7px 0;border-top:1px solid #F0F2F8;font-size:14px}"
    ".foot{margin-top:24px;font-size:12px;color:#8A91A6}"
    "@media(max-width:480px){.card{padding:18px 16px;margin:12px auto}.facts{grid-template-columns:1fr}.facts dd{margin-bottom:6px}"
    ".tiles{grid-template-columns:1fr 1fr}}"
)
HEAD = ("<meta name='robots' content='noindex,nofollow'><meta name='referrer' content='no-referrer'>"
        "<meta name='color-scheme' content='light'>")


def _a(href: str, text: str, cls: str = "") -> str:
    c = f" class='{cls}'" if cls else ""
    return f"<a{c} href='{esc(href)}' rel='noopener noreferrer'>{esc(text)}</a>"


def _sec(title: str, body: str, cls: str = "sec") -> str:
    return f"<section class='{cls}'><h2>{esc(title)}</h2>{body}</section>" if body else ""


def _ul(items: list[str]) -> str:
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else ""


def _header(d: dict[str, Any]) -> str:
    from app import outcomes

    pills = []
    if d["status"] == "cancelled":
        pills.append(f"<span class='pill bad'>Cancelled{' ' + esc(d['cancelled_at']) if d['cancelled_at'] else ''}</span>")
    elif d["status"] == "pending_zoom":
        pills.append("<span class='pill wait'>Awaiting Zoom confirmation</span>")
    elif d["status"] == "confirmed":
        pills.append("<span class='pill ok'>Confirmed</span>")
    if d["moved"]:
        pills.append("<span class='pill moved'>Moved</span>")
    br = d["brief"]
    if br:
        chip = br["headline"]
        chip += " · live rules score" if br["live"] else " · old score, refresh in console" if br["old"] else ""
        pills.append(f"<span class='pill'>{esc(chip)}</span>")
    if d["outcome"] and d["outcome"]["current"] in outcomes.OUTCOMES:
        pills.append(f"<span class='pill ok'>{esc(outcomes.OUTCOMES[d['outcome']['current']])}</span>")
    sub = " · ".join(x for x in (d["schedule_name"], f"{d['duration']} min" if d["duration"] else "") if x)
    return f"<p class='sub'>{esc(sub)}</p><div class='pills'>{''.join(pills)}</div>"


def _actions(d: dict[str, Any]) -> str:
    u = d["urls"]
    btns = []
    if u["join"]:
        btns.append(_a(u["join"], "Join Zoom", "go"))
    if u["mailto"]:
        btns.append(_a(u["mailto"], f"Email {d['first']}"))
    btns.append(_a(u["console"], "Open in console"))
    notes = []
    if d["status"] == "pending_zoom":
        notes.append("No Zoom meeting yet: the visitor still has to confirm on Zoom.")
    elif d["status"] == "confirmed" and d["method"] == "browser" and not u["join"]:
        notes.append("The Zoom link is in the invite Zoom Scheduler put on your calendar.")
    if d["zoom_error"]:
        notes.append(f"Zoom said: {d['zoom_error']}")
    return f"<div class='btns'>{''.join(btns)}</div>" + "".join(f"<p class='note'>{esc(n)}</p>" for n in notes)


def _when(d: dict[str, Any]) -> str:
    lines = [f"<p class='big'>{esc(d['label_host'])}</p>", f"<p class='note'>Their time: {esc(d['label_visitor'])}</p>"]
    if d["relative"]:
        lines.append(f"<p class='note'>{esc(d['relative'])}</p>")
    if d["moved"] and d["was_label"]:
        lines.append(f"<p class='note'>Was: {esc(d['was_label'])}</p>")
    if d["meeting_id"]:
        lines.append(f"<p class='note'>Meeting ID {esc(d['meeting_id'])}" + (f" · Passcode {esc(d['passcode'])}" if d["passcode"] else "") + "</p>")
    return _sec("When", "".join(lines))


def _watch(d: dict[str, Any]) -> str:
    items = (d["brief"] or {}).get("watch") or []
    return _sec("Watch out", _ul(items), "sec watch") if items else ""


_TRUST = {"website": "from their website", "domain": "from their email domain; website not checked",
          "typed": "they typed; unverified", "typed_personal": "they typed; unverified, personal email",
          "dead": "their email domain does not exist or takes no mail"}
# what checked their email domain, for a company read off it (precall.company_view 'proof')
_DOMAIN_PROOF = {"mx": "from their email domain, which receives mail; website not checked",
                 "a": "from their email domain, which exists; website not checked",
                 "unknown": "from their email domain; the domain could not be checked yet"}
# evidence tags on WHY THIS SCORE (precall.CLASS): the class only selects from these, every value is escaped
_TAG = {"verified": "checked", "observed": "seen", "risk": "warning"}


def _who(d: dict[str, Any]) -> str:
    rows = [("Name", esc(d["name"]))]
    if d["email"]:
        mail = _a(d["urls"]["mailto"], d["email"]) if d["urls"]["mailto"] else esc(d["email"])
        rows.append(("Email", mail + (f" <span class='note'>({esc(d['email_kind'])})</span>" if d["email_kind"] else "")))
    co = d["company"]
    if co.get("name"):
        href = company_link(co.get("domain") or "") if co.get("trust") in ("website", "domain") else ""
        shown = _a(href, co["name"]) if href else esc(co["name"])
        extra = (f"; they typed: {co['also']}" if co.get("trust") == "dead" else f"; email domain: {co['also']}") if co.get("also") else ""
        trust = _DOMAIN_PROOF.get(co.get("proof") or "", _TRUST["domain"]) if co.get("trust") == "domain" else _TRUST.get(co["trust"], "")
        rows.append(("Company", f"{shown} <span class='note'>({esc(trust)}{esc(extra)})</span>"))
    for g in d["guests"]:
        mail = _a(g["mailto"], g["email"]) if g["mailto"] else esc(g["email"])
        rows.append(("Guest", " · ".join(x for x in (esc(g["name"]), mail) if x)))
    body = "<dl class='facts'>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"
    if d["notes"]:
        body += f"<h3>Their note</h3><blockquote class='quote'>{esc(d['notes'])}</blockquote>"
    return _sec("Who", body)


def _where(d: dict[str, Any]) -> str:
    if not d["tracking"]:
        return ""
    rows = [(k, v) for k, v in (("Origin", d["origin"]), ("Network", d["network_line"]), ("Came from", d["channel"])) if v]
    body = "<dl class='facts'>" + "".join(f"<dt>{k}</dt><dd>{esc(v)}</dd>" for k, v in rows) + "</dl>" if rows else ""
    if d["tz_note"]:
        body += f"<p class='note'>{esc(d['tz_note'])}</p>"
    if d["pages"]:
        body += "<div class='chips'>" + "".join(f"<span class='chip'>{esc(p)}</span>" for p in d["pages"]) + "</div>"
    if d["visits"]:
        body += f"<p class='note'>{d['visits']} visit{'s' if d['visits'] != 1 else ''}" + (f" since {esc(d['first_seen'])}" if d["first_seen"] else "") + "</p>"
    return _sec("Where from", body)


def _brief(d: dict[str, Any]) -> str:
    br = d["brief"]
    if not br:
        return ""
    body = ""
    g = br["groups"]
    if g:
        word = br["headline"].rsplit(" · ", 1)[0] if br["verdict"] else br["label"]
        body += (f"<div class='score'><b>{esc(br['score'])}</b><span>/100 · {esc(word)}</span>"
                 + (f"<span class='note'>At booking: {esc(br['at_booking'])}</span>" if br["at_booking"] is not None else "") + "</div>")
        body += "<div class='tiles'>" + "".join(
            f"<div class='tile{' neg' if k == 'risk' and (g.get(k) or 0) < 0 else ''}'><span>{k.capitalize()}</span>"
            f"<b>{'−' if (g.get(k) or 0) < 0 else ''}{abs(int(g.get(k) or 0))}</b></div>" for k in ("fit", "intent", "engagement", "risk")) + "</div>"
    if br["evidence"]:
        body += f"<p class='note'>Evidence: {esc(br['evidence'])}</p>"
    if br["summary"]:
        body += f"<p>{esc(br['summary'])}</p>"
    why = [_reason_html(r) for r in br["reasons"] if r.get("cls") != "claimed"]
    if why:
        body += "<h3>Why this score</h3><ul>" + "".join(f"<li>{x}</li>" for x in why) + "</ul>"
    said = [r.get("text") or "" for r in br["reasons"] if r.get("cls") == "claimed"]
    for title, items in (("What they say (not scored)", said), ("What they asked", [f"“{q}”" for q in br["asked"] or []]),
                         ("Talking points", br["talking_points"]), ("Questions to ask", br["questions_to_ask"])):
        if items:
            body += f"<h3>{esc(title)}</h3>{_ul(items)}"
    who = ("Live rules score: no brief was stored" if br["live"] else "Written by the model" if br["composer"] == "model"
           else "Rule-based brief" if br["composer"] == "rules" else "")
    foot = " · ".join(x for x in (who, f"built {br['built_at']}" if br["built_at"] and not br["live"] else "", "refresh it in the console") if x)
    body += f"<p class='note'>{esc(foot)}</p>"
    return _sec("Pre-call brief", body)


def _reason_html(r: dict[str, Any]) -> str:
    """'+15 company email (lovelace.org)' and its evidence tag ('checked: website', 'seen', 'warning'); older briefs
    have no class and no tag."""
    pts = int(r.get("points") or 0)
    line = esc(f"{'+' if pts >= 0 else '−'}{abs(pts)} {r.get('text') or ''}")
    cls = r.get("cls") if r.get("cls") in _TAG else ""
    if not cls:
        return line
    return line + f"<span class='ev {cls}'>{esc(_TAG[cls])}{': ' + esc(r['proof']) if r.get('proof') else ''}</span>"


def _outcome_html(d: dict[str, Any]) -> str:
    from app import outcomes

    o = d["outcome"]
    if not o:
        return ""
    body = "<div class='btns'>" + "".join(_a(url, label, "go" if i == 0 else "") for i, (label, url) in enumerate(o["links"])) + "</div>"
    body += "<p class='note'>Each button opens the outcome page; saving still takes a press there.</p>"
    if o["current"] in outcomes.OUTCOMES:
        body += f"<p><span class='pill ok'>{esc(outcomes.OUTCOMES[o['current']])}</span></p>"
        if o["note"]:
            body += f"<blockquote class='quote'>{esc(o['note'])}</blockquote>"
        sent = _iso(o["followup_sent"])
        body += (f"<p class='note'>Follow-up sent {esc(_local(sent, '%d %b, %H:%M'))}</p>" if sent
                 else "<p class='note'>Follow-up not sent yet</p>")
        body += f"<p class='note'>{_a(o['change_url'], 'Change the outcome')}</p>"
    return _sec("Call outcome", body)


def _chat(d: dict[str, Any]) -> str:
    rows = d["transcript"]
    if not rows:
        return _sec("Chat", "<p class='note'>Booked from the form; no chat messages.</p>")
    out = [f"<p class='note'>{d['total']} message{'s' if d['total'] != 1 else ''}</p>"]
    for m in rows:
        t, when = m["text"], f"<small>{esc(m['time'])}</small>" if m["time"] else ""
        if m["outcome"] == "booking":
            out.append(f"<div class='sys'><span>{esc(_one_line(t, 200))}</span></div>")
            continue
        muted = " muted" if m["outcome"] in ("injection", "error", "stopped") else ""
        if m["role"] == "user":
            out.append(f"<div class='bub v{muted}'>{esc(t)}{when}</div>")
        elif len(t) > LONG_MSG:
            out.append(f"<div class='bub a{muted}'><details><summary>{esc(t[:280].rstrip())}…</summary>{esc(t)}</details>{when}</div>")
        else:
            out.append(f"<div class='bub a{muted}'>{esc(t)}{when}</div>")
    if d["truncated"]:
        out.append(f"<p class='note'>Showing the first {len(rows)} of {d['total']}; the rest is in the console</p>")
    return _sec("Chat", "".join(out))


def _earlier(d: dict[str, Any]) -> str:
    body = ""
    if d["earlier"]:
        body += "<ul class='rows'>" + "".join(
            "<li>" + esc(" · ".join(x for x in (r["date"], r["first_q"] or r["path"],
                                                f"{r['messages']} message{'s' if r['messages'] != 1 else ''}", r["channel"], r["network"], r["via"]) if x))
            + "</li>" for r in d["earlier"]) + "</ul>"
    if d["earlier_bookings"]:
        body += "<h3>Earlier bookings</h3><ul class='rows'>" + "".join(
            "<li>" + esc(" · ".join(x for x in (r["date"], r["call"], r["status"], r["outcome"].replace("_", " ")) if x)) + "</li>"
            for r in d["earlier_bookings"]) + "</ul>"
    return _sec("Earlier visits", body)


def render(d: dict[str, Any]) -> str:
    """The page (pure). Every value is escaped; no JavaScript."""
    from app import outcomes

    body = (_header(d) + _actions(d) + _when(d) + _watch(d) + _who(d) + _where(d) + _brief(d) + _outcome_html(d) + _chat(d)
            + _earlier(d) + f"<p class='foot'>Private page for {esc(d['host_name'])}. Anyone with this link can open it, so don't "
            f"forward it. Booking #{d['id']}.</p>")
    return outcomes._page(f"{d['name'] or 'Visitor'} · booking #{d['id']}", body, css=HOST_CSS, head=HEAD)
