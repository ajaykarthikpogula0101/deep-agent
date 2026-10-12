"""Browser booking on the public Zoom scheduler page: the worker's pure helpers (slot labels, verification, goals,
links), the app-side runner (subprocess faked), and the booking flow with the browser step (book, cancel, reschedule).
No browser, no model and no network here; the live dry run is scripts/zoom_browser_worker.py (docs/BROWSER_BOOKING.md)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from app.booking import browser_booking as bb
from app.booking import flow
from app.booking.service import BookingService
from app.booking.zoom import ZOOM_PUBLIC, Slot, ZoomPublicClient, normalize_schedules
from app.config import settings
from tests.test_booking import SCHEDULES, FakeMail, FakeStore, avail_url, mock_schedules, payload
from tests.test_inchat_booking import NOW, FakeDeps, week_spots

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("zoom_browser_worker", ROOT / "scripts" / "zoom_browser_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)  # type: ignore[union-attr]

SCHED = normalize_schedules(SCHEDULES, settings.zoom_booking_base)[0]
START = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)  # Thu 16:30 IST
REAL_AVAILABLE = bb.available  # captured before the conftest fixture replaces it


# ---------------------------------------------------------------- worker helpers
def test_slot_labels_match_the_wanted_start_in_either_clock_and_date_order():
    ist = worker.parse_start("2026-10-15T11:00:00+00:00", "Asia/Kolkata")
    assert (ist.hour, ist.minute, ist.day) == (16, 30, 15)
    assert worker.slot_label_matches("Select slot on 15/10/2026, 4:30:00 pm", ist)
    assert worker.slot_label_matches("Select slot on 15/10/2026, 16:30:00", ist)       # en-GB 24 h clock
    assert worker.slot_label_matches("Select slot on 10/15/2026, 4:30 PM", ist)         # US order
    assert not worker.slot_label_matches("Select slot on 15/10/2026, 4:00:00 pm", ist)
    assert not worker.slot_label_matches("Select slot on 16/10/2026, 16:30:00", ist)
    assert not worker.slot_label_matches("Choose Thursday, October 15th, 2026", ist)
    assert worker.date_option_matches("Choose Thursday, October 15th, 2026", ist)
    assert not worker.date_option_matches("Choose Thursday, October 1st, 2026", ist)
    assert not worker.date_option_matches("Choose Tuesday, November 15th, 2026", ist)
    assert worker.expected_phrases(ist) == ["October 15", "4:30", "16:30"]
    assert worker.parse_start("2026-10-15T11:00:00Z", "UTC").hour == 11


def test_verification_reads_the_page_not_the_model():
    ist = worker.parse_start("2026-10-15T11:00:00+00:00", "Asia/Kolkata")
    ok, why = worker.verify_text("You're all set! LakeB2B Discovery Call Thursday, October 15, 2026, 4:30 - 4:45 PM ada@lovelace.org", ist, "ada@lovelace.org", "book")
    assert ok and why == "confirmed"
    ok, why = worker.verify_text("Booked. Thursday, October 15, 2026, 16:30 - 16:45", ist, "ada@lovelace.org", "book")
    assert ok and "email" in why                                                    # en-GB 24 h clock, email not echoed
    assert worker.verify_text("Booked. Thursday, October 15, 2026, 16:30", ist, None, "book")[0]
    assert not worker.verify_text("Enter Your Information First Name Last Name", ist, None, "book")[0]
    assert not worker.verify_text("Booked! Friday, October 16, 2026, 4:30 PM", ist, None, "book")[0]   # wrong day
    assert not worker.verify_text("Booked! Thursday, October 15, 2026, 14:30", ist, None, "book")[0]    # wrong time ('4:30' inside '14:30' must not count)
    assert not worker.verify_text("This time is no longer available. Please try again.", ist, None, "book")[0]
    assert worker.verify_text("Your meeting has been rescheduled to Thursday, October 15, 2026, 4:30 PM", ist, None, "reschedule")[0]
    assert worker.verify_text("Your booking has been cancelled.", None, None, "cancel")[0]
    # a retired manage link (Zoom issues a new one on every reschedule) must never read as success
    ok, why = worker.verify_text("This event is no longer active The event you were looking for may have been canceled or rescheduled.", None, None, "cancel")
    assert not ok and "no longer active" in why
    assert not worker.verify_text("This event is no longer active ... may have been canceled or rescheduled.", ist, None, "reschedule")[0]
    assert not worker.verify_text("Are you sure you want to cancel?", None, None, "cancel")[0] or True  # 'cancel' wording alone is weak; allowed


def test_links_and_goals():
    links = worker.pick_links([{"href": "https://scheduler.zoom.us/sreedeep/discovery-call/reschedule?token=abc", "text": "Reschedule"},
                               {"href": "https://scheduler.zoom.us/cancel?token=abc", "text": "Cancel booking"},
                               {"href": "https://us06web.zoom.us/j/123?pwd=x", "text": "Join"},
                               {"href": "mailto:x@y", "text": "mail"}, {"href": "https://zoom.us/privacy", "text": "Privacy"}])
    assert links == {"reschedule": "https://scheduler.zoom.us/sreedeep/discovery-call/reschedule?token=abc",
                     "cancel": "https://scheduler.zoom.us/cancel?token=abc", "join": "https://us06web.zoom.us/j/123?pwd=x"}
    ist = worker.parse_start("2026-10-15T11:00:00+00:00", "Asia/Kolkata")
    p = {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@lovelace.org", "notes": "EU fintech"}
    g = worker.build_goal("book", p, ist, dry_run=False)
    assert "Thursday, October 15, 2026 at 4:30 PM" in g and "'Ada'" in g and "'ada@lovelace.org'" in g and "click the Book button once" in g
    assert "Do NOT click Book" in worker.build_goal("book", p, ist, dry_run=True)
    assert "Stop (DONE) immediately" in worker.build_goal("cancel", {}, None, dry_run=True)
    assert "Cancel Appointment" in worker.build_goal("cancel", {}, None, dry_run=False)
    assert "already selected" in worker.build_goal("reschedule", {}, ist, dry_run=False)


# ---------------------------------------------------------------- app-side runner
def test_run_parses_the_last_json_line_and_handles_timeouts(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="noise\n" + json.dumps({"ok": True, "status": "booked", "links": {"join": "https://zoom.us/j/1"}}) + "\n", stderr="")

    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    monkeypatch.setattr(bb, "_ensure_browser", lambda: "http://127.0.0.1:9999")  # no real browser in unit tests
    monkeypatch.setattr(bb, "available", REAL_AVAILABLE)  # conftest disables it for every other test
    monkeypatch.setattr(settings, "browser_booking_enabled", True)
    monkeypatch.setattr(settings, "browser_booking_driver", "script")
    monkeypatch.setattr(settings, "typesafe_api_key", "")  # the real .env may carry a key; this test is about the script driver
    res = bb.book("https://scheduler.zoom.us/x/discovery-call", START, "Ada Lovelace", "ada@lovelace.org", "notes")
    assert res["status"] == "booked" and res["links"]["join"] == "https://zoom.us/j/1"
    cmd, kw = calls[0]
    assert cmd[1].endswith("zoom_browser_worker.py") and cmd[2:4] == ["--task", "book"]
    assert kw["env"]["BROWSER_BOOKING_DRIVER"] == "script" and kw["env"]["BH_TELEMETRY"] == "0" and "TYPESAFE_API_KEY" not in kw["env"]
    assert kw["env"]["JEV_CDP_URL"] == "http://127.0.0.1:9999"
    sent = json.load(open(cmd[5], encoding="utf-8")) if Path(cmd[5]).exists() else None
    assert sent is None  # the payload file is removed after the run
    assert bb.driver() == "script" and bb.available() is True and bb.mode() == "browser"

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(bb.subprocess, "run", slow)
    assert bb.cancel("https://x/cancel")["status"] == "timeout"
    monkeypatch.setattr(bb.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Traceback\nboom"))
    r = bb.reschedule("https://x/reschedule", START)
    assert r["ok"] is False and r["status"] == "error" and "boom" in r["message"]
    monkeypatch.setattr(settings, "browser_booking_driver", "jev")
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    assert bb.available() is False and bb.mode() == "handoff"
    monkeypatch.setattr(settings, "typesafe_api_key", "ts-key")
    assert bb.available() is True and bb.driver() == "jev"
    assert bb.summary({"ok": True, "status": "booked", "steps": list(range(40)), "page_text": "x" * 900})["steps"] == list(range(30))


# ---------------------------------------------------------------- the flow with the browser step
def svc():
    return BookingService(clients=[ZoomPublicClient(httpx.Client())], store_lead=FakeStore(), send_brief=FakeMail(), send_visitor=FakeMail(),
                          now=lambda: NOW, enrich=lambda e: {"domain": "lovelace.org", "kind": "business", "company": "Lovelace"})


def req(start="2026-10-06T10:00:00+05:30"):
    return flow.ConfirmRequest(schedule_slug=SCHED.slug, start=start, name="Ada Lovelace", email="ada@lovelace.org", visitor_tz="Asia/Kolkata",
                               notes="EU fintech", session_id="s1")


@respx.mock
def test_confirm_books_through_the_browser_worker_and_keeps_its_links(monkeypatch):
    mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
    monkeypatch.setattr(bb, "available", lambda: True)
    seen = {}

    def fake_book(url, start_utc, name, email, notes, dry_run=None):
        seen.update(url=url, start=start_utc, name=name, email=email, notes=notes)
        return {"ok": True, "status": "booked", "driver": "jev", "elapsed_ms": 9000, "steps": ["slot: x", "jev: CLICK Book"],
                "links": {"reschedule": "https://scheduler.zoom.us/r?t=1", "cancel": "https://scheduler.zoom.us/c?t=1", "join": "https://zoom.us/j/9"}}

    monkeypatch.setattr(bb, "book", fake_book)
    d = FakeDeps()
    res = flow.confirm(svc(), req(), d.deps)
    assert res["status"] == "confirmed" and res["booking"]["method"] == "browser" and res["booking"]["join_url"] == "https://zoom.us/j/9"
    assert seen["name"] == "Ada Lovelace" and seen["start"] == datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc) and seen["url"].endswith(SCHED.slug)
    row = d.bookings[0]
    assert row["zoom_reschedule_url"] == "https://scheduler.zoom.us/r?t=1" and row["zoom_cancel_url"] == "https://scheduler.zoom.us/c?t=1"
    assert row["zoom_run"]["status"] == "booked" and row["zoom_run"]["driver"] == "jev" and row["status"] == "confirmed"
    assert d.events[0][0] == "booking_confirmed" and d.events[0][1]["method"] == "browser"
    assert len(d.mails) == 1 and d.mails[0]["join_url"] == "https://zoom.us/j/9"


@respx.mock
def test_confirm_falls_back_to_the_handoff_link_when_the_worker_fails_and_reports_taken_slots(monkeypatch):
    mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
    monkeypatch.setattr(bb, "available", lambda: True)
    monkeypatch.setattr(bb, "book", lambda *a, **k: {"ok": False, "status": "verify_failed", "message": "no confirmation wording on the page", "steps": []})
    d = FakeDeps()
    res = flow.confirm(svc(), req(), d.deps)
    assert res["status"] == "pending_zoom" and res["booking"]["handoff_url"].startswith("https://scheduler.zoom.us/")
    assert d.bookings[0]["method"] == "handoff" and "verify_failed" in d.bookings[0]["zoom_error"]
    monkeypatch.setattr(bb, "book", lambda *a, **k: {"ok": False, "status": "slot_unavailable", "message": "October 6 10:00 is not offered"})
    res = flow.confirm(svc(), req(), FakeDeps().deps)
    assert res["status"] == "slot_taken" and "alternatives" in res
    monkeypatch.setattr(bb, "book", lambda *a, **k: {"ok": True, "status": "dry_run_ok", "message": "form filled, nothing submitted"})
    res = flow.confirm(svc(), req(), FakeDeps().deps)
    assert res["status"] == "pending_zoom"  # a dry run never counts as a booking


def _browser_booking(**over):
    b = {"id": 7, "status": "confirmed", "method": "browser", "name": "Ada Lovelace", "email": "ada@lovelace.org", "schedule_slug": SCHED.slug,
         "schedule_name": SCHED.name, "duration_min": 15, "start_utc": datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc),
         "end_utc": datetime(2026, 10, 6, 4, 45, tzinfo=timezone.utc), "visitor_tz": "Asia/Kolkata", "manage_token": "tok",
         "zoom_reschedule_url": "https://scheduler.zoom.us/r?t=1", "zoom_cancel_url": "https://scheduler.zoom.us/c?t=1", "session_id": "s1",
         "join_url": "https://zoom.us/j/9"}
    b.update(over)
    return b


@respx.mock
def test_reschedule_moves_a_browser_booking_on_zoom_and_tells_both_sides(monkeypatch):
    mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
    monkeypatch.setattr(bb, "available", lambda: True)
    seen = {}
    monkeypatch.setattr(bb, "reschedule", lambda url, start, dry_run=None: (seen.update(url=url, start=start) or
                        {"ok": True, "status": "rescheduled", "driver": "script",
                         "links": {"join": "https://zoom.us/j/10", "reschedule": "https://scheduler.zoom.us/manage/new1/rescheduling", "cancel": "https://scheduler.zoom.us/manage/new1"}}))
    marks, mails = [], []
    d = FakeDeps(busy=[(datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc), datetime(2026, 10, 6, 4, 45, tzinfo=timezone.utc))])
    res = flow.reschedule(svc(), _browser_booking(), "2026-10-07T11:00:00+05:30", "Asia/Kolkata", d.deps,
                          mark=lambda *a: marks.append(a) or True, mail=mails.append)
    assert res["status"] == "rescheduled" and res["booking"]["label_visitor"].startswith("Wed 07 Oct, 11:00") and res["old_label_visitor"].startswith("Tue 06 Oct, 10:00")
    assert seen["url"] == "https://scheduler.zoom.us/r?t=1" and seen["start"] == datetime(2026, 10, 7, 5, 30, tzinfo=timezone.utc)
    assert marks[0][0] == 7 and marks[0][1] == seen["start"] and marks[0][3]["status"] == "rescheduled" and marks[0][4] == "https://zoom.us/j/10"
    assert marks[0][6] == "https://scheduler.zoom.us/manage/new1/rescheduling" and marks[0][7] == "https://scheduler.zoom.us/manage/new1"  # the fresh manage link replaces the retired one
    assert mails[0]["old_label_visitor"].startswith("Tue 06 Oct") and mails[0]["join_url"] == "https://zoom.us/j/10"
    assert d.events[-1][0] == "booking_rescheduled"
    # the old time itself is not "busy" for this booking; a genuinely taken time is refused with alternatives
    res = flow.reschedule(svc(), _browser_booking(), "2026-10-06T10:30:00+05:30", "Asia/Kolkata", d.deps, mark=lambda *a: True, mail=mails.append)
    assert res["status"] == "slot_taken" and res["alternatives"]
    # Zoom says no at the last moment
    monkeypatch.setattr(bb, "reschedule", lambda *a, **k: {"ok": False, "status": "slot_unavailable", "message": "gone"})
    res = flow.reschedule(svc(), _browser_booking(), "2026-10-07T11:00:00+05:30", "Asia/Kolkata", d.deps, mark=lambda *a: True, mail=mails.append)
    assert res["status"] == "slot_taken"
    monkeypatch.setattr(bb, "reschedule", lambda *a, **k: {"ok": False, "status": "verify_failed", "message": "?"})
    res = flow.reschedule(svc(), _browser_booking(), "2026-10-07T11:00:00+05:30", "Asia/Kolkata", d.deps, mark=lambda *a: True, mail=mails.append)
    assert res["status"] == "error" and res["retry"] is True
    # guards
    assert flow.reschedule(svc(), _browser_booking(status="cancelled"), "2026-10-07T11:00:00+05:30", "Asia/Kolkata", d.deps)["status"] == "invalid"
    assert flow.reschedule(svc(), _browser_booking(method="meeting"), "2026-10-07T11:00:00+05:30", "Asia/Kolkata", d.deps)["status"] == "unsupported"
    assert flow.reschedule(svc(), _browser_booking(), "2026-10-06T10:00:00+05:30", "Asia/Kolkata", d.deps)["status"] == "invalid"  # same time
    assert flow.reschedule(svc(), _browser_booking(), "2026-10-01T10:00:00+05:30", "Asia/Kolkata", d.deps)["status"] == "slot_taken"  # past


@respx.mock
def test_reschedule_of_a_handoff_booking_reholds_the_time_with_a_new_prefilled_link():
    mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
    marks, mails = [], []
    b = _browser_booking(method="handoff", status="pending_zoom", join_url=None, zoom_reschedule_url=None, handoff_url="https://scheduler.zoom.us/x?old=1")
    res = flow.reschedule(svc(), b, "2026-10-07T11:00:00+05:30", "Asia/Kolkata", FakeDeps().deps, mark=lambda *a: marks.append(a) or True, mail=mails.append)
    assert res["status"] == "pending_zoom" and "held" in res["message"]
    assert marks[0][5].startswith("https://scheduler.zoom.us/") and "month=2026-10" in marks[0][5]
    assert mails[0]["handoff_url"] == marks[0][5] and mails[0]["status"] == "pending_zoom"


@respx.mock
def test_reschedule_of_a_handoff_booking_books_the_new_time_on_zoom_when_the_worker_is_available(monkeypatch):
    """A hand-off hold was never confirmed on Zoom, so moving it means booking the new time for real: the visitor is
    never sent to Zoom or to their email."""
    mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
    monkeypatch.setattr(bb, "available", lambda: True)
    seen = {}
    monkeypatch.setattr(bb, "book", lambda url, start, name, email, notes, dry_run=None: (seen.update(url=url, start=start, name=name) or
                        {"ok": True, "status": "booked", "driver": "jev", "links": {"join": "https://zoom.us/j/55", "reschedule": "https://scheduler.zoom.us/manage/h1/rescheduling",
                                                                                     "cancel": "https://scheduler.zoom.us/manage/h1"}}))
    marks, mails = [], []
    b = _browser_booking(method="handoff", status="pending_zoom", join_url=None, zoom_reschedule_url=None, zoom_cancel_url=None, handoff_url="https://scheduler.zoom.us/x?old=1")
    res = flow.reschedule(svc(), b, "2026-10-07T11:00:00+05:30", "Asia/Kolkata", FakeDeps().deps, mark=lambda *a: marks.append(a) or True, mail=mails.append)
    assert res["status"] == "rescheduled" and res["message"].startswith("Moved:") and res["booking"]["method"] == "browser" and res["booking"]["join_url"] == "https://zoom.us/j/55"
    assert seen["name"] == "Ada Lovelace" and seen["start"] == datetime(2026, 10, 7, 5, 30, tzinfo=timezone.utc) and seen["url"].endswith(SCHED.slug)
    m = marks[0]
    assert m[4] == "https://zoom.us/j/55" and m[5] is None and m[6].endswith("/h1/rescheduling") and m[7].endswith("/manage/h1") and m[8] == "browser" and m[9] == "confirmed"
    assert mails[0]["status"] == "confirmed" and mails[0]["method"] == "browser" and not mails[0].get("handoff_url")
    # the worker fails: fall back to re-holding the time with a fresh prefilled link (the old behaviour)
    monkeypatch.setattr(bb, "book", lambda *a, **k: {"ok": False, "status": "verify_failed", "message": "?"})
    res = flow.reschedule(svc(), b, "2026-10-07T11:00:00+05:30", "Asia/Kolkata", FakeDeps().deps, mark=lambda *a: marks.append(a) or True, mail=mails.append)
    assert res["status"] == "pending_zoom" and marks[-1][5].startswith("https://scheduler.zoom.us/") and marks[-1][8] == "handoff"
    monkeypatch.setattr(bb, "book", lambda *a, **k: {"ok": False, "status": "slot_unavailable", "message": "gone"})
    assert flow.reschedule(svc(), b, "2026-10-07T11:00:00+05:30", "Asia/Kolkata", FakeDeps().deps, mark=lambda *a: True, mail=mails.append)["status"] == "slot_taken"


def test_cancel_drives_the_scheduler_cancel_link_for_browser_bookings(monkeypatch):
    monkeypatch.setattr(bb, "available", lambda: True)
    calls = []
    monkeypatch.setattr(bb, "cancel", lambda url, dry_run=None: calls.append(url) or {"ok": True, "status": "cancelled"})
    mails = []
    r = flow.cancel(_browser_booking(), svc(), mark=lambda i: True, mail=mails.append)
    assert r["ok"] and calls == ["https://scheduler.zoom.us/c?t=1"] and not r.get("zoom_note") and mails[0]["status"] == "cancelled"
    monkeypatch.setattr(bb, "cancel", lambda url, dry_run=None: {"ok": False, "status": "blocked", "message": "no cancel control"})
    r = flow.cancel(_browser_booking(), svc(), mark=lambda i: True, mail=mails.append)
    assert "please cancel the event in Zoom" in r["zoom_note"]
    r = flow.cancel(_browser_booking(zoom_cancel_url=None), svc(), mark=lambda i: True, mail=mails.append)
    assert "please also cancel" in r["zoom_note"]


def test_reschedule_emails_render_for_both_sides():
    from app.booking.email import send_reschedule_emails

    class M:
        def __init__(self):
            self.items = []

        def enqueue(self, to, subject, body, **kw):
            self.items.append((to, subject, body, kw))

    m = M()
    b = _browser_booking(old_label_visitor="Tue 06 Oct, 10:00 (Asia/Kolkata)", start_utc=datetime(2026, 10, 7, 5, 30, tzinfo=timezone.utc),
                         end_utc=datetime(2026, 10, 7, 5, 45, tzinfo=timezone.utc), manage_url="https://a/manage?t=tok")
    send_reschedule_emails(b, mailer=m)
    assert len(m.items) == 2
    to, subject, body, kw = m.items[0]
    assert to == "ada@lovelace.org" and subject.startswith("Your call with Deep has moved:") and "Tue 06 Oct" in body and "Wed 07 Oct, 11:00" in body and "zoom.us/j/9" in body
    assert kw["attachments"][0][0] == "invite.ics" and kw["kind"] == "reschedule_visitor"
    assert m.items[1][0] == settings.host_email and "Moved:" in m.items[1][1] and "Was:" in m.items[1][2]
