"""Follow-up nudge for unfinished Zoom bookings.

A 'handoff' lead means the visitor picked a time and was sent to Zoom with their details prefilled, but only
Zoom knows whether they clicked "confirm". NUDGE_AFTER_HOURS later (default 24 h), if the host has not marked the
lead confirmed in the console and the wanted time is still ahead, the visitor gets ONE email (template
visitor_nudge in Console → Emails) with the same prefilled link. Runs hourly; never twice for the same lead.

Only hand-offs made after the feature went live are considered (settings key nudge:since, written on the first run),
so enabling it never emails a backlog. Owner actions: POST /admin/leads/{id}/confirm (no nudge, counts as booked
in the digest), POST /admin/nudge/run.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app import templates
from app.config import settings

log = logging.getLogger("nudge")

LOOKBACK_DAYS = 7
BATCH = 50


def since() -> str:
    """ISO time the nudges went live, stored once in `settings` (nudge:since). Hand-offs before it are never
    reminded, so switching the feature on never emails a backlog of old test or real leads."""
    from datetime import datetime, timezone

    from app.db import get_setting, set_setting

    s = get_setting("nudge:since")
    if not s:
        s = datetime.now(timezone.utc).isoformat()
        set_setting("nudge:since", s)
    return s


def due(after_hours: int | None = None, since_iso: str | None = None) -> list[dict[str, Any]]:
    from app.db import conn

    hours = int(after_hours if after_hours is not None else settings.nudge_after_hours)
    since_iso = since_iso or since()
    with conn() as c:
        rows = c.execute(
            """SELECT id, ts, name, email, reason, slot_start, visitor_tz, schedule_slug, company, session_id
               FROM leads
               WHERE status = 'handoff' AND confirmed_at IS NULL AND nudged_at IS NULL
                 AND ts < now() - make_interval(hours => %s) AND ts > now() - make_interval(days => %s)
                 AND ts > %s::timestamptz
                 AND (slot_start IS NULL OR slot_start > now() + interval '1 hour')
               ORDER BY ts LIMIT %s""", (hours, LOOKBACK_DAYS, since_iso, BATCH)).fetchall()
    cols = ["id", "ts", "name", "email", "reason", "slot_start", "visitor_tz", "schedule_slug", "company", "session_id"]
    return [dict(zip(cols, r)) for r in rows]


def lead_for_email(row: dict[str, Any], schedules: list | None = None) -> dict[str, Any]:
    """Template variables for the nudge: schedule name/duration from the live call types when available,
    the prefilled Zoom link rebuilt exactly as the booking turn made it, slot labels in both zones."""
    from app.booking.service import BookingService
    from app.booking.zoom import Slot

    slug = row.get("schedule_slug") or ""
    name = duration = None
    link = f"{settings.zoom_booking_base}/{slug}" if slug else settings.zoom_booking_base
    for s in schedules or []:
        if s.slug.lower() == slug.lower():
            name, duration, link = s.name, s.duration_min, s.booking_link or link
            break
    start = row.get("slot_start")
    tz = row.get("visitor_tz") or settings.host_timezone
    lead = dict(row)
    lead.update({
        "status": "nudge", "schedule": name or (slug.replace("-", " ").title() if slug else "-"), "duration_min": duration,
        "handoff_url": BookingService._handoff_url(link, row.get("name") or "", row.get("email") or "", start) if start else link,
        "slot_label_host": Slot(start, 0).label(settings.host_timezone) if start else "-",
        "slot_label_visitor": Slot(start, 0).label(tz) if start else "-",
        "visitor_tz": tz if start else "-",
    })
    return lead


def run(send: Callable[[dict], bool] | None = None, after_hours: int | None = None, since_iso: str | None = None) -> dict[str, Any]:
    """Send every due nudge once. Returns {"checked", "sent", "skipped"}."""
    from app.db import conn, log_event

    if send is None:
        from app.booking.email import send_visitor_confirmation as send
    try:
        rows = due(after_hours, since_iso)
    except Exception as e:
        log.error("nudge query failed: %s", e)
        return {"checked": 0, "sent": 0, "skipped": 0, "error": str(e)[:200]}
    schedules: list = []
    if rows:
        try:
            from app.booking.service import BookingService

            schedules = BookingService().list_schedules()
        except Exception as e:
            log.warning("nudge: live call types unavailable, using slugs: %s", e)
    sent = skipped = 0
    for row in rows:
        lead = lead_for_email(row, schedules)
        ok = False
        try:
            ok = bool(send(lead))
        except Exception as e:
            log.error("nudge send failed for lead %s: %s", row["id"], e)
        # mark it either way: a lead is never nudged twice, and a disabled template counts as 'decided'
        with conn() as c:
            c.execute("UPDATE leads SET nudged_at = now() WHERE id = %s", (row["id"],))
            c.commit()
        log_event("nudge", row.get("session_id"), {"lead_id": row["id"], "sent": ok, "slot": str(row.get("slot_start"))})
        sent += int(ok)
        skipped += int(not ok)
    if rows:
        log.info("nudges: %d checked, %d sent, %d skipped", len(rows), sent, skipped)
    return {"checked": len(rows), "sent": sent, "skipped": skipped}


def confirm(lead_id: int) -> bool:
    """The host saw the Zoom confirmation (or spoke to the visitor): no nudge, counted as booked."""
    from app.db import conn, log_event

    with conn() as c:
        n = c.execute("UPDATE leads SET confirmed_at = now() WHERE id = %s AND confirmed_at IS NULL", (lead_id,)).rowcount
        c.commit()
    if n:
        log_event("lead_confirmed", None, {"lead_id": lead_id})
    return n > 0


def preview_lead() -> dict[str, Any]:
    """Sample for the console preview / test mail."""
    lead = dict(templates.SAMPLE_LEAD)
    lead["status"] = "nudge"
    return lead

