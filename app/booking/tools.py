"""Tool schemas exposed to the model + the dispatcher that executes them.

The visitor's timezone is NOT a model argument: it comes from the browser with each request and is
injected here, so the model cannot drift into a wrong zone. The call types (schedules) are fetched
live from Zoom and injected into the system prompt, so the model picks from real options only.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict

from app.booking import availability as avail
from app.booking import flow
from app.booking.service import BookingService

log = logging.getLogger("booking.tools")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Fetch live availability for one call type. The interface then shows the visitor a date and time "
                           "picker with every open and taken time for the next two weeks in their timezone; you get up to 3 open "
                           "slots as context. Do not list times in text. Ask which call type they want first if it is not obvious.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule_slug": {"type": "string", "description": "Slug of the call type, from the list in the system prompt."},
                    "days_ahead": {"type": "integer", "minimum": 1, "maximum": 30, "description": "How many days ahead to look. Default 7."},
                },
                "required": ["schedule_slug", "days_ahead"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_slot",
            "description": "Check a time the visitor named against Deep's live scheduler and open the confirmation card. This "
                           "does NOT book anything: the visitor books by pressing Confirm booking. Pass start as ISO 8601 with "
                           "the visitor's offset (a start_iso from get_available_slots when possible). Leave name/email empty "
                           "if the visitor has not given them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule_slug": {"type": "string", "description": "Same slug used for get_available_slots"},
                    "start": {"type": "string", "description": "ISO 8601 start time with offset, from get_available_slots"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "reason": {"type": "string", "description": "What they want to talk about"},
                },
                "required": ["schedule_slug", "start"],
            },
        },
    },
]


def schedules_prompt(service: BookingService) -> str:
    """One line per live call type for the system prompt; empty string if Zoom is unreachable."""
    try:
        items = service.list_schedules()
    except Exception:
        return "Call types: could not be loaded right now; offer the plain booking page instead."
    lines = [f"- {s.slug}: {s.name} ({s.duration_min} min)" for s in items]
    return "Call types available right now (use the slug with the booking tools):\n" + "\n".join(lines)


def _busy_fn():
    try:
        from app.store_bookings import busy_between

        return busy_between
    except Exception:  # pragma: no cover
        return None


def run_tool(service: BookingService, name: str, args: dict, visitor_tz: str) -> tuple[str, list[dict]]:
    """Returns (json string for the model, ui events for the client)."""
    if name == "get_available_slots":
        slug = str(args.get("schedule_slug", ""))
        res = service.get_available_slots(slug, int(args.get("days_ahead", 7)), visitor_tz)
        payload = asdict(res)
        events = []
        if res.ok or res.error in ("no_slots", "unavailable"):
            try:  # the full two-week grid for the picker card; the 3-slot summary stays for the model and the legacy page
                grid = avail.availability(service, slug, None, visitor_tz, busy_fn=_busy_fn())
                events.append({"type": "availability", **grid})
            except Exception as e:
                log.warning("availability grid failed: %s", e)
        events.append({"type": "slots", **payload})
        if res.ok:
            payload["note"] = ("The visitor now sees a date and time picker with all open and taken times. Reply with one short "
                               "sentence inviting them to pick a time below; do not list times. These 3 slots are a sample, not the "
                               "full availability: if the visitor named a specific day or time, call book_slot with it now instead "
                               "of judging from this sample.")
        return json.dumps(payload), events
    if name == "book_slot":
        res = flow.review(service, str(args.get("schedule_slug", "")), str(args.get("start", "")), str(args.get("name", "")),
                          str(args.get("email", "")), str(args.get("reason", "")), visitor_tz, busy_fn=_busy_fn())
        return json.dumps(res, default=str), [{"type": "booking_review", **res}]
    return json.dumps({"error": f"unknown tool {name}"}), [{"type": "error", "error": "unknown tool"}]
