"""The Zoom join link for browser bookings, read from Zoom's own invitation email. No Zoom credentials.

Zoom's public scheduler pages never show the join link (the confirmation page, the manage page and its
/zscheduler/v1/attendees/<id> data all leave the location empty; probed 2026-10-15). The link only travels in the
invitation Zoom sends to every attendee. So the browser worker adds one mailbox of ours as an additional attendee
(ZOOM_LINK_MAILBOX, default SMTP_USER), and this module reads the invitation there over IMAP (the same Gmail app
password as SMTP) and takes the join link, the meeting ID and the passcode from it.

    after_booking(booking, mail)  the confirmation emails wait (on a thread, up to ZOOM_LINK_WAIT_SECONDS) for the link,
                                  then go out with the Join button and the phone row; without it they go out as before
    backfill()                    every 10 minutes: links that arrived late are stored, so reminders carry them

An invitation belongs to a booking when its calendar part starts at the booking's start (one host: one call per time),
or, without a calendar part, when it names the booker's email. Only messages received after the booking was made
count; cancellations never do, and neither do our own emails (the host copy lands in the same mailbox).
"""
from __future__ import annotations

import email
import html
import imaplib
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import unquote

from app.config import settings

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

log = logging.getLogger("booking.zoom_mail")

JOIN_RE = re.compile(r"https://(?:[\w-]+\.)?zoom\.us/j/(\d{9,11})(?:\?pwd=[\w.\-]+)?")
MEETING_ID_RE = re.compile(r"Meeting\s+ID\s*[:：]?\s*(\d{3}\s?\d{3,4}\s?\d{3,4})", re.I)
PASSCODE_RE = re.compile(r"(?:Passcode|Password)\s*[:：]?\s*([A-Za-z0-9@#*!.\-_]{4,12})\b", re.I)
CANCELLED_RE = re.compile(r"^\s*(?:cancel(?:l)?ed|cancellation)\b", re.I)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
POLL_SECONDS = 8


# ---------------------------------------------------------------- settings
def mailbox() -> str:
    return (settings.zoom_link_mailbox or settings.smtp_user or "").strip()


def _password() -> str:
    return settings.zoom_link_imap_password or settings.smtp_password or ""


def enabled() -> bool:
    return bool(settings.zoom_link_from_email and mailbox() and _password() and settings.zoom_link_imap_host)


def extra_attendee(booker_email: str, guests: list[str]) -> list[str]:
    """The mailbox to add on Zoom next to the visitor's own guests (none when it is the booker or a guest already)."""
    box = mailbox()
    if not enabled() or not box:
        return []
    taken = {(booker_email or "").lower(), *(g.lower() for g in guests)}
    return [] if box.lower() in taken else [box]


# ---------------------------------------------------------------- parsing (pure)
def format_meeting_id(digits: str) -> str:
    """Zoom's own grouping: 812 3456 7890 (11 digits), 812 345 6789 (10), 812 345 678 (9)."""
    d = re.sub(r"\D", "", digits or "")
    if len(d) == 11:
        return f"{d[:3]} {d[3:7]} {d[7:]}"
    if len(d) in (9, 10):
        return f"{d[:3]} {d[3:6]} {d[6:]}"
    return d


def _ics_lines(text: str) -> list[str]:
    """Unfolded calendar lines (a line starting with a space continues the previous one)."""
    out: list[str] = []
    for ln in (text or "").replace("\r\n", "\n").split("\n"):
        if ln.startswith((" ", "\t")) and out:
            out[-1] += ln[1:]
        else:
            out.append(ln)
    return out


def _ics_start(lines: list[str]) -> datetime | None:
    """The first VEVENT's DTSTART in UTC: 20261020T140000Z, or local with TZID=<IANA name>."""
    for ln in lines:
        m = re.match(r"DTSTART(;[^:]*)?:(\d{8}T\d{4,6})(Z?)$", ln.strip())
        if not m:
            continue
        stamp = m.group(2).ljust(15, "0")
        dt = datetime.strptime(stamp, "%Y%m%dT%H%M%S")
        if m.group(3):
            return dt.replace(tzinfo=timezone.utc)
        tzid = re.search(r"TZID=\"?([^\";:]+)", m.group(1) or "")
        if tzid and ZoneInfo:
            try:
                return dt.replace(tzinfo=ZoneInfo(tzid.group(1))).astimezone(timezone.utc)
            except Exception:
                return None
        return None
    return None


