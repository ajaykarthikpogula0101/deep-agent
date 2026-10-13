"""Day-before reminder for every upcoming booking made in the chat.

Hourly (:45, host timezone): every active booking (confirmed or still to be confirmed on Zoom) that starts within
REMINDER_BEFORE_HOURS and more than an hour from now, and has not been reminded yet, gets the editable
"visitor_reminder" email (Console -> Emails) with the join link, or the confirm link when the hold is still pending.
The same pass sends the host a "Brief for tomorrow" with a freshly built pre-call brief (app/precall.py,
PRECALL_HOST_REMINDER), except for bookings made in the last 12 hours, whose "New booking" email already carried it.
A booking is reminded once (bookings.reminder_sent_at), whether or not the template is enabled. Only bookings made
after the feature went live are considered (settings key reminder:since), so switching it on never mails a backlog.
Owner action: POST /admin/reminders/run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.config import settings

log = logging.getLogger("reminders")

BATCH = 50
SINCE_KEY = "reminder:since"


def since() -> str:
    from app.db import get_setting, set_setting

    s = get_setting(SINCE_KEY)
    if not s:
        s = datetime.now(timezone.utc).isoformat()
        set_setting(SINCE_KEY, s)
    return s


def due(before_hours: int | None = None, since_iso: str | None = None) -> list[dict[str, Any]]:
    from app import store_bookings as sb
    from app.db import conn

    hours = int(before_hours if before_hours is not None else settings.reminder_before_hours)
    since_iso = since_iso or since()
    with conn() as c:
        rows = c.execute(
            """SELECT id FROM bookings
               WHERE status IN ('confirmed', 'pending_zoom') AND reminder_sent_at IS NULL
                 AND start_utc > now() + interval '1 hour' AND start_utc <= now() + make_interval(hours => %s)
                 AND created_at > %s::timestamptz
               ORDER BY start_utc LIMIT %s""", (hours, since_iso, BATCH)).fetchall()
    out = []
    for (bid,) in rows:
        b = sb.get(int(bid))
        if b:
            out.append(b)
    return out


def booking_for_email(b: dict[str, Any]) -> dict[str, Any]:
    """The booking row plus the manage/ics links the templates can show."""
    from app.booking.flow import manage_urls

    out = dict(b)
    if b.get("id") and b.get("manage_token"):
        out.update(manage_urls(int(b["id"]), b["manage_token"]))
    return out


def run(send: Callable[[dict], bool] | None = None, before_hours: int | None = None, since_iso: str | None = None,
        host_send: Callable[[dict], bool] | None = None) -> dict[str, Any]:
    """Send every due reminder once. Returns {"checked", "sent", "skipped"} (+ "host_briefs" when the host email is on).
    The host brief goes with the default sender only, or with an explicit `host_send`."""
    from app.db import conn, log_event

    if send is None:
        from app.booking.email import send_reminder_email as send

        if host_send is None and settings.precall_enabled and settings.precall_host_reminder:
            from app.precall import send_host_reminder as host_send
    try:
        rows = due(before_hours, since_iso)
    except Exception as e:
        log.error("reminder query failed: %s", e)
        return {"checked": 0, "sent": 0, "skipped": 0, "error": str(e)[:200]}
    sent = skipped = briefs = 0
    for b in rows:
        ok = False
        try:
            ok = bool(send(booking_for_email(b)))
        except Exception as e:
            log.error("reminder send failed for booking %s: %s", b.get("id"), e)
        with conn() as c:  # marked either way: never twice, and a disabled template counts as decided
            c.execute("UPDATE bookings SET reminder_sent_at = now() WHERE id = %s", (b["id"],))
            c.commit()
        try:
            log_event("reminder", b.get("session_id"), {"booking_id": b.get("id"), "sent": ok, "slot": str(b.get("start_utc"))})
        except Exception:
            pass
        sent += int(ok)
        skipped += int(not ok)
        created = b.get("created_at")
        if host_send and not (created and datetime.now(timezone.utc) - created < timedelta(hours=12)):
            try:
                briefs += int(bool(host_send(booking_for_email(b))))
            except Exception as e:
                log.error("host brief failed for booking %s: %s", b.get("id"), e)
    if rows:
        log.info("reminders: %d checked, %d sent, %d skipped, %d host briefs", len(rows), sent, skipped, briefs)
    out = {"checked": len(rows), "sent": sent, "skipped": skipped}
    if host_send:
        out["host_briefs"] = briefs
    return out
