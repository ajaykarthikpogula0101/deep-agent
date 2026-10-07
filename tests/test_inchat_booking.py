"""In-chat booking (docs/BOOKING.md): the availability grid, review, confirm with every Zoom outcome, cancel, the
invite and the retrying mailer. Zoom HTTP is mocked with respx; storage and mail are fakes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app import mailer as mailer_mod
from app import templates
from app.booking import availability as avail
from app.booking import flow, ics
from app.booking.service import BookingService
from app.booking.zoom import ZOOM_API, ZOOM_OAUTH, ZOOM_PUBLIC, Slot, ZoomOfficialClient, ZoomPublicClient, normalize_schedules
from app.config import settings
from tests.test_booking import SCHEDULES, FakeMail, FakeStore, avail_url, mock_schedules, payload

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)  # Monday 14:30 IST
SCHED = normalize_schedules(SCHEDULES, settings.zoom_booking_base)[0]  # discovery call, 15 min


def svc(official=False, **kw):
    clients = [ZoomPublicClient(httpx.Client())]
    if official:
        clients.insert(0, ZoomOfficialClient(httpx.Client()))
    return BookingService(clients=clients, store_lead=kw.get("store") or FakeStore(), send_brief=FakeMail(), send_visitor=FakeMail(),
                          now=lambda: NOW, enrich=lambda e: {"domain": "lovelace.org", "kind": "business", "company": "Lovelace"})


class FakeDeps:
    def __init__(self, active=0, busy=None):
        self.bookings: list[dict] = []
        self.mails: list[dict] = []
        self.events: list[tuple] = []
        self.active = active
        self._busy = busy or []
        self.deps = flow.Deps(store_booking=self.store, count_active=lambda e: self.active, busy=lambda a, b: self._busy,
                              mail=self.mails.append, log_event=lambda k, s, d: self.events.append((k, d)))

    def store(self, b):
        self.bookings.append(b)
        return 7


def week_spots(duration=15):
    """Mon–Fri 10:00–12:00 IST open on the 30-min grid, except Tue 10:30 (taken on Zoom's side)."""
    spots = []
    for d in range(0, 8):
        day = (NOW + timedelta(days=d)).astimezone(avail.ZoneInfo("Asia/Kolkata")).date()
        if day.weekday() >= 5:
            continue
        for hh, mm in ((10, 0), (10, 30), (11, 0), (11, 30)):
            if day.weekday() == 1 and (hh, mm) == (10, 30):
                continue
            spots.append((f"{day.isoformat()}T{hh:02d}:{mm:02d}:00+05:30", "available"))
    return payload(spots, duration)


# ---------------------------------------------------------------- 1. the grid
def test_grid_marks_open_taken_past_and_booked_in_the_visitor_zone():
    slots = [Slot(datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc), 15), Slot(datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc), 15),
             Slot(datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc), 15),   # Tue 10:00, 10:30, 12:00 IST
             Slot(datetime(2026, 10, 5, 10, 30, tzinfo=timezone.utc), 15)]  # Mon 16:00 IST (later today)
    busy = [(datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc), datetime(2026, 10, 6, 5, 15, tzinfo=timezone.utc))]
    days = avail.build_days(slots, SCHED, "America/New_York", NOW, 3, busy)
    assert len(days) == 3 and days[0]["date"] == "2026-10-05" and days[0]["label"].startswith("Mon")
    tue = days[1]
    assert tue["label"].startswith("Tue") and tue["open"] == 2
    by = {s["time"]: s for s in tue["slots"]}
    assert by["00:30"]["available"] is True and by["00:30"]["label_host"].startswith("Tue 06 Oct, 10:00")
    assert by["01:00"]["available"] is False and by["01:00"]["reason"] == "booked"       # our own confirmed booking
    assert by["01:30"]["available"] is False and by["01:30"]["reason"] == "unavailable"  # Zoom did not offer it
    assert by["02:00"]["available"] is True
    mon = {s["label_host"][12:17]: s for s in days[0]["slots"]}                       # Monday: morning is past, 16:00 open
    assert days[0]["open"] == 1 and mon["16:00"]["available"] and mon["10:00"]["reason"] == "past" and mon["15:00"]["reason"] == "unavailable"


