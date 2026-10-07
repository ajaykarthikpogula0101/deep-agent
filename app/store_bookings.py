"""Postgres side of in-chat bookings (table `bookings`, see app/db.py). Kept apart from the flow so it can be faked."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.db import conn

COLS = ["id", "created_at", "lead_id", "session_id", "name", "email", "company", "notes", "schedule_slug", "schedule_name",
        "duration_min", "start_utc", "end_utc", "visitor_tz", "method", "zoom_meeting_id", "join_url", "passcode", "zoom_event_id",
        "handoff_url", "status", "manage_token", "cancelled_at", "origin", "company_line", "zoom_error"]


def insert(b: dict[str, Any]) -> int:
    with conn() as c:
        row = c.execute(
            """INSERT INTO bookings(lead_id, session_id, name, email, company, notes, schedule_slug, schedule_name, duration_min,
                                    start_utc, end_utc, visitor_tz, method, zoom_meeting_id, join_url, passcode, zoom_event_id,
                                    handoff_url, status, manage_token, origin, company_line, zoom_error)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (b.get("lead_id"), b.get("session_id"), b["name"], b["email"], b.get("company") or None, b.get("notes") or None,
             b["schedule_slug"], b.get("schedule_name"), b["duration_min"], b["start_utc"], b["end_utc"], b["visitor_tz"],
             b["method"], b.get("zoom_meeting_id"), b.get("join_url"), b.get("passcode"), b.get("zoom_event_id"),
             b.get("handoff_url"), b["status"], b["manage_token"], b.get("origin") or None, b.get("company_line") or None,
             b.get("zoom_error"))).fetchone()
        c.commit()
    return int(row[0])


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
