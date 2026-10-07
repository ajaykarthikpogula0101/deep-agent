"""The booking tools the agent may call, with every failure path defined.

list_schedules()                                   -> the host's live call types (cached 10 min)
get_available_slots(schedule_slug, days_ahead, tz) -> 3 slots (visitor waking hours, distinct days)
book_slot(schedule_slug, start, name, email, reason, tz) -> re-checks availability, saves the lead,
emails the host brief, then either books through the API or hands off to the Zoom page with prefilled fields.

The lead is saved and the host brief is sent BEFORE the hand-off, so a visitor who drops off is not lost.
Storage and mail are injectable so the whole module is testable without Postgres or SMTP.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlencode

from app.booking.zoom import (
    AvailabilityClient,
    AvailabilityError,
    InvalidTimeError,
    Schedule,
    Slot,
    SlotTakenError,
    ZoomOfficialClient,
    default_clients,
    parse_start,
    parse_tz,
)
from app.config import settings
from app.enrich import summary as company_summary

log = logging.getLogger("booking.service")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Values a model reaches for when it has not actually been told anything. Never accept them as a lead.
_PLACEHOLDER_NAMES = {"visitor", "guest", "user", "unknown", "n/a", "na", "none", "anonymous", "name", "your name",
                      "first last", "john doe", "jane doe", "test", "test user"}
_PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "email.com", "test.com", "domain.com", "mail.com"}
_PLACEHOLDER_LOCALPARTS = {"visitor", "guest", "user", "name", "email", "test", "noreply", "no-reply", "unknown", "anonymous"}


def looks_like_placeholder(name: str, email: str) -> bool:
    local, _, domain = email.lower().partition("@")
    return (name.strip().lower() in _PLACEHOLDER_NAMES or domain in _PLACEHOLDER_DOMAINS
            or local in _PLACEHOLDER_LOCALPARTS)
MAX_DAYS_AHEAD = 30
SCHEDULE_CACHE_SECONDS = 600
WAKING_HOURS = range(8, 20)  # visitor-local hours we prefer to offer


@dataclass
class SlotView:
    start_iso: str  # ISO with offset, in the visitor's zone
    label_visitor: str
    label_host: str
    duration_min: int


@dataclass
class ScheduleView:
    slug: str
    name: str
    duration_min: int
    booking_link: str


@dataclass
class SlotsResult:
    ok: bool
    schedule: ScheduleView | None = None
    slots: list[SlotView] = field(default_factory=list)
    source: str | None = None
    error: str | None = None  # 'no_slots' | 'unavailable' | 'unknown_schedule'
    choices: list[ScheduleView] = field(default_factory=list)
    fallback_link: str = settings.zoom_booking_base


@dataclass
class BookingResult:
    status: str  # 'booked' | 'handoff' | 'slot_taken' | 'unavailable' | 'invalid'
    message: str
    schedule: ScheduleView | None = None
    handoff_url: str | None = None
    brief_sent: bool = False
    visitor_mailed: bool = False  # "Thank you for booking with {brand}" went to the visitor
    lead_id: int | None = None
    slot: SlotView | None = None


StoreLead = Callable[[dict], int]
SendBrief = Callable[[dict], bool]


def _view(slot: Slot, visitor_tz: str) -> SlotView:
    return SlotView(
        start_iso=slot.in_tz(visitor_tz).isoformat(),
        label_visitor=slot.label(visitor_tz),
        label_host=slot.label(settings.host_timezone),
        duration_min=slot.duration_min,
    )


def _sview(s: Schedule) -> ScheduleView:
    return ScheduleView(slug=s.slug, name=s.name, duration_min=s.duration_min, booking_link=s.booking_link)


def pick_three(slots: list[Slot], visitor_tz: str = "UTC") -> list[Slot]:
    """Up to three slots: prefer visitor-local waking hours, then distinct days, then earliest.
    A New York visitor should not be offered 02:30 when 08:00 the same day is free."""
    daytime = [s for s in slots if s.in_tz(visitor_tz).hour in WAKING_HOURS]
    chosen: list[Slot] = []
    seen_days: set[str] = set()
    for pool in (daytime, slots):
        for s in pool:
            if s in chosen:
                continue
            d = s.in_tz(visitor_tz).date().isoformat()
            if d not in seen_days:
                chosen.append(s)
                seen_days.add(d)
            if len(chosen) == 3:
                return chosen
        for s in pool:  # same-day fill from this pool before falling back to the next
            if s not in chosen:
                chosen.append(s)
            if len(chosen) == 3:
                return chosen
    return chosen


class BookingService:
    def __init__(
        self,
        clients: list[AvailabilityClient] | None = None,
        store_lead: StoreLead | None = None,
        send_brief: SendBrief | None = None,
        now: Callable[[], datetime] | None = None,
        send_visitor: SendBrief | None = None,
        enrich: Callable[[str], dict] | None = None,
    ):
        self.clients = clients if clients is not None else default_clients()
        self.store_lead = store_lead or _default_store_lead
        self.send_brief = send_brief or _default_send_brief
        self.send_visitor = send_visitor or _default_send_visitor
        self.enrich = enrich or _default_enrich  # email domain -> company (app/enrich.py)
        self._last_lead: dict | None = None
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.session_id: str | None = None  # set per request by chat.respond()
        self._schedules: list[Schedule] = []
        self._schedules_at: float = 0

    # ------------------------------------------------------------ schedules
    def list_schedules(self) -> list[Schedule]:
        if self._schedules and time.monotonic() - self._schedules_at < SCHEDULE_CACHE_SECONDS:
            return self._schedules
        errors: list[str] = []
        for c in self.clients:
            try:
                self._schedules = c.list_schedules()
                self._schedules_at = time.monotonic()
                return self._schedules
            except AvailabilityError as e:
                errors.append(f"{c.name}: {e}")
                log.warning("list_schedules failed: %s", errors[-1])
        if self._schedules:  # stale cache beats nothing
            return self._schedules
        raise AvailabilityError("; ".join(errors) or "no availability clients configured")

    def schedule_by_slug(self, slug: str) -> Schedule | None:
        slug = (slug or "").strip().lower()
        for s in self.list_schedules():
            if s.slug.lower() == slug:
                return s
        return None

    # ------------------------------------------------------------ availability
    def _fetch(self, schedule: Schedule, start_utc: datetime, end_utc: datetime, tz: str) -> tuple[list[Slot], str]:
        errors: list[str] = []
        for c in self.clients:
            try:
                return c.available(schedule, start_utc, end_utc, tz), c.name
            except AvailabilityError as e:
                errors.append(f"{c.name}: {e}")
                log.warning("availability client failed: %s", errors[-1])
        raise AvailabilityError("; ".join(errors) or "no availability clients configured")

    def get_available_slots(self, schedule_slug: str, days_ahead: int, visitor_tz: str) -> SlotsResult:
        try:
            tz = parse_tz(visitor_tz)
        except InvalidTimeError:
            tz = settings.host_timezone  # show host time rather than nothing; the UI labels the zone
        try:
            schedule = self.schedule_by_slug(schedule_slug)
            choices = [_sview(s) for s in self.list_schedules()]
        except AvailabilityError:
            return SlotsResult(ok=False, error="unavailable")
        if schedule is None:
            return SlotsResult(ok=False, error="unknown_schedule", choices=choices)
        days_ahead = max(1, min(int(days_ahead or 7), MAX_DAYS_AHEAD))
        start = self.now()
        end = start + timedelta(days=days_ahead)
        try:
            slots, source = self._fetch(schedule, start, end, tz)
        except AvailabilityError:
            return SlotsResult(ok=False, error="unavailable", schedule=_sview(schedule), fallback_link=schedule.booking_link)
        slots = [s for s in slots if s.start_utc > start + timedelta(minutes=30)]  # no 'right now' slots
        if not slots:
            return SlotsResult(ok=False, error="no_slots", schedule=_sview(schedule), source=source,
                               fallback_link=schedule.booking_link)
        return SlotsResult(ok=True, schedule=_sview(schedule), slots=[_view(s, tz) for s in pick_three(slots, tz)],
                           source=source, fallback_link=schedule.booking_link)

    # ------------------------------------------------------------ booking
    def book_slot(self, schedule_slug: str, start: str, name: str, email: str, reason: str, visitor_tz: str) -> BookingResult:
        # 1. validate inputs (never trust the model's arguments)
        name, email, reason = (name or "").strip()[:120], (email or "").strip()[:200], (reason or "").strip()[:1000]
        if not name or not _EMAIL_RE.match(email) or not reason:
            return BookingResult(status="invalid", message="I need a name, a valid email and a short reason before booking.")
        if looks_like_placeholder(name, email):
            return BookingResult(status="invalid", message="Those look like placeholder details. Ask the visitor for their "
                                                           "real name and email before booking; do not guess them.")
        try:
            tz = parse_tz(visitor_tz)
            start_utc = parse_start(start)
        except InvalidTimeError as e:
            return BookingResult(status="invalid", message=f"I couldn't pin down that time ({e}). Please pick one of the listed slots.")
        if start_utc < self.now():
            return BookingResult(status="invalid", message="That time is in the past. Please pick one of the listed slots.")
        try:
            schedule = self.schedule_by_slug(schedule_slug)
        except AvailabilityError:
            schedule = None
        if schedule is None:
            url = self._handoff_url(settings.zoom_booking_base, name, email, start_utc)
            lead_id, sent = self._save_and_brief(None, name, email, reason, start_utc, tz, status="enquiry",
                                                 note=f"unknown or unavailable schedule {schedule_slug!r}", handoff_url=url)
            return BookingResult(status="unavailable", lead_id=lead_id, brief_sent=sent, handoff_url=url,
                                 visitor_mailed=self._mail_visitor("enquiry"),
                                 message="I couldn't load that call type right now. I've sent Deep your details; "
                                         "you can also pick a time directly here: ")

        # 2. re-check availability right before confirming
        url = self._handoff_url(schedule.booking_link, name, email, start_utc)
        try:
            slots, source = self._fetch(schedule, start_utc - timedelta(hours=1), start_utc + timedelta(hours=1), tz)
        except AvailabilityError:
            lead_id, sent = self._save_and_brief(schedule, name, email, reason, start_utc, tz, status="enquiry",
                                                 note="scheduler unavailable at confirm time", handoff_url=url)
            return BookingResult(
                status="unavailable", schedule=_sview(schedule), lead_id=lead_id, brief_sent=sent, handoff_url=url,
                visitor_mailed=self._mail_visitor("enquiry"),
                message="Zoom's scheduler isn't responding right now. I've sent Deep your details and the time you wanted; "
                        "you can also book directly here: ",
            )
        match = next((s for s in slots if s.start_utc == start_utc), None)
        if match is None:
            return BookingResult(status="slot_taken", schedule=_sview(schedule),
                                 message="That slot was just taken. Let me fetch fresh times for you.")

        # 3. save the lead + host brief BEFORE any hand-off
        lead_id, sent = self._save_and_brief(schedule, name, email, reason, start_utc, tz, status="handoff", handoff_url=url)
        view = _view(match, tz)

        # 4. confirm: API booking if enabled and the official client is present, else hand-off
        official = next((c for c in self.clients if isinstance(c, ZoomOfficialClient)), None)
        if settings.zoom_enable_api_booking and official is not None:
            first, _, last = name.partition(" ")
            try:
                official.create_booking(schedule, start_utc, first, last, email, reason)
                return BookingResult(status="booked", schedule=_sview(schedule), lead_id=lead_id, brief_sent=sent, slot=view,
                                     visitor_mailed=self._mail_visitor("booked"),
                                     message=f"Booked: {schedule.name}, {view.label_visitor}. A Zoom confirmation is on its way to {email}.")
            except SlotTakenError:
                return BookingResult(status="slot_taken", schedule=_sview(schedule), lead_id=lead_id, brief_sent=sent,
                                     message="That slot was just taken. Let me fetch fresh times for you.")
            except AvailabilityError as e:
                log.warning("api booking failed, falling back to handoff: %s", e)
        return BookingResult(
            status="handoff", schedule=_sview(schedule), lead_id=lead_id, brief_sent=sent, slot=view, handoff_url=url,
            visitor_mailed=self._mail_visitor("handoff"),
            message=f"Great, {view.label_visitor} is still free for the {schedule.name}. "
                    f"Confirm it on Zoom (your details are prefilled): ",
        )

    # ------------------------------------------------------------ helpers
    def _save_and_brief(self, schedule, name, email, reason, start_utc, tz, status, note: str = "",
                        handoff_url: str | None = None) -> tuple[int | None, bool]:
        lead = {"name": name, "email": email, "reason": reason, "slot_start": start_utc, "visitor_tz": tz,
                "status": status, "note": note,
                "schedule": schedule.name if schedule else "-", "schedule_slug": schedule.slug if schedule else None,
                "duration_min": schedule.duration_min if schedule else None, "handoff_url": handoff_url,
                "slot_label_host": Slot(start_utc, 0).label(settings.host_timezone),
                "slot_label_visitor": Slot(start_utc, 0).label(tz),
                "session_id": self.session_id, "origin": _origin_line(self.session_id)}
        try:  # which company is this? bounded lookup, never blocks the booking for long
            data = self.enrich(email) or {}
        except Exception as e:
            log.warning("enrichment failed: %s", e)
            data = {}
        lead["enrichment"], lead["company"] = data, company_summary(data)
        self._last_lead = lead
        lead_id = None
        try:
            lead_id = self.store_lead(lead)
        except Exception as e:  # storage must never block the visitor
            log.error("lead store failed: %s", e)
        sent = False
        try:
            sent = bool(self.send_brief(lead))
        except Exception as e:
            log.error("host brief failed: %s", e)
        return lead_id, sent

    def _mail_visitor(self, status: str) -> bool:
        """'Thank you for booking with {brand}' to the visitor, with the final outcome. Never blocks the visitor."""
        if not self._last_lead:
            return False
        lead = dict(self._last_lead, status=status)
        try:
            return bool(self.send_visitor(lead))
        except Exception as e:
            log.error("visitor confirmation failed: %s", e)
            return False

    @staticmethod
    def _handoff_url(booking_link: str, name: str, email: str, start_utc: datetime) -> str:
        """Zoom booking link with documented prefill params (firstname, lastname, email, month, utm_*).
        Zoom has no documented param to preselect a specific time, so the chat shows the chosen time
        alongside the link and the host brief already carries it."""
        first, _, last = name.partition(" ")
        q = {"firstname": first, "lastname": last, "email": email,
             "month": start_utc.astimezone(timezone.utc).strftime("%Y-%m"),
             "utm_source": "deependhq-assistant", "utm_medium": "chat"}
        return f"{booking_link}?{urlencode({k: v for k, v in q.items() if v})}"


def _origin_line(session_id: str | None) -> str:
    """Where the visitor came from, for the host brief. Empty when tracking is off or nothing is known."""
    try:
        from app.tracking import describe_session

        return describe_session(session_id)
    except Exception:  # tracking is optional; a lead is never lost over it
        return ""


# ---------------------------------------------------------------- default side effects (DB + SMTP)
def _default_store_lead(lead: dict) -> int:
    from app.db import conn, log_event
    from app.tracking import attach_lead

    with conn() as c:
        row = c.execute(
            """INSERT INTO leads(name, email, reason, slot_start, visitor_tz, status, schedule_slug, session_id, company, enrichment)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id""",
            (lead["name"], lead["email"], lead["reason"], lead["slot_start"], lead["visitor_tz"], lead["status"],
             lead.get("schedule_slug"), lead.get("session_id"), lead.get("company") or None,
             json.dumps(lead.get("enrichment") or {}, default=str)),
        ).fetchone()
        c.commit()
    attach_lead(lead.get("session_id"), int(row[0]))
    log_event("handoff" if lead["status"] == "handoff" else "lead", lead.get("session_id"),
              {"lead_id": row[0], "status": lead["status"], "slot": str(lead["slot_start"]),
               "schedule": lead.get("schedule_slug"), "note": lead.get("note"), "origin": lead.get("origin")})
    return int(row[0])


def _default_enrich(email: str) -> dict:
    from app.enrich import lookup

    return lookup(email)


def _default_send_visitor(lead: dict) -> bool:
    from app.booking.email import send_visitor_confirmation

    return send_visitor_confirmation(lead)


def _default_send_brief(lead: dict) -> bool:
    from app.booking.email import send_host_brief

    ok = send_host_brief(lead)
    if ok:
        try:
            from app.db import conn

            with conn() as c:
                c.execute("UPDATE leads SET brief_sent = true WHERE email = %s AND slot_start = %s",
                          (lead["email"], lead["slot_start"]))
                c.commit()
        except Exception as e:  # pragma: no cover
            log.error("brief_sent flag update failed: %s", e)
    return ok
