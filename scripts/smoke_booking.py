"""End-to-end booking flow against YOUR Zoom schedule, without the chat model and without Postgres.

    python scripts/smoke_booking.py                 # list call types, show 3 slots for each
    python scripts/smoke_booking.py book <slug>     # pick the first slot, email the brief, print the hand-off link

The 'book' step does exactly what the chatbot does when a visitor confirms: re-check the slot, save the lead
(printed here instead of Postgres), email the host brief to HOST_EMAIL, and return the prefilled Zoom link.
Open that link in a browser to finish the booking on Zoom, which is the hand-off the visitor would see.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.booking.email import send_host_brief  # noqa: E402
from app.booking.service import BookingService  # noqa: E402
from app.booking.zoom import AvailabilityError  # noqa: E402
from app.config import settings  # noqa: E402

VISITOR_TZ = "America/New_York"  # pretend the visitor is in New York so the timezone shift is visible


def print_lead(lead: dict) -> int:
    print("  LEAD (would be stored):", {k: str(v) for k, v in lead.items()})
    return 1


def main(argv: list[str]) -> int:
    if settings.zoom_booking_user in ("", "FILL_ME"):
        print("Set ZOOM_BOOKING_USER and ZOOM_BOOKING_BASE in .env first (your scheduler.zoom.us handle).")
        return 2
    svc = BookingService(store_lead=print_lead, send_brief=send_host_brief)
    try:
        scheds = svc.list_schedules()
    except AvailabilityError as e:
        print("Could not list schedules:", e)
        print("Is the booking page public? Open", settings.zoom_booking_base, "in a private window.")
        return 1
    print(f"Call types on {settings.zoom_booking_base}:")
    for s in scheds:
        print(f"  - {s.slug}: {s.name} ({s.duration_min} min)")

    if len(argv) >= 2 and argv[0] == "book":
        slug = argv[1]
        res = svc.get_available_slots(slug, 14, VISITOR_TZ)
        if not res.ok:
            print("No bookable slot:", res.error, "->", res.fallback_link)
            return 1
        slot = res.slots[0]
        print(f"\nBooking {res.schedule.name} at {slot.label_visitor} / {slot.label_host}")
        out = svc.book_slot(slug, slot.start_iso, "Test Visitor", "visitor@example.com",
                            "testing the assistant's booking flow", VISITOR_TZ)
        print("  status:", out.status)
        print("  brief emailed:", out.brief_sent, "->", settings.host_email)
        print("  message:", out.message)
        if out.handoff_url:
            print("  OPEN THIS to finish on Zoom:", out.handoff_url)
        return 0

    for s in scheds:
        res = svc.get_available_slots(s.slug, 14, VISITOR_TZ)
        print(f"\n{s.name}: " + ("" if res.ok else f"{res.error}"))
        for sl in res.slots:
            print(f"  {sl.label_visitor}   = {sl.label_host}   start_iso={sl.start_iso}")
    print(f"\nNext: python scripts/smoke_booking.py book {scheds[0].slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
