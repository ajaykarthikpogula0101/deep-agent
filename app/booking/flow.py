"""In-chat booking: review a wanted time, confirm a booking, cancel one. Built on BookingService (Zoom clients,
lead storage, enrichment) and app/booking/availability.py (the grid).

confirm() is the only place a booking is made, and it runs when the visitor clicks "Confirm booking":
  1. validate details (no placeholders), per-email active-booking limit
  2. re-check the slot on Zoom right now (and against our own confirmed bookings)
  3. book: Zoom Scheduler API (POST /scheduler/attendee) -> Meetings API (POST /users/{host}/meetings) -> prefilled
     Zoom hand-off link when no API credentials are configured ("pending_zoom": the visitor finishes on Zoom)
  4. store the lead and the booking, queue both confirmation emails with the .ics invite (app/mailer.py)
Side effects are injectable (Deps) so the whole flow is testable without Postgres, SMTP or Zoom.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.booking import availability as avail
from app.booking.service import BookingService, _EMAIL_RE, _origin_line, looks_like_placeholder
from app.booking.zoom import AvailabilityError, InvalidTimeError, Schedule, Slot, SlotTakenError, ZoomOfficialClient, parse_start, parse_tz
from app.config import settings
from app.enrich import summary as company_summary

log = logging.getLogger("booking.flow")

ACTIVE = ("confirmed", "pending_zoom")


@dataclass
class Deps:
    store_booking: Callable[[dict], int]
    count_active: Callable[[str], int]
    busy: Callable[[datetime, datetime], list]
    mail: Callable[[dict], None]
    log_event: Callable[[str, str | None, dict], None] = lambda *a, **k: None
    enrich: Callable[[str], dict] | None = None


def default_deps() -> Deps:
    from app import store_bookings as sb
    from app.booking.email import send_booking_emails
    from app.db import log_event

    return Deps(store_booking=sb.insert, count_active=sb.count_active, busy=sb.busy_between, mail=send_booking_emails,
                log_event=log_event)


# ---------------------------------------------------------------- helpers
def _schedule_view(s: Schedule) -> dict[str, Any]:
    return {"slug": s.slug, "name": s.name, "duration_min": s.duration_min, "description": avail.describe(s),
            "booking_link": s.booking_link}


def _booking_view(b: dict[str, Any]) -> dict[str, Any]:
    tz = b["visitor_tz"]
    start = Slot(b["start_utc"], b["duration_min"])
    return {
        "id": b.get("id"), "status": b["status"], "method": b["method"],
        "schedule_slug": b["schedule_slug"], "schedule_name": b["schedule_name"], "duration_min": b["duration_min"],
        "start_iso": start.in_tz(tz).isoformat(), "end_iso": (start.in_tz(tz) + timedelta(minutes=b["duration_min"])).isoformat(),
        "label_visitor": start.label(tz), "label_host": start.label(settings.host_timezone), "visitor_tz": tz,
        "name": b["name"], "email": b["email"], "company": b.get("company") or "", "notes": b.get("notes") or "",
        "join_url": b.get("join_url"), "meeting_id": b.get("meeting_id"), "passcode": b.get("passcode"),
        "handoff_url": b.get("handoff_url"), "ics_url": b.get("ics_url"), "manage_url": b.get("manage_url"),
    }


def manage_urls(booking_id: int, token: str, base: str | None = None) -> dict[str, str]:
    base = (settings.public_base_url or base or "").rstrip("/")
    return {"ics_url": f"{base}/booking/{booking_id}/ics?t={token}",
            "manage_url": f"{base}/booking/{booking_id}/manage?t={token}",
            "cancel_url": f"{base}/booking/{booking_id}/cancel?t={token}"}


# ---------------------------------------------------------------- model tool: review a wanted time
def review(service: BookingService, schedule_slug: str, start: str, name: str, email: str, reason: str, visitor_tz: str,
           busy_fn: Callable | None = None) -> dict[str, Any]:
    """Nothing is booked here. The time is checked against the live grid; the client then shows the details form
    and the confirmation card (status 'review') or the nearest open times (status 'unavailable')."""
    try:
        tz = parse_tz(visitor_tz)
    except InvalidTimeError:
        tz = settings.host_timezone
    try:
        start_utc = parse_start(start)
    except InvalidTimeError as e:
        return {"status": "invalid", "message": f"I couldn't pin down that time ({e}). Ask the visitor to pick one in the picker."}
    data = avail.availability(service, schedule_slug, None, tz, busy_fn=busy_fn)
    if not data.get("ok"):
        return {"status": "unavailable", "message": data.get("message", "availability unavailable"),
                "fallback_link": data.get("fallback_link"), "choices": data.get("choices")}
    wanted = start_utc.astimezone(timezone.utc)
    match = next((s for s in avail.open_slots(data) if parse_start(s["start_iso"]) == wanted), None)
    prefill = {"name": (name or "").strip()[:120], "email": (email or "").strip()[:200], "reason": (reason or "").strip()[:1000]}
    if looks_like_placeholder(prefill["name"], prefill["email"]):
        prefill["name"], prefill["email"] = "", ""
    if match is None:
        alts = avail.nearest(data, wanted, 3)
        return {"status": "unavailable", "schedule": data["schedule"], "wanted": Slot(wanted, 0).label(tz),
                "alternatives": alts, "prefill": prefill, "timezone": tz,
                "message": "That time is not open on Deep's scheduler. The nearest open times are shown to the visitor; "
                           "ask them to pick one (do not list them yourself)."}
    return {"status": "review", "schedule": data["schedule"], "slot": match, "prefill": prefill, "timezone": tz,
            "message": "The time is open. The interface now shows a details form and a 'Confirm booking' button; nothing is booked "
                       "until the visitor clicks it. Tell them to check the details below and confirm."}


# ---------------------------------------------------------------- confirm
@dataclass
class ConfirmRequest:
    schedule_slug: str
    start: str
    name: str
    email: str
    visitor_tz: str
    company: str = ""
    notes: str = ""
    session_id: str | None = None
    origin: str = ""
    extra: dict = field(default_factory=dict)


def _book_on_zoom(service: BookingService, schedule: Schedule, start_utc: datetime, req: ConfirmRequest, tz: str) -> dict[str, Any]:
    """Returns {"method", "join_url", "meeting_id", "passcode", "zoom_event_id", "handoff_url", "error"}."""
    out: dict[str, Any] = {"method": "handoff", "join_url": None, "meeting_id": None, "passcode": None, "zoom_event_id": None,
                           "handoff_url": None, "error": None}
    official = next((c for c in service.clients if isinstance(c, ZoomOfficialClient)), None)
    first, _, last = req.name.partition(" ")
    if official is not None and settings.zoom_enable_api_booking:
        try:
            r = official.create_booking(schedule, start_utc, first, last, req.email, req.notes or req.company or "-", tz)
            out.update(method="scheduler", zoom_event_id=str(r.get("id") or r.get("event_id") or r.get("scheduled_event_id") or ""),
                       join_url=r.get("join_url") or r.get("joinUrl") or (r.get("location") or {}).get("join_url"),
                       meeting_id=str(r.get("meeting_id") or (r.get("location") or {}).get("meeting_id") or "") or None)
            return out
        except SlotTakenError:
            raise
        except AvailabilityError as e:
            log.warning("scheduler booking failed, trying the Meetings API: %s", e)
            out["error"] = str(e)[:200]
    if official is not None and settings.zoom_host_user_id:
        try:
            topic = f"{schedule.name} — {req.name} × {settings.host_name_short}"
            agenda = "\n".join(x for x in (req.notes, f"Company: {req.company}" if req.company else "",
                                           f"Booked via the {settings.site_base_url} assistant") if x)
            r = official.create_meeting(settings.zoom_host_user_id, topic, start_utc, schedule.duration_min, agenda, req.email)
            out.update(method="meeting", meeting_id=str(r.get("id") or ""), join_url=r.get("join_url"),
                       passcode=r.get("password") or r.get("passcode"))  # a scheduler error stays recorded for the console
            return out
        except AvailabilityError as e:
            log.error("meetings api booking failed: %s", e)
            out["error"] = str(e)[:200]
    out["handoff_url"] = BookingService._handoff_url(schedule.booking_link or settings.zoom_booking_base, req.name, req.email, start_utc)
    return out


def confirm(service: BookingService, req: ConfirmRequest, deps: Deps | None = None) -> dict[str, Any]:
    deps = deps or default_deps()
    name, email = (req.name or "").strip()[:120], (req.email or "").strip()[:200]
    company, notes = (req.company or "").strip()[:120], (req.notes or "").strip()[:1000]
    if not name or not _EMAIL_RE.match(email):
        return {"status": "invalid", "message": "Please give your full name and a valid email address."}
    if looks_like_placeholder(name, email):
        return {"status": "invalid", "message": "Please use your real name and email address."}
    try:
        tz = parse_tz(req.visitor_tz)
        start_utc = parse_start(req.start)
    except InvalidTimeError as e:
        return {"status": "invalid", "message": f"That time could not be read ({e}). Please pick it again."}
    now = service.now()
    if start_utc < now + timedelta(minutes=5):
        return {"status": "slot_taken", "message": "That time has already passed. Please pick another."}
    try:
        active = deps.count_active(email)
    except Exception as e:
        log.warning("count_active failed: %s", e)
        active = 0
    if active >= settings.booking_max_active_per_email:
        return {"status": "rate_limited", "message": f"You already have {active} upcoming bookings with Deep. "
                                                     "Please use those, or reply to your confirmation email to change them."}
    try:
        schedule = service.schedule_by_slug(req.schedule_slug)
    except AvailabilityError:
        schedule = None
    if schedule is None:
        return {"status": "unavailable", "message": "Deep's scheduler isn't responding right now. You can book directly on Zoom.",
                "fallback_link": settings.zoom_booking_base}

    # 2. re-check right before booking
    try:
        slots, _ = service._fetch(schedule, start_utc - timedelta(hours=1), start_utc + timedelta(hours=1), tz)
    except AvailabilityError as e:
        log.warning("confirm: availability check failed: %s", e)
        return {"status": "unavailable", "message": "Zoom's scheduler isn't responding right now, so I can't confirm the time. "
                                                    "Please try again in a minute or book directly on Zoom.",
                "fallback_link": schedule.booking_link or settings.zoom_booking_base, "retry": True}
    end_utc = start_utc + timedelta(minutes=schedule.duration_min)
    busy = []
    try:
        busy = deps.busy(start_utc - timedelta(hours=2), end_utc + timedelta(hours=2))
    except Exception as e:
        log.warning("busy lookup failed: %s", e)
    taken = not any(s.start_utc == start_utc for s in slots) or any(b0 < end_utc and start_utc < b1 for b0, b1 in busy)
    if taken:
        avail.invalidate(schedule.slug)
        data = avail.availability(service, schedule.slug, None, tz, busy_fn=deps.busy, use_cache=False)
        return {"status": "slot_taken", "message": "That time was just taken. Here are the nearest open times.",
                "alternatives": avail.nearest(data, start_utc, 3) if data.get("ok") else [], "schedule": _schedule_view(schedule)}

    # 3. book on Zoom
    try:
        zoom = _book_on_zoom(service, schedule, start_utc, req, tz)
    except SlotTakenError:
        avail.invalidate(schedule.slug)
        data = avail.availability(service, schedule.slug, None, tz, busy_fn=deps.busy, use_cache=False)
        return {"status": "slot_taken", "message": "Zoom reports that time was just taken. Here are the nearest open times.",
                "alternatives": avail.nearest(data, start_utc, 3) if data.get("ok") else [], "schedule": _schedule_view(schedule)}
    status = "confirmed" if zoom["method"] != "handoff" else "pending_zoom"

    # 4. store: lead (host console, digest, nudges) + booking (grid overlay, emails, cancel link)
    enrich_fn = deps.enrich or service.enrich
    try:
        data = enrich_fn(email) or {}
    except Exception:
        data = {}
    origin = req.origin or _origin_line(req.session_id)
    lead = {"name": name, "email": email, "reason": notes or company or f"{schedule.name} booking", "slot_start": start_utc,
            "visitor_tz": tz, "status": "booked" if status == "confirmed" else "handoff", "note": f"booked in chat ({zoom['method']})",
            "schedule": schedule.name, "schedule_slug": schedule.slug, "duration_min": schedule.duration_min,
            "handoff_url": zoom.get("handoff_url"), "slot_label_host": Slot(start_utc, 0).label(settings.host_timezone),
            "slot_label_visitor": Slot(start_utc, 0).label(tz), "session_id": req.session_id, "origin": origin,
            "enrichment": data, "company": company_summary(data) or company}
    lead_id = None
    try:
        lead_id = service.store_lead(lead)
    except Exception as e:
        log.error("lead store failed: %s", e)
    token = secrets.token_urlsafe(24)
    booking = {"lead_id": lead_id, "session_id": req.session_id, "name": name, "email": email, "company": company, "notes": notes,
               "schedule_slug": schedule.slug, "schedule_name": schedule.name, "duration_min": schedule.duration_min,
               "start_utc": start_utc, "end_utc": end_utc, "visitor_tz": tz, "method": zoom["method"], "status": status,
               "zoom_meeting_id": zoom.get("meeting_id"), "join_url": zoom.get("join_url"), "passcode": zoom.get("passcode"),
               "zoom_event_id": zoom.get("zoom_event_id"), "handoff_url": zoom.get("handoff_url"), "manage_token": token,
               "origin": origin, "company_line": lead["company"], "zoom_error": zoom.get("error")}
    try:
        booking["id"] = deps.store_booking(booking)
    except Exception as e:  # the Zoom side is done; never lose it silently
        log.error("booking store failed: %s", e)
        booking["id"] = None
    booking.update(manage_urls(booking["id"] or 0, token, req.extra.get("base_url")))
    booking["meeting_id"] = booking.get("zoom_meeting_id")
    avail.invalidate(schedule.slug)

    # 5. emails (background, retried) + event
    try:
        deps.mail(booking)
    except Exception as e:
        log.error("booking emails failed to queue: %s", e)
    try:
        deps.log_event("booking_confirmed" if status == "confirmed" else "booking_pending", req.session_id,
                       {"booking_id": booking["id"], "lead_id": lead_id, "method": zoom["method"], "slot": str(start_utc),
                        "schedule": schedule.slug, "email": email, "zoom_error": zoom.get("error")})
    except Exception:
        pass
    view = _booking_view(booking)
    msg = (f"Booked: {schedule.name}, {view['label_visitor']}." if status == "confirmed"
           else f"Your time is held: {schedule.name}, {view['label_visitor']}. Finish on Zoom to make it final.")
    return {"status": status, "message": msg, "booking": view, "emails_queued": True}


# ---------------------------------------------------------------- cancel
def cancel(booking: dict[str, Any], service: BookingService | None = None, deps: Deps | None = None,
           mark: Callable[[int], bool] | None = None, mail: Callable[[dict], None] | None = None) -> dict[str, Any]:
    """Cancel a booking from the visitor's email link: delete the Zoom meeting when we created one, mark the row,
    tell both sides. Scheduler-API bookings are cancelled on our side and the host is told to cancel in Zoom."""
    if booking.get("status") == "cancelled":
        return {"ok": True, "already": True}
    service = service or BookingService()
    zoom_note = ""
    if booking.get("method") == "meeting" and booking.get("zoom_meeting_id"):
        official = next((c for c in service.clients if isinstance(c, ZoomOfficialClient)), None)
        if official is not None:
            try:
                official.delete_meeting(str(booking["zoom_meeting_id"]))
            except AvailabilityError as e:
                zoom_note = f"Zoom meeting could not be deleted automatically: {e}"
                log.error(zoom_note)
    elif booking.get("method") == "scheduler":
        zoom_note = "Cancelled here; please also cancel the event in Zoom Scheduler."
    if mark is None:
        from app import store_bookings as sb

        mark = sb.cancel
    ok = bool(mark(int(booking["id"]))) if booking.get("id") else False
    booking = dict(booking, status="cancelled", zoom_note=zoom_note)
    if mail is None:
        from app.booking.email import send_cancel_emails

        mail = send_cancel_emails
    try:
        mail(booking)
    except Exception as e:
        log.error("cancel emails failed: %s", e)
    avail.invalidate(booking.get("schedule_slug"))
    return {"ok": ok, "zoom_note": zoom_note}


__all__ = ["Deps", "ConfirmRequest", "confirm", "review", "cancel", "default_deps", "manage_urls"]