def test_grid_infers_hours_and_step_and_greys_weekends(monkeypatch):
    monkeypatch.setattr(settings, "host_hours", "")
    slots = [Slot(datetime(2026, 10, 6, 3, 45, tzinfo=timezone.utc), 15), Slot(datetime(2026, 10, 7, 9, 15, tzinfo=timezone.utc), 15)]
    start, end, step, weekdays = avail.infer_window(slots, "Asia/Kolkata", 15)
    assert (start, end, step) == (9 * 60, 15 * 60, 15) and weekdays == {1, 2}
    days = avail.build_days(slots, SCHED, "Asia/Kolkata", NOW, 7, [])
    sat = next(d for d in days if d["label"].startswith("Sat"))
    assert sat["open"] == 0 and sat["slots"] == []
    monkeypatch.setattr(settings, "host_hours", "09:00-18:00")
    assert avail.infer_window([], "Asia/Kolkata", 30)[:3] == (540, 1080, 30)


@respx.mock
def test_availability_endpoint_shape_caches_and_invalidates(monkeypatch):
    mock_schedules()
    route = respx.get(avail_url()).mock(return_value=httpx.Response(200, json=week_spots()))
    avail.invalidate()
    d = avail.availability(svc(), "discovery-call", 14, "Europe/London")
    assert d["ok"] and d["schedule"]["slug"] == "discovery-call" and d["schedule"]["description"].startswith("A short first")
    assert d["timezone"] == "Europe/London" and len(d["days"]) == 14 and d["open_total"] > 10
    tue = d["days"][1]  # 10:00 IST = 05:30 London (BST); 10:30 IST was not offered by Zoom
    assert tue["label"].startswith("Tue") and any(s["time"] == "05:30" and s["available"] for s in tue["slots"])
    assert any(s["time"] == "06:00" and not s["available"] and s["reason"] == "unavailable" for s in tue["slots"])
    assert any(s["label_host"].startswith("Tue 06 Oct, 10:30") and not s["available"] for s in tue["slots"])
    assert "Times" not in str(d)  # the note is the client's
    d2 = avail.availability(svc(), "discovery-call", 14, "Europe/London")
    assert d2["cached"] is True and route.call_count == 1
    avail.invalidate("discovery-call")
    avail.availability(svc(), "discovery-call", 14, "Europe/London")
    assert route.call_count == 2
    assert avail.availability(svc(), "coffee", 14, "Europe/London")["error"] == "unknown_schedule"
    assert [n["slot"] if False else n["time"] for n in avail.nearest(d, datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc), 2)]


# ---------------------------------------------------------------- 2. review (the model's book_slot)
@respx.mock
def test_review_opens_the_card_for_open_times_and_offers_alternatives_otherwise():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=week_spots()))
    avail.invalidate()
    r = flow.review(svc(), "discovery-call", "2026-10-06T10:00:00+05:30", "Ada Lovelace", "ada@lovelace.org", "demo", "Asia/Kolkata")
    assert r["status"] == "review" and r["slot"]["time"] == "10:00" and r["prefill"]["email"] == "ada@lovelace.org"
    r = flow.review(svc(), "discovery-call", "2026-10-06T10:30:00+05:30", "Visitor", "visitor@example.com", "", "Asia/Kolkata")
    assert r["status"] == "unavailable" and r["wanted"].startswith("Tue 06 Oct, 10:30") and len(r["alternatives"]) == 3
    assert r["prefill"] == {"name": "", "email": "", "reason": ""}  # placeholders never prefill the form
    assert r["alternatives"][0]["time"] in ("10:00", "11:00")
    assert flow.review(svc(), "discovery-call", "tomorrow 4pm", "", "", "", "Asia/Kolkata")["status"] == "invalid"


