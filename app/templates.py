"""Email templates with dynamic variables, editable from the console (Console → Emails).

Two audiences, three templates:
  host brief            to the host, for every lead (booking hand-off, API booking, enquiry, human hand-over)
  visitor booking       to the visitor after a booking step ("Thank you for booking with {brand}: {title} on {date_visitor}")
  visitor handover      to the visitor after they asked for a human reply

Variables (unknown ones render as empty, never as an error):
  {brand}         derived from the call type via the brand map, else the default brand (e.g. LakeB2B, SPAN Global Services)
  {title}         the call type's name (e.g. LakeB2B Discovery Call)       {duration}  minutes
  {kind}          what happened, in words (e.g. Demo request, handing off to Zoom)
  {name} {first_name} {email} {reason}
  {date}          slot in the host's timezone      {date_visitor} slot in the visitor's timezone   {visitor_tz} {host_tz}
  {link}          the Zoom confirmation link (hand-off)        {next_step}  one sentence that depends on the outcome
  {origin}        where the visitor came from (city, channel)  {note}       internal note (host only)
  {company}       the visitor's company from their email domain (app/enrich.py); empty for personal addresses
  {host_name} {host_email} {site}

Templates live in the `settings` table under keys `tpl:<name>`; missing keys fall back to DEFAULTS below.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from app.config import settings
from app.db import get_settings_prefix, set_setting

log = logging.getLogger("templates")

CACHE_SECONDS = 30
MAX_CHARS = 4000

DEFAULTS: dict[str, str] = {
    "brand_default": "Champions Group",
    # one per line: keyword=Brand. The keyword is matched against the call type's name and slug, case-insensitive.
    "brand_map": "lakeb2b=LakeB2B\nlake b2b=LakeB2B\nspan=SPAN Global Services\nampliz=Ampliz\nmetricfox=MetricFox\n"
                 "recruit=Recruit Champ\nchampions=Champions Group\naccelerator=Champions Accelerator",
    "host_name": "Deep",
    "host_subject": "[{brand}] {kind}: {name} · {title} · {date}",
    "host_body": (
        "{kind}\n\n"
        "Name:    {name}\n"
        "Email:   {email}\n"
        "Company: {company}\n"
        "Reason:  {reason}\n"
        "Call:    {title}\n"
        "Wanted:  {date}  /  visitor time {date_visitor} ({visitor_tz})\n"
        "Note:    {note}\n"
        "Where:   {origin}\n\n"
        "Sent by the website assistant. Reply to the visitor directly if the Zoom booking never lands.\n"
    ),
    "visitor_booking_enabled": "true",
    "visitor_booking_subject": "Thank you for booking with {brand}: {title} on {date_visitor}",
    "visitor_booking_body": (
        "Hi {first_name},\n\n"
        "Thank you for booking with {brand}.\n\n"
        "Call:   {title} ({duration} min)\n"
        "When:   {date_visitor} ({visitor_tz})\n"
        "Topic:  {reason}\n\n"
        "{next_step}\n\n"
        "If anything changes, just reply to this email.\n\n"
        "{host_name}\n{site}\n"
    ),
    "visitor_handover_enabled": "true",
    "visitor_handover_subject": "Thanks for your message to {brand}",
    "visitor_handover_body": (
        "Hi {first_name},\n\n"
        "Thanks for reaching out. {host_name} has your message and will reply to this address.\n\n"
        "Your message:\n{reason}\n\n"
        "{host_name}\n{site}\n"
    ),
    # follow-up when a Zoom hand-off is still unconfirmed after NUDGE_AFTER_HOURS (app/nudge.py)
    # in-chat booking (app/booking/flow.py): visitor confirmation + host 'New booking', both carry the .ics invite
    "visitor_confirmed_enabled": "true",
    "visitor_confirmed_subject": "{headline}: {title} on {date_visitor}",
    "visitor_confirmed_body": (
        "Hi {first_name},\n\n"
        "{headline}.\n\n"
        "Call:     {title} ({duration} min) with {host_name}\n"
        "When:     {date_visitor}\n"
        "Zoom:     {join_url}\n"
        "{meeting_line}\n"
        "Topic:    {reason}\n\n"
        "{next_step}\n\n"
        "The calendar invite is attached. {manage_line}\n\n"
        "{host_name}\n{site}\n"
    ),
    "host_booking_subject": "[{brand}] New booking: {name} · {title} · {date}",
    "host_booking_body": (
        "New booking through the website assistant ({method_line}).\n\n"
        "Name:     {name}\n"
        "Email:    {email}\n"
        "Company:  {company}\n"
        "Call:     {title} ({duration} min)\n"
        "When:     {date}  /  visitor time {date_visitor}\n"
        "Zoom:     {join_url}\n"
        "{meeting_line}\n"
        "Notes:    {reason}\n"
        "Where:    {origin}\n\n"
        "The calendar invite is attached.\n"
    ),
    "visitor_nudge_enabled": "true",
    "visitor_nudge_subject": "Still want to talk with {host_name}? {title} on {date_visitor}",
    "visitor_nudge_body": (
        "Hi {first_name},\n\n"
        "You picked {date_visitor} for a {title} with {host_name}, but the Zoom booking wasn't completed, "
        "so that time isn't reserved yet.\n\n"
        "{next_step}\n\n"
        "If the time no longer works, just reply to this email and we'll find another.\n\n"
        "{host_name}\n{site}\n"
    ),
}

KINDS = {"handoff": "Demo request, handing off to Zoom", "booked": "Demo booked", "enquiry": "Enquiry, scheduler unavailable",
         "handover": "Visitor wants a human reply", "nudge": "Reminder: Zoom booking not yet confirmed",
         "confirmed": "Booked in chat", "pending_zoom": "Booked in chat, Zoom confirmation pending"}

NEXT_STEP = {
    "handoff": "One last step: confirm the time on Zoom here, your details are already filled in: {link}",
    "booked": "It's confirmed. A Zoom calendar invite follows separately.",
    "enquiry": "Zoom's scheduler was unavailable for a moment, so {host_name} has your details and will confirm the time by email.",
    "handover": "{host_name} will reply to this email address.",
    "nudge": "Confirm it here, your details are already filled in: {link}",
    "confirmed": "Join with the Zoom link above when it's time. Nothing else to do.",
    "pending_zoom": "One last step: confirm the time on Zoom here, your details are already filled in: {link}",
}

HEADLINE = {"confirmed": "Your call with {host_name} is confirmed", "pending_zoom": "Your call with {host_name}: one last step"}
METHOD_LINE = {"scheduler": "booked on the Zoom Scheduler", "meeting": "Zoom meeting created",
               "handoff": "time held in chat; the visitor still has to confirm on Zoom"}

VARIABLES = ["brand", "title", "duration", "kind", "name", "first_name", "email", "reason", "date", "date_visitor", "visitor_tz",
             "host_tz", "link", "next_step", "origin", "note", "company", "host_name", "host_email", "site",
             "headline", "join_url", "meeting_id", "passcode", "meeting_line", "ics_url", "manage_url", "manage_line", "method_line"]

_VAR = re.compile(r"\{([a-z_]+)\}")
_cache: dict[str, tuple[float, dict[str, str]]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- storage
def get_templates() -> dict[str, str]:
    """DEFAULTS overlaid with whatever the owner saved; cached; never raises."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get("tpl")
        if hit and now - hit[0] < CACHE_SECONDS:
            return dict(hit[1])
    merged = dict(DEFAULTS)
    try:
        saved = get_settings_prefix("tpl:")
    except Exception as e:
        log.warning("template read failed, using defaults: %s", e)
        saved = {}
    for key, value in saved.items():
        if key in DEFAULTS and value is not None:
            merged[key] = value
    with _lock:
        _cache["tpl"] = (now, dict(merged))
    return merged


