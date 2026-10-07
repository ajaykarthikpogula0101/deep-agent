"""Hits the real public Zoom endpoints for scheduler.zoom.us/sreedeep. Skipped unless LIVE=1.
Run:  LIVE=1 pytest tests/test_live_zoom.py -s
"""
import os

import pytest

from app.booking.service import BookingService
from app.booking.zoom import ZoomPublicClient

pytestmark = pytest.mark.skipif(os.environ.get("LIVE") != "1", reason="set LIVE=1 to hit Zoom")


def test_live_schedules_and_availability_for_each_call_type():
    svc = BookingService(clients=[ZoomPublicClient()], store_lead=lambda l: 0, send_brief=lambda l: False, send_visitor=lambda l: False)
    scheds = svc.list_schedules()
    print("\nschedules:", [(s.slug, s.duration_min) for s in scheds])
    assert {s.slug for s in scheds} >= {"discovery-call", "lakeb2b-product-walkthrough-use-case-demo",
                                        "gtm-strategy-session-data-ai-revenue-acceleration"}
    for s in scheds:
        ist = svc.get_available_slots(s.slug, 14, "Asia/Kolkata")
        ny = svc.get_available_slots(s.slug, 14, "America/New_York")
        print(f"{s.slug} ({s.duration_min} min)")
        print("  IST:", [x.label_visitor for x in ist.slots])
        print("  NY :", [x.label_visitor for x in ny.slots])
        assert ist.ok and ny.ok and ist.schedule.duration_min == s.duration_min
