"""Zoom Scheduler schedules, availability and booking.

Two clients behind one interface:

* ZoomOfficialClient  – Zoom REST API v2 with a Server-to-Server OAuth app.
    GET  /scheduler/schedules                                 (list the host's booking schedules)
    GET  /scheduler/schedules/{scheduleId}/available_times    (added 2026-07-13)
    POST /scheduler/attendee                                  (create booking for a schedule slot)
  Preferred. Known risk: some accounts get 401 "Invalid license type" on Scheduler endpoints even
  with the licence + scopes in place (devforum thread 145888, Aug 2026). The query-parameter names
  for available_times are configurable because the SPA reference could not be fetched headlessly;
  run scripts/verify_zoom.py once with credentials to pin them down.

* ZoomPublicClient    – the unauthenticated endpoints the public booking page itself calls:
    GET https://scheduler.zoom.us/zscheduler/v1/appointments?user=<handle>
    GET https://scheduler.zoom.us/zscheduler/v1/appointments/{slug}/availableTimes
        ?user=<handle>&timeZone=<IANA>&timeMin=<ISO Z>&timeMax=<ISO Z>
  Verified working against scheduler.zoom.us/sreedeep on 2026-10-05. Undocumented: Zoom staff pointed
  a developer at it in Jan 2025, but it can change or start requiring auth without notice. It is the
  fallback, never the primary.

Both are normalised to Schedule objects and lists of timezone-aware UTC datetimes of *available* starts.
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from dateutil import parser as dtparser

from app.config import settings

log = logging.getLogger("booking.zoom")

ZOOM_API = "https://api.zoom.us/v2"
ZOOM_OAUTH = "https://zoom.us/oauth/token"
ZOOM_PUBLIC = "https://scheduler.zoom.us/zscheduler/v1"
HTTP_TIMEOUT = httpx.Timeout(8.0)


class AvailabilityError(Exception):
    """Scheduler unreachable, timed out, or returned something we don't understand."""


class SlotTakenError(Exception):
    """The requested start is no longer in the available list."""


class NoSlotsError(Exception):
    """Zero available spots in the window."""


class InvalidTimeError(Exception):
    """Naive / unparsable start time, or unknown timezone."""


@dataclass(frozen=True)
class Schedule:
    slug: str
    id: str
    name: str
    duration_min: int
    booking_link: str


@dataclass(frozen=True)
class Slot:
    start_utc: datetime  # aware, UTC
    duration_min: int

    @property
    def end_utc(self) -> datetime:
        return self.start_utc + timedelta(minutes=self.duration_min)

    def in_tz(self, tz: str) -> datetime:
        return self.start_utc.astimezone(ZoneInfo(tz))

    def label(self, tz: str) -> str:
        local = self.in_tz(tz)
        return local.strftime("%a %d %b, %H:%M") + f" ({tz})"


# ---------------------------------------------------------------- helpers
def parse_tz(tz: str | None) -> str:
    """Validate an IANA zone. Raises InvalidTimeError rather than silently assuming UTC."""
    if not tz:
        raise InvalidTimeError("missing timezone")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidTimeError(f"unknown timezone: {tz}")
    return tz