# ---------------------------------------------------------------- 3. confirm
def _oauth():
    respx.post(ZOOM_OAUTH).mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600}))
    # the official client is asked first for schedules and availability
    respx.get(f"{ZOOM_API}/scheduler/schedules").mock(return_value=httpx.Response(200, json=SCHEDULES))
    respx.get(f"{ZOOM_API}/scheduler/schedules/id-disc/available_times").mock(return_value=httpx.Response(200, json=week_spots()))


def _req(**kw):
    base = dict(schedule_slug="discovery-call", start="2026-10-06T10:00:00+05:30", name="Ada Lovelace", email="ada@lovelace.org",
                visitor_tz="Asia/Kolkata", company="Lovelace Analytical Engines", notes="EU fintech data", session_id="s1",
                extra={"base_url": "https://assistant.test"})
    base.update(kw)
    return flow.ConfirmRequest(**base)


@respx.mock
def test_confirm_books_through_the_scheduler_api_first(monkeypatch):
    monkeypatch.setattr(settings, "zoom_enable_api_booking", True)
    monkeypatch.setattr(settings, "zoom_host_user_id", "deep@championsmail.com")
    monkeypatch.setattr(settings, "public_base_url", "")  # links then come from the request's base url
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=week_spots()))
    _oauth()
    sched_route = respx.post(f"{ZOOM_API}/scheduler/attendee").mock(return_value=httpx.Response(201, json={"id": "evt-1", "join_url": "https://zoom.us/j/1"}))
    f = FakeDeps()
    store = FakeStore()
    res = flow.confirm(svc(official=True, store=store), _req(), f.deps)
    assert res["status"] == "confirmed" and res["booking"]["method"] == "scheduler" and res["booking"]["join_url"] == "https://zoom.us/j/1"
    body = json.loads(sched_route.calls[0].request.content)
    assert body["schedule_id"] == "id-disc" and body["duration"] == 15 and body["booker"]["first_name"] == "Ada"
    assert body["location_configuration"] == {"kind": "zoomMeeting"} and body["start_date_time"] == "2026-10-06T04:30:00Z" and body["time_zone"] == "Asia/Kolkata"
    assert res["booking"]["ics_url"].startswith("https://assistant.test/booking/7/ics?t=") and res["booking"]["label_visitor"].startswith("Tue 06 Oct, 10:00")
    assert store.leads[0]["status"] == "booked" and store.leads[0]["company"].startswith("Lovelace")
    assert f.bookings[0]["status"] == "confirmed" and f.bookings[0]["end_utc"] - f.bookings[0]["start_utc"] == timedelta(minutes=15)
    assert f.mails and f.mails[0]["id"] == 7 and f.events[0][0] == "booking_confirmed"


@respx.mock
def test_confirm_falls_back_to_the_meetings_api_then_to_the_handoff_link(monkeypatch):
    monkeypatch.setattr(settings, "zoom_enable_api_booking", True)
    monkeypatch.setattr(settings, "zoom_host_user_id", "deep@championsmail.com")
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=week_spots()))
    _oauth()
    respx.post(f"{ZOOM_API}/scheduler/attendee").mock(return_value=httpx.Response(400, json={"message": "Failed json validation!"}))
    meet = respx.post(f"{ZOOM_API}/users/deep@championsmail.com/meetings").mock(
        return_value=httpx.Response(201, json={"id": 81234567890, "join_url": "https://zoom.us/j/81234567890", "password": "742913"}))
    f = FakeDeps()
    res = flow.confirm(svc(official=True), _req(), f.deps)
    assert res["status"] == "confirmed" and res["booking"]["method"] == "meeting" and res["booking"]["passcode"] == "742913"
    body = json.loads(meet.calls[0].request.content)
    assert body["topic"] == "LakeB2B Discovery Call — Ada Lovelace × Deep" and body["start_time"] == "2026-10-06T04:30:00Z" and body["duration"] == 15
    assert body["settings"]["meeting_invitees"] == [{"email": "ada@lovelace.org"}] and "EU fintech data" in body["agenda"]
    assert f.bookings[0]["zoom_error"].startswith("zoom booking failed 400")
    # no API at all (today's situation): the visitor finishes on Zoom with prefilled details
    f2 = FakeDeps()
    res = flow.confirm(svc(official=False), _req(), f2.deps)
    assert res["status"] == "pending_zoom" and res["booking"]["method"] == "handoff"
    assert res["booking"]["handoff_url"].startswith("https://scheduler.zoom.us/sreedeep/discovery-call?firstname=Ada&lastname=Lovelace&email=ada%40lovelace.org")
    assert f2.events[0][0] == "booking_pending" and f2.mails[0]["status"] == "pending_zoom"


