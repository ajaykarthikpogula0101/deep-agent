"""The booking path under the failure cases from the brief. Zoom HTTP is mocked with respx;
storage and email are fakes, so nothing here touches Postgres, SMTP or the real scheduler."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.booking.service import BookingService, pick_three
from app.booking.zoom import (
    ZOOM_PUBLIC,
    AvailabilityError,
    InvalidTimeError,
    Slot,
    ZoomPublicClient,
    normalize_available,
    normalize_schedules,
    parse_start,
)
from app.config import settings

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
LIST_URL = f"{ZOOM_PUBLIC}/appointments"
BASE = settings.zoom_booking_base

SCHEDULES = {"items": [
    {"id": "id-disc", "slug": "discovery-call", "summary": "LakeB2B Discovery Call", "duration": 15, "active": True,
     "bookingLink": f"{BASE}/discovery-call"},
    {"id": "id-demo", "slug": "lakeb2b-product-walkthrough-use-case-demo", "summary": "LakeB2B Product Walkthrough & Use Case Demo",
     "duration": 30, "active": True, "bookingLink": f"{BASE}/lakeb2b-product-walkthrough-use-case-demo"},
    {"id": "id-gtm", "slug": "gtm-strategy-session-data-ai-revenue-acceleration", "summary": "GTM Strategy Session", "duration": 45,
     "active": True, "bookingLink": f"{BASE}/gtm-strategy-session-data-ai-revenue-acceleration"},
    {"id": "id-old", "slug": "retired", "summary": "Old", "duration": 30, "active": False},
]}


def avail_url(slug="discovery-call"):
    return f"{ZOOM_PUBLIC}/appointments/{slug}/availableTimes"


def payload(spots: list[tuple[str, str]], duration: int = 15) -> dict:
    """spots: (startTime ISO with offset, status)"""
    days: dict[str, list] = {}
    for st, status in spots:
        days.setdefault(st[:10], []).append({"availableNumber": 1, "startTime": st, "status": status})
    return {"duration": duration, "days": [{"date": d, "spots": s} for d, s in days.items()], "customFields": []}


class FakeStore:
    def __init__(self):
        self.leads: list[dict] = []

    def __call__(self, lead: dict) -> int:
        self.leads.append(lead)
        return len(self.leads)


class FakeMail:
    def __init__(self, ok=True):
        self.sent: list[dict] = []
        self.ok = ok

    def __call__(self, lead: dict) -> bool:
        self.sent.append(lead)
        return self.ok


def make_service(store=None, mail=None, visitor_mail=None):
    return BookingService(clients=[ZoomPublicClient(httpx.Client())], store_lead=store or FakeStore(),
                         send_brief=mail or FakeMail(), send_visitor=visitor_mail or FakeMail(), now=lambda: NOW,
                         enrich=lambda email: {"domain": "lovelace.org", "kind": "business", "company": "Lovelace"})


@respx.mock
def test_visitor_gets_a_thank_you_with_the_final_outcome_and_the_zoom_link():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "available")])))
    visitor = FakeMail()
    res = make_service(FakeStore(), FakeMail(), visitor).book_slot("discovery-call", "2026-10-06T17:30:00+05:30", "Ada Lovelace",
                                                                   "ada@lovelace.org", "demo", "Asia/Kolkata")
    assert res.status == "handoff" and res.visitor_mailed is True
    lead = visitor.sent[0]
    assert lead["email"] == "ada@lovelace.org" and lead["status"] == "handoff" and lead["duration_min"] == 15
    assert lead["handoff_url"].startswith("https://scheduler.zoom.us/") and "firstname=Ada" in lead["handoff_url"]


def mock_schedules():
    return respx.get(LIST_URL).mock(return_value=httpx.Response(200, json=SCHEDULES))


# ---------------------------------------------------------------- schedules
def test_all_three_call_types_are_offered_and_inactive_ones_hidden():
    scheds = normalize_schedules(SCHEDULES, BASE)
    assert [s.slug for s in scheds] == ["discovery-call", "lakeb2b-product-walkthrough-use-case-demo",
                                        "gtm-strategy-session-data-ai-revenue-acceleration"]
    assert [s.duration_min for s in scheds] == [15, 30, 45]
    with pytest.raises(AvailabilityError):
        normalize_schedules({"items": []}, BASE)


@respx.mock
def test_unknown_call_type_returns_the_choices():
    mock_schedules()
    res = make_service().get_available_slots("coffee-chat", 7, "Europe/London")
    assert not res.ok and res.error == "unknown_schedule"
    assert [c.slug for c in res.choices][0] == "discovery-call" and len(res.choices) == 3


@respx.mock
def test_schedule_list_is_cached():
    route = mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "available")])))
    svc = make_service()
    svc.get_available_slots("discovery-call", 7, "Asia/Kolkata")
    svc.get_available_slots("discovery-call", 7, "Asia/Kolkata")
    assert route.call_count == 1


# ---------------------------------------------------------------- 1. happy path (baseline)
@respx.mock
def test_slots_are_shown_in_visitor_timezone_and_spread_over_days():
    mock_schedules()
    respx.get(avail_url("gtm-strategy-session-data-ai-revenue-acceleration")).mock(return_value=httpx.Response(200, json=payload([
        ("2026-10-06T17:30:00+05:30", "available"), ("2026-10-06T18:00:00+05:30", "available"),
        ("2026-10-07T12:00:00+05:30", "available"), ("2026-10-08T12:00:00+05:30", "available"),
        ("2026-10-06T13:00:00+05:30", "unavailable"),
    ], duration=45)))
    res = make_service().get_available_slots("gtm-strategy-session-data-ai-revenue-acceleration", 7, "America/New_York")
    assert res.ok and res.source == "zoom-public-fallback" and res.schedule.duration_min == 45
    # 08:00 and 08:30 NY are daytime for the visitor; the 02:30 slots are only used to fill up
    assert [s.start_iso for s in res.slots] == [
        "2026-10-06T08:00:00-04:00", "2026-10-06T08:30:00-04:00", "2026-10-07T02:30:00-04:00"]
    assert res.slots[0].label_host.endswith("(Asia/Kolkata)") and "17:30" in res.slots[0].label_host
    assert res.fallback_link.endswith("/gtm-strategy-session-data-ai-revenue-acceleration")


# ---------------------------------------------------------------- 2. no slots available
@respx.mock
def test_no_slots_returns_fallback_link():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=payload([
        ("2026-10-06T13:00:00+05:30", "unavailable")])))
    res = make_service().get_available_slots("discovery-call", 7, "Europe/London")
    assert not res.ok and res.error == "no_slots"
    assert res.fallback_link == f"{BASE}/discovery-call"


# ---------------------------------------------------------------- 3. scheduler timed out / changed
@respx.mock
def test_timeout_returns_unavailable_not_a_crash():
    mock_schedules()
    respx.get(avail_url()).mock(side_effect=httpx.ReadTimeout("slow"))
    res = make_service().get_available_slots("discovery-call", 7, "Europe/London")
    assert not res.ok and res.error == "unavailable"


@respx.mock
def test_schedule_listing_down_is_unavailable():
    respx.get(LIST_URL).mock(side_effect=httpx.ConnectError("down"))
    res = make_service().get_available_slots("discovery-call", 7, "Europe/London")
    assert not res.ok and res.error == "unavailable" and res.fallback_link == BASE


@respx.mock
def test_schema_change_is_detected():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json={"items": [{"foo": "bar"}]}))
    res = make_service().get_available_slots("discovery-call", 7, "Europe/London")
    assert not res.ok and res.error == "unavailable"
    with pytest.raises(AvailabilityError):
        normalize_available({"days": [{"spots": [{"status": "available"}]}]}, 15)


@respx.mock
def test_unavailable_at_confirm_time_still_saves_lead_and_briefs_host():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(502, text="bad gateway"))
    store, mail = FakeStore(), FakeMail()
    res = make_service(store, mail).book_slot("discovery-call", "2026-10-06T08:00:00-04:00", "Ada Lovelace", "ada@lovelace.org",
                                              "LakeB2B data for EU fintech", "America/New_York")
    assert res.status == "unavailable"
    assert store.leads[0]["status"] == "enquiry" and mail.sent[0]["email"] == "ada@lovelace.org"
    assert mail.sent[0]["schedule"] == "LakeB2B Discovery Call"
    assert res.handoff_url.startswith(f"{BASE}/discovery-call?") and "firstname=Ada" in res.handoff_url


# ---------------------------------------------------------------- 4. slot taken between show and confirm
@respx.mock
def test_slot_taken_between_show_and_confirm():
    mock_schedules()
    route = respx.get(avail_url())
    route.mock(return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "available")])))
    svc = make_service()
    shown = svc.get_available_slots("discovery-call", 7, "Asia/Kolkata")
    assert shown.ok and shown.slots[0].start_iso == "2026-10-06T17:30:00+05:30"
    # someone else books it before we confirm
    route.mock(return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "unavailable")])))
    res = svc.book_slot("discovery-call", shown.slots[0].start_iso, "Ada Lovelace", "ada@lovelace.org", "demo", "Asia/Kolkata")
    assert res.status == "slot_taken" and res.handoff_url is None
    assert route.call_count == 2  # availability was re-checked right before confirming


# ---------------------------------------------------------------- 5. timezone mismatch
@respx.mock
def test_same_instant_in_a_different_zone_is_accepted():
    mock_schedules()
    respx.get(avail_url("lakeb2b-product-walkthrough-use-case-demo")).mock(
        return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "available")], duration=30)))
    store = FakeStore()
    res = make_service(store).book_slot("lakeb2b-product-walkthrough-use-case-demo", "2026-10-06T08:00:00-04:00",
                                        "Ada Lovelace", "ada@lovelace.org", "demo", "America/New_York")
    assert res.status == "handoff" and res.schedule.duration_min == 30
    assert res.slot.label_visitor.startswith("Tue 06 Oct, 08:00") and "17:30" in res.slot.label_host
    assert store.leads[0]["slot_start"] == datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    assert res.handoff_url.startswith(f"{BASE}/lakeb2b-product-walkthrough-use-case-demo?")


@respx.mock
def test_naive_time_or_unknown_zone_is_rejected_not_assumed():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "available")])))
    svc = make_service()
    r1 = svc.book_slot("discovery-call", "2026-10-06T17:30:00", "Ada", "ada@lovelace.org", "demo", "Asia/Kolkata")  # no offset
    r2 = svc.book_slot("discovery-call", "2026-10-06T17:30:00+05:30", "Ada", "ada@lovelace.org", "demo", "Mars/Olympus")
    assert r1.status == "invalid" and "offset" in r1.message
    assert r2.status == "invalid" and "timezone" in r2.message
    with pytest.raises(InvalidTimeError):
        parse_start("not a time")
    assert respx.calls.call_count == 0  # rejected before touching Zoom


# ---------------------------------------------------------------- hand-off details + brief ordering
@respx.mock
def test_handoff_sends_brief_before_returning_link_and_prefills_zoom():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=payload([("2026-10-06T17:30:00+05:30", "available")])))
    store, mail = FakeStore(), FakeMail(ok=False)  # SMTP down
    res = make_service(store, mail).book_slot("discovery-call", "2026-10-06T17:30:00+05:30", "Ada Lovelace", "ada@lovelace.org",
                                              "LakeB2B demo", "Asia/Kolkata")
    assert res.status == "handoff" and res.lead_id == 1 and res.brief_sent is False  # lead saved even if mail fails
    assert "firstname=Ada&lastname=Lovelace&email=ada%40lovelace.org&month=2026-10" in res.handoff_url
    assert "utm_source=deependhq-assistant" in res.handoff_url


@respx.mock
def test_book_slot_validates_inputs_before_any_network():
    svc = make_service()
    assert svc.book_slot("discovery-call", "2026-10-06T17:30:00+05:30", "", "ada@lovelace.org", "x", "UTC").status == "invalid"
    assert svc.book_slot("discovery-call", "2026-10-06T17:30:00+05:30", "Ada", "not-an-email", "x", "UTC").status == "invalid"
    assert svc.book_slot("discovery-call", "2026-10-06T17:30:00+05:30", "Ada", "ada@lovelace.org", "", "UTC").status == "invalid"
    assert svc.book_slot("discovery-call", "2020-01-01T10:00:00+00:00", "Ada", "ada@lovelace.org", "x", "UTC").status == "invalid"
    assert respx.calls.call_count == 0


def test_pick_three_prefers_distinct_days():
    mk = lambda d, h: Slot(datetime(2026, 10, d, h, 0, tzinfo=timezone.utc), 15)
    slots = [mk(6, 9), mk(6, 10), mk(6, 11), mk(7, 9), mk(8, 9)]
    assert [s.start_utc.day for s in pick_three(slots, "UTC")] == [6, 7, 8]
    assert [s.start_utc.hour for s in pick_three(slots[:3], "UTC")] == [9, 10, 11]
    # 09:00 UTC is 04:00 in New York: night slots only when nothing better exists
    night_only = [mk(6, 9), mk(7, 9)]
    assert len(pick_three(night_only, "America/New_York")) == 2
    mixed = [mk(6, 9), mk(6, 14), mk(7, 9)]  # 14:00 UTC = 10:00 NY
    assert pick_three(mixed, "America/New_York")[0].start_utc.hour == 14
