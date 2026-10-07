"""Full availability for the in-chat picker: every slot of the next N days with its status.

Zoom's endpoints only return the OPEN starts. To show the host's whole day (open and taken), the grid is rebuilt:
the working window and the step come from the open slots themselves (or HOST_HOURS when configured), each
candidate start in that window is marked available when Zoom listed it, otherwise 'booked' (one of our own
confirmed bookings), 'past' (earlier today) or 'unavailable' (taken, blocked, buffer or minimum notice on Zoom's
side). Days without any working hours (weekends) have no grid and show as "Not available".

Everything is converted to the visitor's timezone; results are cached for AVAILABILITY_CACHE_SECONDS (60).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.booking.zoom import AvailabilityError, InvalidTimeError, Schedule, Slot, parse_tz
from app.config import settings

log = logging.getLogger("booking.availability")

DEFAULT_WINDOW = (9 * 60, 18 * 60)  # minutes of the host day when nothing can be inferred
MAX_DAYS = 30

CALL_DESCRIPTIONS = [
    ("discovery", "A short first conversation to see where Deep can help."),
    ("walkthrough", "See LakeB2B's data and workflows applied to your own use case."),
    ("demo", "See LakeB2B's data and workflows applied to your own use case."),
    ("gtm", "A working session on go-to-market: data, AI and revenue acceleration."),
    ("strategy", "A working session on go-to-market: data, AI and revenue acceleration."),
]

_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def describe(schedule: Schedule) -> str:
    hay = f"{schedule.slug} {schedule.name}".lower()
    for key, text in CALL_DESCRIPTIONS:
        if key in hay:
            return text
    return "A call with Deep."


# ---------------------------------------------------------------- pure grid construction
def _parse_hours(text: str) -> tuple[int, int] | None:
    try:
        a, b = text.split("-")
        h1, m1 = (int(x) for x in a.strip().split(":"))
        h2, m2 = (int(x) for x in b.strip().split(":"))
        if 0 <= h1 * 60 + m1 < h2 * 60 + m2 <= 24 * 60:
            return h1 * 60 + m1, h2 * 60 + m2
    except (ValueError, AttributeError):
        pass
    return None


def infer_window(available: list[Slot], host_tz: str, duration: int) -> tuple[int, int, int, set[int]]:
    """(window_start_min, window_end_min, step_min, weekdays) in the HOST zone, from the open slots."""
    z = ZoneInfo(host_tz)
    locals_ = [s.start_utc.astimezone(z) for s in available]
    step = 15 if any(dt.minute % 30 for dt in locals_) else 30
    if duration >= 60 and not any(dt.minute for dt in locals_):
        step = 60
    configured = _parse_hours(settings.host_hours) if settings.host_hours else None
    if configured:
        start, end = configured
    elif locals_:
        mins = [dt.hour * 60 + dt.minute for dt in locals_]
        start = (min(mins) // 60) * 60
        end = min(24 * 60, max(mins) + duration)
        end = ((end + 59) // 60) * 60
    else:
        start, end = DEFAULT_WINDOW
    weekdays = {dt.weekday() for dt in locals_} or ({0, 1, 2, 3, 4} if configured else set())
    return start, end, step, weekdays


def build_days(available: list[Slot], schedule: Schedule, tz: str, now: datetime, days: int,
               busy: list[tuple[datetime, datetime]] | None = None, host_tz: str | None = None) -> list[dict[str, Any]]:
    """Visitor-local days, each with every candidate start and its status."""
    host_tz = host_tz or settings.host_timezone
    hz, vz = ZoneInfo(host_tz), ZoneInfo(tz)
    duration = schedule.duration_min
    open_starts = {s.start_utc for s in available}
    w_start, w_end, step, weekdays = infer_window(available, host_tz, duration)
    busy = busy or []
    end_range = now + timedelta(days=days)

    def is_busy(start_utc: datetime) -> bool:
        end_utc = start_utc + timedelta(minutes=duration)
        return any(b0 < end_utc and start_utc < b1 for b0, b1 in busy)

    entries: dict[date, list[dict[str, Any]]] = {}
    host_day = now.astimezone(hz).date()
    for _ in range(days + 2):  # +2: a visitor far west/east of the host sees parts of neighbouring host days
        if host_day.weekday() in weekdays:
            m = w_start
            while m + duration <= w_end:
                local = datetime(host_day.year, host_day.month, host_day.day, m // 60, m % 60, tzinfo=hz)
                start_utc = local.astimezone(timezone.utc)
                m += step
                if start_utc > end_range:
                    continue  # earlier slots of today stay visible as 'past' so the visitor sees the whole day
                v = start_utc.astimezone(vz)
                if start_utc in open_starts and not is_busy(start_utc):
                    status, reason = True, None
                elif is_busy(start_utc):
                    status, reason = False, "booked"
                elif start_utc < now:
                    status, reason = False, "past"
                else:
                    status, reason = False, "unavailable"
                entries.setdefault(v.date(), []).append({
                    "start_iso": v.isoformat(), "time": v.strftime("%H:%M"),
                    "label_visitor": Slot(start_utc, duration).label(tz), "label_host": Slot(start_utc, duration).label(host_tz),
                    "available": status, "reason": reason,
                })
        host_day += timedelta(days=1)
    # open slots Zoom listed outside the inferred window (rare) must still be offered
    for s in available:
        if now <= s.start_utc <= end_range and not is_busy(s.start_utc):
            v = s.start_utc.astimezone(vz)
            lst = entries.setdefault(v.date(), [])
            if not any(e["start_iso"] == v.isoformat() for e in lst):
                lst.append({"start_iso": v.isoformat(), "time": v.strftime("%H:%M"), "label_visitor": s.label(tz),
                            "label_host": s.label(host_tz), "available": True, "reason": None})

    out = []
    vday = now.astimezone(vz).date()
    for _ in range(days):
        slots = sorted(entries.get(vday, []), key=lambda e: e["start_iso"])
        open_n = sum(1 for e in slots if e["available"])
        out.append({"date": vday.isoformat(), "label": vday.strftime("%a %d %b"), "weekday": vday.strftime("%A"),
                    "open": open_n, "slots": slots})
        vday += timedelta(days=1)
    return out


# ---------------------------------------------------------------- with the service
def availability(service, slug: str, days: int | None, tz: str, busy_fn: Callable[[datetime, datetime], list] | None = None,
                 now: datetime | None = None, use_cache: bool = True) -> dict[str, Any]:
    """{"ok", "schedule", "timezone", "days", "fetched_at", "source"} or {"ok": False, "error", "message", "fallback_link"}."""
    days = max(1, min(int(days or settings.booking_days_ahead), MAX_DAYS))
    try:
        tz = parse_tz(tz)
    except InvalidTimeError:
        tz = settings.host_timezone
    key = (slug.lower(), tz, days)
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < settings.availability_cache_seconds:
            return dict(hit[1], cached=True)
    try:
        schedule = service.schedule_by_slug(slug)
        choices = [{"slug": s.slug, "name": s.name, "duration_min": s.duration_min, "description": describe(s)}
                   for s in service.list_schedules()]
    except AvailabilityError as e:
        log.warning("availability: schedules unavailable: %s", e)
        return {"ok": False, "error": "unavailable", "message": "Deep's scheduler isn't responding right now.",
                "fallback_link": settings.zoom_booking_base}
    if schedule is None:
        return {"ok": False, "error": "unknown_schedule", "choices": choices, "message": "Pick a call type first.",
                "fallback_link": settings.zoom_booking_base}
    now = now or service.now()
    start, end = now, now + timedelta(days=days + 1)
    try:
        slots, source = service._fetch(schedule, start, end, tz)
    except AvailabilityError as e:
        log.warning("availability fetch failed for %s: %s", slug, e)
        return {"ok": False, "error": "unavailable", "message": "Deep's availability couldn't be loaded right now.",
                "schedule": {"slug": schedule.slug, "name": schedule.name, "duration_min": schedule.duration_min},
                "fallback_link": schedule.booking_link or settings.zoom_booking_base}
    busy = []
    if busy_fn is not None:
        try:
            busy = busy_fn(start, end)
        except Exception as e:  # our own bookings table is an overlay, never a blocker
            log.warning("busy lookup failed: %s", e)
    days_out = build_days(slots, schedule, tz, now, days, busy)
    data = {"ok": True, "schedule": {"slug": schedule.slug, "name": schedule.name, "duration_min": schedule.duration_min,
                                     "description": describe(schedule), "booking_link": schedule.booking_link},
            "timezone": tz, "days": days_out, "open_total": sum(d["open"] for d in days_out),
            "fetched_at": datetime.now(timezone.utc).isoformat(), "source": source,
            "fallback_link": schedule.booking_link or settings.zoom_booking_base, "cached": False}
    with _lock:
        _cache[key] = (time.monotonic(), data)
    return data


def open_slots(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for d in data.get("days", []) for s in d["slots"] if s["available"]]


def nearest(data: dict[str, Any], start_utc: datetime, n: int = 3) -> list[dict[str, Any]]:
    """The n open slots closest to a wanted time (for 'Friday 4pm isn't free, how about...')."""
    from dateutil import parser as dtparser

    items = open_slots(data)
    items.sort(key=lambda s: abs((dtparser.isoparse(s["start_iso"]) - start_utc).total_seconds()))
    return items[:n]


def invalidate(slug: str | None = None) -> None:
    with _lock:
        for k in list(_cache):
            if slug is None or k[0] == slug.lower():
                _cache.pop(k, None)