def set_templates(values: dict[str, str]) -> dict[str, str]:
    """Save the given keys (unknown keys ignored). An empty value restores the default."""
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        value = (value or "").strip()[:MAX_CHARS]
        set_setting(f"tpl:{key}", value if value else None)
    with _lock:
        _cache.pop("tpl", None)
    return get_templates()


# ---------------------------------------------------------------- rendering
def render(template: str, variables: dict[str, Any]) -> str:
    return _VAR.sub(lambda m: str(variables.get(m.group(1), "") or ""), template or "")


def parse_brand_map(text: str) -> list[tuple[str, str]]:
    out = []
    for line in (text or "").splitlines():
        key, sep, brand = line.partition("=")
        if sep and key.strip() and brand.strip():
            out.append((key.strip().lower(), brand.strip()))
    return out


def brand_for(schedule_name: str | None, slug: str | None, tpl: dict[str, str] | None = None) -> str:
    tpl = tpl or get_templates()
    hay = f"{schedule_name or ''} {slug or ''}".lower()
    for key, brand in parse_brand_map(tpl.get("brand_map", "")):
        if key in hay:
            return brand
    return tpl.get("brand_default") or DEFAULTS["brand_default"]


def build_vars(lead: dict[str, Any], tpl: dict[str, str] | None = None) -> dict[str, str]:
    tpl = tpl or get_templates()
    status = lead.get("status") or "lead"
    name = (lead.get("name") or "").strip()
    title = lead.get("schedule") if lead.get("schedule") not in (None, "-") else ""
    host_name = tpl.get("host_name") or DEFAULTS["host_name"]
    v = {
        "brand": brand_for(title, lead.get("schedule_slug"), tpl),
        "title": title or "a call with " + host_name,
        "duration": str(lead.get("duration_min") or ""),
        "kind": KINDS.get(status, "Lead"),
        "name": name, "first_name": name.split(" ")[0] if name else "there",
        "email": lead.get("email") or "", "reason": lead.get("reason") or "",
        "date": lead.get("slot_label_host") if lead.get("slot_label_host") not in (None, "-") else "",
        "date_visitor": lead.get("slot_label_visitor") if lead.get("slot_label_visitor") not in (None, "-") else "",
        "visitor_tz": lead.get("visitor_tz") if lead.get("visitor_tz") not in (None, "-") else "",
        "host_tz": settings.host_timezone, "link": lead.get("handoff_url") or "",
        "origin": lead.get("origin") or "", "note": lead.get("note") or "", "company": lead.get("company") or "",
        "host_name": host_name, "host_email": settings.host_email,
        "site": settings.site_base_url.replace("https://", "").replace("http://", ""),
        "join_url": lead.get("join_url") or "", "meeting_id": str(lead.get("meeting_id") or ""), "passcode": lead.get("passcode") or "",
        "ics_url": lead.get("ics_url") or "", "manage_url": lead.get("manage_url") or "",
    }
    v["meeting_line"] = (f"Meeting ID {v['meeting_id']}" + (f" · Passcode {v['passcode']}" if v["passcode"] else "")) if v["meeting_id"] else ""
    v["manage_line"] = f"Need to change it? Cancel or reschedule here: {v['manage_url']}" if v["manage_url"] else ""
    v["method_line"] = METHOD_LINE.get(lead.get("method") or "", "")
    v["headline"] = render(HEADLINE.get(status, ""), v)
    v["next_step"] = render(NEXT_STEP.get(status, ""), v)
    return v


