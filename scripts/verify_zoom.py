"""One-shot check of the Zoom Server-to-Server credentials and the Scheduler API on this account.

Run after filling ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET in .env:

    python scripts/verify_zoom.py

It reports, in order:
  1. OAuth token                      -> credentials are right
  2. GET /scheduler/schedules         -> licence + scopes are right, and the three call types are visible
  3. GET .../available_times          -> which query-parameter names the endpoint accepts (writes the answer)
  4. Public fallback for comparison   -> same slots from the unauthenticated endpoint
It never creates a booking.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.booking.zoom import (  # noqa: E402
    ZOOM_API,
    AvailabilityError,
    ZoomOfficialClient,
    ZoomPublicClient,
    normalize_available,
    normalize_schedules,
)
from app.config import settings  # noqa: E402

PARAM_VARIANTS = [
    ("from", "to", "time_zone"),
    ("from", "to", "timezone"),
    ("start_time", "end_time", "time_zone"),
    ("time_min", "time_max", "time_zone"),
    ("start_date", "end_date", "time_zone"),
    ("timeMin", "timeMax", "timeZone"),
]


def main() -> int:
    if not settings.zoom_api_configured:
        print("ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET are not all set in .env")
        return 2
    client = ZoomOfficialClient(httpx.Client(timeout=15))

    print("1. OAuth token ...", end=" ")
    try:
        client._access_token()
        print("OK")
    except AvailabilityError as e:
        print("FAILED:", e)
        print("   -> check account id / client id / secret, and that the app is activated.")
        return 1

    print("2. GET /scheduler/schedules ...", end=" ")
    try:
        raw = client._get("/scheduler/schedules", {"page_size": 50})
        scheds = normalize_schedules(raw, settings.zoom_booking_base)
        print("OK")
        for s in scheds:
            print(f"   - {s.slug}: {s.name} ({s.duration_min} min) id={s.id}")
    except AvailabilityError as e:
        print("FAILED:", e)
        if "license" in str(e).lower():
            print("   -> this is the known 'Invalid license type' problem. The bot keeps using the public fallback.")
            print("      Ask Zoom support to enable Scheduler API access for the account (quote devforum thread 145888).")
        else:
            print("   -> add the scopes scheduler:read:admin (and scheduler:write:admin for API booking) and re-activate the app.")
        return 1

    print("3. GET /scheduler/schedules/{id}/available_times, trying parameter names ...")
    s = scheds[0]
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=7)
    found = None
    for p_from, p_to, p_tz in PARAM_VARIANTS:
        try:
            r = client.http.get(f"{ZOOM_API}/scheduler/schedules/{s.id}/available_times",
                                params={p_from: start.strftime("%Y-%m-%dT%H:%M:%SZ"), p_to: end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        p_tz: settings.host_timezone},
                                headers={"Authorization": f"Bearer {client._access_token()}"})
        except httpx.HTTPError as e:
            print(f"   {p_from}/{p_to}/{p_tz}: network error {e.__class__.__name__}")
            continue
        ok = r.status_code == 200 and "days" in r.text
        print(f"   {p_from}/{p_to}/{p_tz}: {r.status_code}" + ("" if ok else f" {r.text[:120]}"))
        if ok:
            found = (p_from, p_to, p_tz)
            try:
                slots = normalize_available(r.json(), s.duration_min)
                print(f"   -> {len(slots)} available slots in the next 7 days; first: {slots[0].label(settings.host_timezone) if slots else '-'}")
            except AvailabilityError as e:
                print("   -> response parsed with a warning:", e)
            break
    if found:
        print(f"   WRITE THESE TO .env:\n   ZOOM_AVAIL_PARAM_FROM={found[0]}\n   ZOOM_AVAIL_PARAM_TO={found[1]}\n   ZOOM_AVAIL_PARAM_TZ={found[2]}")
    else:
        print("   none of the guesses worked; open the endpoint in the Zoom API reference and copy the parameter names.")

    print("4. Public fallback for comparison ...", end=" ")
    try:
        pub = ZoomPublicClient(httpx.Client(timeout=15))
        pslots = pub.available(s, start, end, settings.host_timezone)
        print(f"OK, {len(pslots)} available slots; first: {pslots[0].label(settings.host_timezone) if pslots else '-'}")
    except AvailabilityError as e:
        print("FAILED:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