@respx.mock
def test_confirm_refuses_taken_slots_rate_limits_and_placeholders(monkeypatch):
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(200, json=week_spots()))
    avail.invalidate()
    # taken on Zoom's side right before confirming
    f = FakeDeps()
    res = flow.confirm(svc(), _req(start="2026-10-06T10:30:00+05:30"), f.deps)
    assert res["status"] == "slot_taken" and len(res["alternatives"]) == 3 and not f.bookings
    # taken by one of our own confirmed bookings
    busy = [(datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc), datetime(2026, 10, 6, 4, 45, tzinfo=timezone.utc))]
    res = flow.confirm(svc(), _req(), FakeDeps(busy=busy).deps)
    assert res["status"] == "slot_taken"
    assert flow.confirm(svc(), _req(), FakeDeps(active=2).deps)["status"] == "rate_limited"
    assert flow.confirm(svc(), _req(name="Visitor", email="visitor@example.com"), FakeDeps().deps)["status"] == "invalid"
    assert flow.confirm(svc(), _req(email="nope"), FakeDeps().deps)["status"] == "invalid"
    assert flow.confirm(svc(), _req(start="2026-10-04T10:00:00+05:30"), FakeDeps().deps)["status"] == "slot_taken"  # in the past


@respx.mock
def test_confirm_when_zoom_is_down_points_to_the_scheduler_page():
    mock_schedules()
    respx.get(avail_url()).mock(return_value=httpx.Response(503))
    res = flow.confirm(svc(), _req(), FakeDeps().deps)
    assert res["status"] == "unavailable" and res["retry"] and res["fallback_link"].endswith("/discovery-call")


# ---------------------------------------------------------------- 4. cancel
@respx.mock
def test_cancel_deletes_our_meeting_and_tells_both_sides():
    _oauth()
    route = respx.delete(f"{ZOOM_API}/meetings/812").mock(return_value=httpx.Response(204))
    marked, mails = [], []
    booking = dict(templates.SAMPLE_BOOKING, id=5, method="meeting", zoom_meeting_id="812")
    r = flow.cancel(booking, svc(official=True), mark=lambda i: marked.append(i) or True, mail=mails.append)
    assert r["ok"] and marked == [5] and route.called and mails[0]["status"] == "cancelled"
    r = flow.cancel(dict(booking, method="scheduler"), svc(official=True), mark=lambda i: True, mail=mails.append)
    assert "Zoom Scheduler" in r["zoom_note"]
    assert flow.cancel(dict(booking, status="cancelled"), svc(), mark=lambda i: True, mail=mails.append)["already"]


# ---------------------------------------------------------------- 5. invite + emails + mailer
def test_ics_is_valid_utc_and_folded():
    text = ics.build(templates.SAMPLE_BOOKING, "Deep")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and "DTSTART:20261007T133000Z" in text and "DTEND:20261007T134500Z" in text
    assert "SUMMARY:LakeB2B Discovery Call — Ada Lovelace × Deep" in text and "ATTENDEE;CN=Ada Lovelace;ROLE=REQ-PARTICIPANT:mailto:ada@lovelace.org" in text
    assert "Join Zoom: https://zoom.us/j/81234567890?pwd=sample" in text.replace("\r\n ", "") and "Passcode: 742913" in text.replace("\r\n ", "")
    assert all(len(ln.encode()) <= 75 for ln in text.split("\r\n"))