def _tidy(body: str) -> str:
    """Drop lines whose only content was an empty variable (e.g. 'Note:    ') and collapse blank runs."""
    lines = [ln for ln in body.splitlines() if not re.fullmatch(r"\s*[A-Za-z ]{1,12}:\s*", ln)]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
    return out


def _subject(text: str) -> str:
    text = re.sub(r"(\s*·\s*){2,}", " · ", text)            # two separators in a row when a variable was empty
    return re.sub(r"^(\s*·\s*)+|(\s*·\s*)+$", "", text).strip()


def render_host(lead: dict[str, Any], tpl: dict[str, str] | None = None) -> tuple[str, str]:
    tpl = tpl or get_templates()
    v = build_vars(lead, tpl)
    subject = _subject(render(tpl["host_subject"], v))
    return subject or f"[{v['brand']}] {v['kind']}", _tidy(render(tpl["host_body"], v))


def render_visitor(lead: dict[str, Any], tpl: dict[str, str] | None = None) -> tuple[str, str] | None:
    """Visitor email for the lead's status, or None when that kind is disabled or has no template."""
    tpl = tpl or get_templates()
    status = lead.get("status")
    kind = ("handover" if status == "handover" else "nudge" if status == "nudge"
            else "confirmed" if status in ("confirmed", "pending_zoom")
            else "booking" if status in ("handoff", "booked", "enquiry") else None)
    if not kind or (tpl.get(f"visitor_{kind}_enabled", "true").strip().lower() not in ("true", "1", "yes", "on")):
        return None
    v = build_vars(lead, tpl)
    subject = _subject(render(tpl[f"visitor_{kind}_subject"], v)) or f"Thank you from {v['brand']}"
    return subject, _tidy(render(tpl[f"visitor_{kind}_body"], v))


