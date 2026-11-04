"""Postgres side of in-chat bookings (table `bookings`, see app/db.py). Kept apart from the flow so it can be faked."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.db import conn

COLS = ["id", "created_at", "lead_id", "session_id", "name", "email", "company", "notes", "schedule_slug", "schedule_name",
        "duration_min", "start_utc", "end_utc", "visitor_tz", "method", "zoom_meeting_id", "join_url", "passcode", "zoom_event_id",
        "handoff_url", "status", "manage_token", "cancelled_at", "origin", "company_line", "zoom_error",
        "zoom_reschedule_url", "zoom_cancel_url", "zoom_run", "previous_start_utc", "rescheduled_at", "reminder_sent_at", "schedule_description", "attendees",
        "outcome", "outcome_note", "outcome_at", "outcome_asked_at", "followup"]


def insert(b: dict[str, Any]) -> int:
    with conn() as c:
        row = c.execute(
            """INSERT INTO bookings(lead_id, session_id, name, email, company, notes, schedule_slug, schedule_name, duration_min,
                                    start_utc, end_utc, visitor_tz, method, zoom_meeting_id, join_url, passcode, zoom_event_id,
                                    handoff_url, status, manage_token, origin, company_line, zoom_error,
                                    zoom_reschedule_url, zoom_cancel_url, zoom_run, schedule_description, attendees)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
               RETURNING id""",
            (b.get("lead_id"), b.get("session_id"), b["name"], b["email"], b.get("company") or None, b.get("notes") or None,
             b["schedule_slug"], b.get("schedule_name"), b["duration_min"], b["start_utc"], b["end_utc"], b["visitor_tz"],
             b["method"], b.get("zoom_meeting_id"), b.get("join_url"), b.get("passcode"), b.get("zoom_event_id"),
             b.get("handoff_url"), b["status"], b["manage_token"], b.get("origin") or None, b.get("company_line") or None,
             b.get("zoom_error"), b.get("zoom_reschedule_url"), b.get("zoom_cancel_url"),
             json.dumps(b["zoom_run"], default=str) if b.get("zoom_run") else None, (b.get("schedule_description") or None),
             json.dumps(b.get("attendees") or []))).fetchone()
        c.commit()
    return int(row[0])


def reschedule(booking_id: int, start_utc: datetime, end_utc: datetime, run: dict[str, Any] | None = None,
               join_url: str | None = None, handoff_url: str | None = None, reschedule_url: str | None = None,
               cancel_url: str | None = None, method: str | None = None, status: str | None = None) -> bool:
    """Move an active booking to a new time (keeps the old start in previous_start_utc). Zoom issues a fresh manage link
    on every reschedule, so the new reschedule/cancel links replace the old ones when the worker captured them."""
    with conn() as c:
        n = c.execute(
            """UPDATE bookings SET previous_start_utc = start_utc, start_utc = %s, end_utc = %s, rescheduled_at = now(),
                      zoom_run = COALESCE(%s::jsonb, zoom_run), join_url = COALESCE(%s, join_url), handoff_url = COALESCE(%s, handoff_url),
                      zoom_reschedule_url = COALESCE(%s, zoom_reschedule_url), zoom_cancel_url = COALESCE(%s, zoom_cancel_url),
                      method = COALESCE(%s, method), status = COALESCE(%s, status)
               WHERE id = %s AND status IN ('confirmed', 'pending_zoom')""",
            (start_utc, end_utc, json.dumps(run, default=str) if run else None, join_url, handoff_url, reschedule_url, cancel_url,
             method, status, booking_id)).rowcount
        c.commit()
    return n > 0


def set_zoom_link(booking_id: int, join_url: str, meeting_id: str | None, passcode: str | None) -> bool:
    """The join link read from Zoom's invitation (app/booking/zoom_mail.py); never overwrites a link already stored."""
    with conn() as c:
        n = c.execute(
            """UPDATE bookings SET join_url = %s, zoom_meeting_id = COALESCE(zoom_meeting_id, %s), passcode = COALESCE(passcode, %s)
               WHERE id = %s AND join_url IS NULL""", (join_url, meeting_id, passcode, booking_id)).rowcount
        c.commit()
    return n > 0