def parse(raw: bytes) -> dict[str, Any]:
    """{"from", "join_url", "meeting_id", "passcode", "start_utc", "cancelled", "received", "subject", "text"} from one message."""
    m = email.message_from_bytes(raw)
    try:
        subject = str(make_header(decode_header(m.get("Subject") or "")))
    except Exception:
        subject = m.get("Subject") or ""
    try:
        received = parsedate_to_datetime(m.get("Date")) if m.get("Date") else None
        if received and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
    except Exception:
        received = None
    texts: list[str] = []
    start = None
    cancelled = bool(CANCELLED_RE.search(subject))
    for part in m.walk():
        if part.is_multipart():
            continue
        ct = part.get_content_type()
        name = (part.get_filename() or "").lower()
        payload = part.get_payload(decode=True) or b""
        body = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ct in ("text/calendar", "application/ics") or name.endswith(".ics"):
            lines = _ics_lines(body)
            start = start or _ics_start(lines)
            if any(ln.strip().upper() in ("METHOD:CANCEL", "STATUS:CANCELLED") for ln in lines):
                cancelled = True
            texts.append("\n".join(lines).replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";"))
        elif ct == "text/plain":
            texts.append(body)
        elif ct == "text/html":
            t = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S | re.I)
            texts.append(unquote(html.unescape(re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", t, flags=re.I))))
            texts.append(html.unescape(re.sub(r"<[^>]+>", " ", t)))
    text = "\n".join(texts)
    join = JOIN_RE.search(text)
    mid = MEETING_ID_RE.search(text)
    pc = PASSCODE_RE.search(text)
    return {"from": parseaddr(m.get("From") or "")[1].lower(), "join_url": join.group(0) if join else None,
            "meeting_id": format_meeting_id(mid.group(1) if mid else (join.group(1) if join else "")) or None,
            "passcode": pc.group(1) if pc else None, "start_utc": start, "cancelled": cancelled, "received": received,
            "subject": subject, "text": text}


def matches(info: dict[str, Any], booking: dict[str, Any], after: datetime | None = None) -> bool:
    """This invitation is for this booking: a join link, not a cancellation, received after the booking was made, and
    the same start (or, without a calendar part, the booker's email named in it)."""
    if not info.get("join_url") or info.get("cancelled"):
        return False
    ours = {a.strip().lower() for a in (mailbox(), settings.smtp_user, settings.email_from) if a}
    if info.get("from") in ours:  # our own booking emails land in this mailbox too (the host copy) and carry links
        return False
    if after and info.get("received") and info["received"] < after - timedelta(minutes=10):  # Zoom mails while we still store
        return False
    start = booking.get("start_utc")
    if isinstance(start, datetime) and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if info.get("start_utc") is not None:
        return start is not None and abs((info["start_utc"] - start).total_seconds()) < 60
    who = (booking.get("email") or "").lower()
    return bool(who) and who in (info.get("text") or "").lower()


# ---------------------------------------------------------------- the mailbox
def _messages(since: datetime, limit: int = 25) -> list[bytes]:
    """Newest first: messages since that day that carry a Zoom join link, from INBOX, else All Mail (read-only)."""
    day = f"{since.day:02d}-{MONTHS[since.month - 1]}-{since.year}"
    M = imaplib.IMAP4_SSL(settings.zoom_link_imap_host, timeout=20)
    try:
        M.login(mailbox(), _password())
        for folder in ("INBOX", '"[Gmail]/All Mail"'):
            typ, _ = M.select(folder, readonly=True)
            if typ != "OK":
                continue
            typ, data = M.search(None, f'(SINCE {day} BODY "zoom.us/j/")')
            ids = (data[0] or b"").split() if typ == "OK" and data else []
            if not ids:
                continue
            out = []
            for i in reversed(ids[-limit:]):
                typ, msg = M.fetch(i, "(BODY.PEEK[])")
                if typ == "OK" and msg and isinstance(msg[0], tuple):
                    out.append(msg[0][1])
            return out
        return []
    finally:
        try:
            M.logout()
        except Exception:
            pass


def find(booking: dict[str, Any], after: datetime | None = None) -> dict[str, Any] | None:
    """Zoom's invitation for this booking in the mailbox (newest first), or None. Never raises. `after`: when the
    booking was made (default its created_at, else now)."""
    created = after or booking.get("created_at") or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    try:
        for raw in _messages(created - timedelta(days=1)):
            info = parse(raw)
            if matches(info, booking, after=created):
                return info
    except Exception as e:
        log.warning("zoom invitation lookup failed: %s", f"{type(e).__name__}: {e}"[:200])
    return None


def store(booking: dict[str, Any], info: dict[str, Any]) -> None:
    """Onto the booking dict (for the emails about to go out) and its row."""
    booking.update(join_url=info["join_url"], zoom_meeting_id=booking.get("zoom_meeting_id") or info.get("meeting_id"),
                   passcode=booking.get("passcode") or info.get("passcode"))
    booking["meeting_id"] = booking.get("zoom_meeting_id")
    if booking.get("id"):
        from app import store_bookings as sb

        try:
            sb.set_zoom_link(int(booking["id"]), info["join_url"], info.get("meeting_id"), info.get("passcode"))
        except Exception as e:
            log.warning("zoom link store failed: %s", e)


def wait(booking: dict[str, Any], seconds: int | None = None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any] | None:
    deadline = time.monotonic() + (settings.zoom_link_wait_seconds if seconds is None else seconds)
    made = booking.get("created_at") or datetime.now(timezone.utc)
    while True:
        info = find(booking, after=made)
        if info or time.monotonic() >= deadline:
            return info
        sleep(POLL_SECONDS)


def after_booking(booking: dict[str, Any], mail: Callable[[dict], None]) -> bool:
    """Send the booking emails; for a browser booking without a link, first wait for Zoom's invitation on a thread.
    Returns True when the emails were deferred."""
    if booking.get("method") != "browser" or booking.get("join_url") or not enabled():
        mail(booking)
        return False

    def work() -> None:
        t0 = time.monotonic()
        try:
            info = wait(booking)
            if info:
                store(booking, info)
                log.info("zoom link for booking %s found after %.0fs", booking.get("id"), time.monotonic() - t0)
            else:
                log.warning("no zoom invitation for booking %s within %ss; emails go out without the link",
                            booking.get("id"), settings.zoom_link_wait_seconds)
        except Exception as e:  # the emails always go out
            log.error("zoom link wait failed: %s", e)
        mail(booking)

    threading.Thread(target=work, name=f"zoom-link-{booking.get('id')}", daemon=True).start()
    return True


def backfill() -> int:
    """Scheduler job: store links that arrived after the confirmation emails went out. Returns how many were found."""
    if not enabled():
        return 0
    from app import store_bookings as sb

    n = 0
    for b in sb.missing_zoom_link():
        info = find(b)
        if info:
            store(b, info)
            n += 1
    if n:
        log.info("zoom links backfilled: %s", n)
    return n