def _label(dt, tz: str) -> str:
    from zoneinfo import ZoneInfo

    return dt.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %H:%M") + f" ({tz})"


def booking_to_lead(b: dict[str, Any]) -> dict[str, Any]:
    """A booking row/dict (app/booking/flow.py) in the lead shape the templates read."""
    tz = b.get("visitor_tz") or settings.host_timezone
    lead = dict(b)
    lead.update({"schedule": b.get("schedule_name") or b.get("schedule") or "-", "reason": b.get("notes") or b.get("reason") or "",
                 "company": b.get("company_line") or b.get("company") or "", "handoff_url": b.get("handoff_url") or "",
                 "meeting_id": b.get("zoom_meeting_id") or b.get("meeting_id") or "",
                 "slot_label_host": _label(b["start_utc"], settings.host_timezone) if b.get("start_utc") else "-",
                 "slot_label_visitor": _label(b["start_utc"], tz) if b.get("start_utc") else "-", "visitor_tz": tz})
    return lead


def render_booking_visitor(b: dict[str, Any], tpl: dict[str, str] | None = None) -> tuple[str, str] | None:
    return render_visitor(booking_to_lead(b), tpl)


def render_booking_host(b: dict[str, Any], tpl: dict[str, str] | None = None) -> tuple[str, str]:
    tpl = tpl or get_templates()
    v = build_vars(booking_to_lead(b), tpl)
    subject = _subject(render(tpl["host_booking_subject"], v))
    return subject or f"[{v['brand']}] New booking", _tidy(render(tpl["host_booking_body"], v))


def html_wrap(subject: str, body: str, cta: tuple[str, str] | None = None) -> str:
    """The plain-text email as a simple dark/orange HTML card (the text version is always sent alongside)."""
    import html as h

    def line(ln: str) -> str:
        t = h.escape(ln)
        t = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#F28C28">\1</a>', t)
        m = re.match(r"^([A-Za-z ]{1,12}):(\s+)(.*)$", t)
        if m and m.group(2):
            return f'<tr><td style="color:#8A8D93;padding:3px 12px 3px 0;white-space:nowrap;vertical-align:top">{m.group(1)}</td><td style="padding:3px 0">{m.group(3)}</td></tr>'
        return f'<p style="margin:0 0 12px">{t}</p>'

    parts, table = [], []
    for ln in body.splitlines():
        piece = line(ln) if ln.strip() else ""
        if piece.startswith("<tr>"):
            table.append(piece)
            continue
        if table:
            parts.append('<table style="border-collapse:collapse;font-size:15px;margin:0 0 12px">' + "".join(table) + "</table>")
            table = []
        if piece:
            parts.append(piece)
    if table:
        parts.append('<table style="border-collapse:collapse;font-size:15px;margin:0 0 12px">' + "".join(table) + "</table>")
    button = (f'<p style="margin:20px 0"><a href="{h.escape(cta[1])}" style="display:inline-block;background:#F28C28;color:#1A1208;'
              f'font-weight:600;text-decoration:none;padding:12px 22px;border-radius:999px">{h.escape(cta[0])}</a></p>') if cta and cta[1] else ""
    site = settings.site_base_url.replace("https://", "").replace("http://", "")
    return (f'<!doctype html><html><body style="margin:0;background:#000;padding:24px 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
            f'<div style="max-width:560px;margin:0 auto;background:#0F0F10;border:1px solid #1F1F22;border-radius:16px;padding:28px;color:#F2F3F5;font-size:15px;line-height:1.55">'
            f'<div style="color:#F28C28;font-weight:700;font-size:13px;letter-spacing:.04em;margin-bottom:14px">ask deep &gt;_</div>'
            f'<h1 style="font-size:20px;margin:0 0 16px">{h.escape(subject)}</h1>' + "".join(parts) + button +
            f'<p style="color:#8A8D93;font-size:12px;margin:20px 0 0">Sent by the {h.escape(site)} assistant.</p></div></body></html>')


