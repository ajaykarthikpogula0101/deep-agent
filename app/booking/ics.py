"""iCalendar invite for a booking: attached to both confirmation emails and served by GET /booking/{id}/ics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets are folded with CRLF + one space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # never split a UTF-8 sequence
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build(b: dict[str, Any], host_name: str = "Deep") -> str:
    """b: booking dict with id, schedule_name, start_utc, end_utc, name, email, join_url, meeting_id, passcode, notes."""
    site = settings.site_base_url.replace("https://", "").replace("http://", "")
    summary = f"{b.get('schedule_name') or 'Call'} — {b.get('name') or 'Visitor'} × {host_name}"
    desc = [f"{b.get('schedule_name') or 'Call'} with {host_name} ({b.get('duration_min')} min)."]
    if b.get("join_url"):
        desc.append(f"Join Zoom: {b['join_url']}")
    meeting_id = b.get("meeting_id") or b.get("zoom_meeting_id")
    if meeting_id:
        desc.append(f"Meeting ID: {meeting_id}" + (f" · Passcode: {b['passcode']}" if b.get("passcode") else ""))
    if b.get("handoff_url") and not b.get("join_url"):
        desc.append(f"Confirm the time on Zoom: {b['handoff_url']}")
    if b.get("notes"):
        desc.append(f"Topic: {b['notes']}")
    desc.append(f"Booked through the {site} assistant.")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{site}//assistant//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:booking-{b.get('id') or 'x'}@{site}",
        f"DTSTAMP:{_utc(datetime.now(timezone.utc))}",
        f"DTSTART:{_utc(b['start_utc'])}",
        f"DTEND:{_utc(b['end_utc'])}",
        f"SUMMARY:{_esc(summary)}",
        f"DESCRIPTION:{_esc(chr(10).join(desc))}",
        f"LOCATION:{_esc(b.get('join_url') or 'Zoom')}",
    ]
    if b.get("join_url"):
        lines.append(f"URL:{b['join_url']}")
    lines += [
        f"ORGANIZER;CN={_esc(host_name)}:mailto:{settings.host_email}",
        f"ATTENDEE;CN={_esc(b.get('name') or '')};ROLE=REQ-PARTICIPANT:mailto:{b.get('email') or ''}",
        "STATUS:CONFIRMED" if b.get("status", "confirmed") != "cancelled" else "STATUS:CANCELLED",
        "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(summary)}", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