def parse_start(start: str) -> datetime:
    """ISO 8601 with an offset -> aware UTC. Naive strings are rejected (timezone mismatch guard)."""
    try:
        dt = dtparser.isoparse(start)
    except (ValueError, TypeError):
        raise InvalidTimeError(f"unparsable start time: {start!r}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise InvalidTimeError("start time has no timezone offset; restate it with an offset or zone")
    return dt.astimezone(timezone.utc)


def normalize_available(payload: dict, duration_fallback: int) -> list[Slot]:
    """Accepts the shape both endpoints use: {duration, days:[{date, spots:[{startTime,status}]}]}.
    Tolerates snake_case variants. Anything else -> AvailabilityError('schema changed')."""
    if not isinstance(payload, dict) or "days" not in payload:
        raise AvailabilityError("availability response schema changed: no 'days' key")
    duration = int(payload.get("duration") or payload.get("duration_minutes") or duration_fallback)
    slots: list[Slot] = []
    for day in payload["days"] or []:
        spots = day.get("spots") or day.get("available_spots") or []
        for sp in spots:
            status = (sp.get("status") or ("available" if sp.get("available", True) else "unavailable")).lower()
            if status != "available":
                continue
            raw = sp.get("startTime") or sp.get("start_time") or sp.get("start")
            if not raw:
                raise AvailabilityError("availability response schema changed: spot without start time")
            try:
                dt = dtparser.isoparse(raw)
            except ValueError:
                raise AvailabilityError(f"availability response schema changed: bad time {raw!r}")
            if dt.tzinfo is None:
                raise AvailabilityError("availability response schema changed: naive spot time")
            slots.append(Slot(start_utc=dt.astimezone(timezone.utc), duration_min=duration))
    slots.sort(key=lambda s: s.start_utc)
    return slots


def normalize_schedules(payload: dict, booking_base: str) -> list[Schedule]:
    """Both endpoints return a list of schedule objects under 'items' or 'schedules'; field names vary."""
    items = payload.get("items") or payload.get("schedules") or []
    if not isinstance(items, list):
        raise AvailabilityError("schedule list schema changed")
    out: list[Schedule] = []
    for it in items:
        if it.get("active") is False or str(it.get("status", "")).lower() in ("inactive", "disabled"):
            continue
        slug = it.get("slug") or ""
        sid = it.get("id") or it.get("schedule_id") or ""
        name = it.get("summary") or it.get("name") or it.get("title") or slug
        duration = int(it.get("duration") or it.get("duration_minutes") or 0)
        link = it.get("bookingLink") or it.get("booking_link") or (f"{booking_base}/{slug}" if slug else "")
        if slug and sid and duration:
            out.append(Schedule(slug=slug, id=sid, name=name, duration_min=duration, booking_link=link))
    if not out:
        raise AvailabilityError("schedule list empty or schema changed")
    return out


# ---------------------------------------------------------------- interface
class AvailabilityClient(Protocol):
    name: str

    def list_schedules(self) -> list[Schedule]: ...

    def available(self, schedule: Schedule, start_utc: datetime, end_utc: datetime, tz: str) -> list[Slot]: ...


# ---------------------------------------------------------------- official API
class ZoomOfficialClient:
    name = "zoom-official"

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=HTTP_TIMEOUT)
        self._token: str | None = None
        self._token_exp: float = 0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        basic = base64.b64encode(f"{settings.zoom_client_id}:{settings.zoom_client_secret}".encode()).decode()
        r = self.http.post(
            ZOOM_OAUTH,
            params={"grant_type": "account_credentials", "account_id": settings.zoom_account_id},
            headers={"Authorization": f"Basic {basic}"},
        )
        if r.status_code != 200:
            raise AvailabilityError(f"zoom oauth failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, params: dict) -> dict:
        try:
            r = self.http.get(f"{ZOOM_API}{path}", params=params,
                              headers={"Authorization": f"Bearer {self._access_token()}"})
        except httpx.HTTPError as e:
            raise AvailabilityError(f"zoom api unreachable: {e.__class__.__name__}") from e
        if r.status_code == 401 and "license" in r.text.lower():
            raise AvailabilityError("zoom api: invalid license type for Scheduler endpoints")
        if r.status_code != 200:
            raise AvailabilityError(f"zoom api {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise AvailabilityError("zoom api returned non-JSON")

    def list_schedules(self) -> list[Schedule]:
        payload = self._get("/scheduler/schedules", {"page_size": 50})
        return normalize_schedules(payload, settings.zoom_booking_base)

    def available(self, schedule: Schedule, start_utc: datetime, end_utc: datetime, tz: str) -> list[Slot]:
        payload = self._get(
            f"/scheduler/schedules/{schedule.id}/available_times",
            {
                settings.zoom_avail_param_from: start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                settings.zoom_avail_param_to: end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                settings.zoom_avail_param_tz: tz,
            },
        )
        return normalize_available(payload, duration_fallback=schedule.duration_min)

    def create_booking(self, schedule: Schedule, start_utc: datetime, first: str, last: str, email: str, reason: str,
                       tz: str = "UTC") -> dict:
        """POST /scheduler/attendee (scope scheduler:write:scheduled_event:admin). Body per the Zoom reference, 2026-10:
        schedule_id, start_date_time, duration, booker{email, first_name, last_name}, location_configuration{kind},
        time_zone. `reason` is not sent: question fields are schedule-specific and reject unknown names
        (devforum 144729); it goes into the host email instead. Verify once with real credentials (docs/BOOKING.md)."""
        body = {
            "schedule_id": schedule.id,
            "start_date_time": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": schedule.duration_min,
            "booker": {"first_name": first, "last_name": last or "-", "email": email},
            "location_configuration": {"kind": "zoomMeeting"},
            "time_zone": tz,
        }
        try:
            r = self.http.post(f"{ZOOM_API}/scheduler/attendee", json=body,
                               headers={"Authorization": f"Bearer {self._access_token()}"})
        except httpx.HTTPError as e:
            raise AvailabilityError(f"zoom api unreachable: {e.__class__.__name__}") from e
        if r.status_code in (409, 400) and any(w in r.text.lower() for w in ("not available", "unavailable", "conflict", "taken")):
            raise SlotTakenError(r.text[:200])
        if r.status_code >= 300:
            raise AvailabilityError(f"zoom booking failed {r.status_code}: {r.text[:200]}")
        return r.json()

    def create_meeting(self, host_user_id: str, topic: str, start_utc: datetime, duration_min: int, agenda: str,
                       invitee_email: str) -> dict:
        """POST /users/{userId}/meetings (scope meeting:write:meeting:admin): the fallback when the Scheduler API cannot
        book. Returns Zoom's meeting object (id, join_url, password, start_url)."""
        body = {
            "topic": topic[:200], "type": 2, "start_time": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "timezone": "UTC",
            "duration": duration_min, "agenda": (agenda or "")[:2000],
            "settings": {"join_before_host": False, "waiting_room": True, "approval_type": 2, "email_notification": True,
                         "meeting_invitees": [{"email": invitee_email}]},
        }
        try:
            r = self.http.post(f"{ZOOM_API}/users/{host_user_id}/meetings", json=body,
                               headers={"Authorization": f"Bearer {self._access_token()}"})
        except httpx.HTTPError as e:
            raise AvailabilityError(f"zoom api unreachable: {e.__class__.__name__}") from e
        if r.status_code >= 300:
            raise AvailabilityError(f"zoom meetings api {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise AvailabilityError("zoom meetings api returned non-JSON")

    def delete_meeting(self, meeting_id: str) -> bool:
        """DELETE /meetings/{meetingId} (scope meeting:delete:meeting:admin). A missing meeting counts as deleted."""
        try:
            r = self.http.delete(f"{ZOOM_API}/meetings/{meeting_id}", params={"schedule_for_reminder": "true"},
                                 headers={"Authorization": f"Bearer {self._access_token()}"})
        except httpx.HTTPError as e:
            raise AvailabilityError(f"zoom api unreachable: {e.__class__.__name__}") from e
        if r.status_code in (200, 204, 404):
            return True
        raise AvailabilityError(f"zoom delete meeting {r.status_code}: {r.text[:200]}")


# ---------------------------------------------------------------- public fallback
class ZoomPublicClient:
    name = "zoom-public-fallback"

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=HTTP_TIMEOUT)

    def _get(self, path: str, params: dict) -> dict:
        try:
            r = self.http.get(f"{ZOOM_PUBLIC}{path}", params=params)
        except httpx.HTTPError as e:
            raise AvailabilityError(f"zoom public endpoint unreachable: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise AvailabilityError(f"zoom public endpoint {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise AvailabilityError("zoom public endpoint returned non-JSON (page changed?)")

    def list_schedules(self) -> list[Schedule]:
        payload = self._get("/appointments", {"user": settings.zoom_booking_user})
        return normalize_schedules(payload, settings.zoom_booking_base)

    def available(self, schedule: Schedule, start_utc: datetime, end_utc: datetime, tz: str) -> list[Slot]:
        payload = self._get(
            f"/appointments/{schedule.slug}/availableTimes",
            {
                "user": settings.zoom_booking_user,
                "timeZone": tz,
                "timeMin": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timeMax": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        return normalize_available(payload, duration_fallback=schedule.duration_min)


def default_clients() -> list[AvailabilityClient]:
    clients: list[AvailabilityClient] = []
    if settings.zoom_api_configured:
        clients.append(ZoomOfficialClient())
    clients.append(ZoomPublicClient())
    return clients