SAMPLE_LEAD: dict[str, Any] = {
    "name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "B2B data for EU fintech", "status": "handoff",
    "schedule": "LakeB2B Discovery Call", "schedule_slug": "discovery-call", "duration_min": 15,
    "slot_label_host": "Wed 07 Oct, 19:00 (Asia/Kolkata)", "slot_label_visitor": "Wed 07 Oct, 09:30 (America/New_York)",
    "visitor_tz": "America/New_York", "handoff_url": "https://scheduler.zoom.us/sreedeep/discovery-call?firstname=Ada&email=ada%40lovelace.org",
    "origin": "Bengaluru, Karnataka, IN · via linkedin.com (social) · visit 2 · 4 messages", "note": "",
    "company": "Lovelace Analytical Engines (lovelace.org) · Computation for the modern enterprise",
}


from datetime import datetime as _dt, timezone as _tz  # noqa: E402

SAMPLE_BOOKING: dict[str, Any] = {
    "id": 42, "name": "Ada Lovelace", "email": "ada@lovelace.org", "company": "Lovelace Analytical Engines", "notes": "B2B data for EU fintech",
    "schedule_slug": "discovery-call", "schedule_name": "LakeB2B Discovery Call", "duration_min": 15,
    "start_utc": _dt(2026, 10, 7, 13, 30, tzinfo=_tz.utc), "end_utc": _dt(2026, 10, 7, 13, 45, tzinfo=_tz.utc), "visitor_tz": "America/New_York",
    "method": "meeting", "status": "confirmed", "zoom_meeting_id": "812 3456 7890", "join_url": "https://zoom.us/j/81234567890?pwd=sample",
    "passcode": "742913", "handoff_url": "", "ics_url": "https://assistant.deependhq.com/booking/42/ics?t=sample",
    "manage_url": "https://assistant.deependhq.com/booking/42/manage?t=sample", "origin": SAMPLE_LEAD["origin"],
    "company_line": "Lovelace Analytical Engines (lovelace.org) · Computation for the modern enterprise",
}


def preview(kind: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Sample lead rendered with the saved templates plus any unsaved edits from the console."""
    tpl = get_templates()
    for k, v in (overrides or {}).items():
        if k in DEFAULTS:
            tpl[k] = (v or "").strip() or DEFAULTS[k]
    lead = dict(SAMPLE_LEAD)
    if kind == "host_booking":
        s, b = render_booking_host(SAMPLE_BOOKING, tpl)
        return {"subject": s, "body": b}
    if kind == "visitor_confirmed":
        r = render_booking_visitor(SAMPLE_BOOKING, tpl)
        s, b = r if r else ("(disabled)", "")
        return {"subject": s, "body": b}
    if kind == "host":
        s, b = render_host(lead, tpl)
    else:
        lead["status"] = "handover" if kind == "visitor_handover" else "nudge" if kind == "visitor_nudge" else "handoff"
        r = render_visitor(lead, tpl)
        s, b = r if r else ("(disabled)", "")
    return {"subject": s, "body": b}


def previews(overrides: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    return {k: preview(k, overrides) for k in ("host", "visitor_booking", "visitor_handover", "visitor_nudge", "visitor_confirmed", "host_booking")}