def test_booking_emails_render_for_both_sides_and_queue_with_the_invite():
    s, b = templates.render_booking_host(templates.SAMPLE_BOOKING)
    assert s == "[LakeB2B] New booking: Ada Lovelace · LakeB2B Discovery Call · Wed 07 Oct, 19:00 (Asia/Kolkata)"
    assert "Zoom meeting created" in b and "Company:  Lovelace Analytical Engines (lovelace.org)" in b and "Meeting ID 812 3456 7890 · Passcode 742913" in b
    s, b = templates.render_booking_visitor(templates.SAMPLE_BOOKING)
    assert s == "Your call with Deep is confirmed: LakeB2B Discovery Call on Wed 07 Oct, 09:30 (America/New_York)"
    assert b.startswith("Hi Ada,\n\nYour call with Deep is confirmed.") and "Zoom:     https://zoom.us/j/81234567890?pwd=sample" in b
    assert "Cancel or reschedule here: https://assistant.deependhq.com/booking/42/manage?t=sample" in b
    s, b = templates.render_booking_visitor(dict(templates.SAMPLE_BOOKING, status="pending_zoom", join_url="", handoff_url="https://scheduler.zoom.us/x"))
    assert s.startswith("Your call with Deep: one last step") and "confirm the time on Zoom here" in b and "https://scheduler.zoom.us/x" in b
    html = templates.html_wrap(s, b, ("Confirm on Zoom", "https://scheduler.zoom.us/x"))
    assert "<table" in html and "Confirm on Zoom" in html and "#F28C28" in html and "<script" not in html
    from app.booking.email import send_booking_emails

    m = mailer_mod.Mailer(sender=lambda *a, **k: True, sync=True)
    send_booking_emails(templates.SAMPLE_BOOKING, mailer=m)
    kinds = [r["kind"] for r in m.results]
    assert sorted(kinds) == ["booking_host", "booking_visitor"] and all(r["ok"] for r in m.results)


def test_mailer_retries_with_backoff_then_gives_up():
    attempts, naps = [], []

    def flaky(to, subject, body, **kw):
        attempts.append(to)
        return len(attempts) >= 3

    m = mailer_mod.Mailer(sender=flaky, sleep=naps.append, sync=True)
    m.enqueue("x@y.z", "s", "b", attachments=[("invite.ics", "BEGIN:VCALENDAR", "text/calendar")], kind="t")
    assert len(attempts) == 3 and naps == [2, 8] and m.results[0]["ok"] is True
    m2 = mailer_mod.Mailer(sender=lambda *a, **k: False, sleep=naps.append, sync=True)
    m2.enqueue("x@y.z", "s", "b")
    assert m2.results[0]["ok"] is False and m2.results[0]["error"] is None
    m3 = mailer_mod.Mailer(sender=lambda *a, **k: (_ for _ in ()).throw(OSError("smtp down")), sleep=lambda s: None, sync=True)
    m3.enqueue("x@y.z", "s", "b")
    assert m3.results[0]["error"] == "smtp down"


def test_send_builds_html_alternative_and_calendar_attachment(monkeypatch):
    import smtplib

    from app.booking import email as em

    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): captured["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    assert em._send("to@x.y", "Sub", "plain", html="<p>hi</p>", attachments=[("invite.ics", "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", "text/calendar")])
    msg = captured["msg"]
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts and "text/calendar" in parts and msg["Subject"] == "Sub"
    att = next(p for p in msg.walk() if p.get_content_type() == "text/calendar")
    assert att.get_filename() == "invite.ics" and att.get_param("method") == "PUBLISH"