def missing_zoom_link(days: int = 3, limit: int = 20) -> list[dict[str, Any]]:
    """Recent, upcoming browser bookings still without a join link."""
    with conn() as c:
        rows = c.execute(
            f"""SELECT {", ".join(COLS)} FROM bookings
                WHERE method = 'browser' AND status = 'confirmed' AND join_url IS NULL AND start_utc > now()
                  AND created_at > now() - make_interval(days => %s)
                ORDER BY created_at DESC LIMIT %s""", (days, limit)).fetchall()
    return [dict(zip(COLS, r)) for r in rows]


def list_for_visitor(visitor_id: str | None, user_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Every booking made in a chat session of this browser (visitor id) or signed-in user: the upcoming active ones first,
    then the rest, each newest start first. Upcoming first so the limit never hides a call they still have behind older,
    moved or cancelled bookings dated later."""
    if not visitor_id and not user_id:
        return []
    cols = ", ".join("b." + c for c in COLS)
    with conn() as c:
        rows = c.execute(
            f"""SELECT {cols} FROM bookings b JOIN sessions s ON s.session_id = b.session_id
                WHERE s.visitor_id = %s::text OR s.user_id = %s::text
                ORDER BY (b.status IN ('confirmed', 'pending_zoom') AND b.start_utc > now()) DESC, b.start_utc DESC LIMIT %s""",
            (visitor_id, user_id, max(1, min(limit, 100)))).fetchall()
    out = []
    for r in rows:
        b = dict(zip(COLS, r))
        b["meeting_id"] = b.get("zoom_meeting_id")
        out.append(b)
    return out


def owned_by_visitor(booking_id: int, visitor_id: str | None, session_id: str | None = None) -> bool:
    """The booking was made in a chat session of this browser (visitor id) or in this very session."""
    if not visitor_id and not session_id:
        return False
    with conn() as c:
        row = c.execute(
            """SELECT 1 FROM bookings b WHERE b.id = %s AND b.session_id IS NOT NULL
               AND (b.session_id = COALESCE(%s::text, '') OR EXISTS (SELECT 1 FROM sessions s WHERE s.session_id = b.session_id
                                                                     AND s.visitor_id = %s::text))""",
            (booking_id, session_id, visitor_id)).fetchone()
    return row is not None


def get(booking_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(f"SELECT {', '.join(COLS)} FROM bookings WHERE id = %s", (booking_id,)).fetchone()
    if not row:
        return None
    b = dict(zip(COLS, row))
    b["meeting_id"] = b.get("zoom_meeting_id")
    return b


def count_active(email: str) -> int:
    with conn() as c:
        row = c.execute("""SELECT count(*) FROM bookings WHERE lower(email) = lower(%s) AND status IN ('confirmed', 'pending_zoom')
                           AND start_utc > now()""", (email,)).fetchone()
    return int(row[0])


def busy_between(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Our own confirmed bookings (Meetings-API or Scheduler) overlapping the window: shown as 'booked' in the grid."""
    with conn() as c:
        rows = c.execute("""SELECT start_utc, end_utc FROM bookings WHERE status = 'confirmed' AND end_utc > %s AND start_utc < %s""",
                         (start, end)).fetchall()
    return [(r[0], r[1]) for r in rows]


def cancel(booking_id: int) -> bool:
    with conn() as c:
        n = c.execute("UPDATE bookings SET status = 'cancelled', cancelled_at = now() WHERE id = %s AND status <> 'cancelled'",
                      (booking_id,)).rowcount
        c.commit()
    return n > 0


def recent(days: int = 30, limit: int = 200) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(f"""SELECT {', '.join(COLS)} FROM bookings WHERE created_at > now() - make_interval(days => %s)
                             ORDER BY created_at DESC LIMIT %s""", (max(1, min(days, 365)), max(1, min(limit, 500)))).fetchall()
    out = []
    for r in rows:
        b = dict(zip(COLS, r))
        b.pop("manage_token", None)
        out.append(b)
    return out


def dumps(b: dict[str, Any]) -> str:
    return json.dumps(b, default=str)
