"""Extra attendees on a booking: validation, hand-off to Zoom (browser worker and Meetings API), storage, the calendar
invite, the host/visitor emails and one notice per guest for booked / moved / cancelled / reminder."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import respx

from app import templates
from app.booking import browser_booking as bb
from app.booking import flow, ics
from app.booking.email import attendee_notice, send_attendee_emails, send_booking_emails, send_cancel_emails, send_reminder_email, send_reschedule_emails
from app.booking.zoom import ZOOM_API, ZOOM_OAUTH, ZoomOfficialClient
from app.config import settings
from tests.test_browser_booking import SCHED, req, svc
from tests.test_booking import avail_url, mock_schedules
from tests.test_inchat_booking import FakeDeps, week_spots

GUESTS = [{"name": "Charles Babbage", "email": "charles@babbage.org"}, {"name": "Mary Somerville", "email": "mary@somerville.org"}]


class M:
    def __init__(self):
        self.items = []

    def enqueue(self, to, subject, body, **kw):
        self.items.append((to, subject, body, kw))


def test_clean_attendees_validates_dedupes_and_caps():
    ok, err = flow.clean_attendees(GUESTS + [{"name": "", "email": ""}], "ada@lovelace.org")
    assert err is None and ok == GUESTS
    assert flow.clean_attendees([{"name": "C", "email": "c@x.org"}], "ada@lovelace.org")[1] == "Please add a name for every attendee."
    assert "doesn't look right" in flow.clean_attendees([{"name": "Charles", "email": "charles@"}], "ada@lovelace.org")[1]
    assert "your own email" in flow.clean_attendees([{"name": "Me Again", "email": "ADA@lovelace.org"}], "ada@lovelace.org")[1]
    assert "added twice" in flow.clean_attendees(GUESTS + [{"name": "Charles B", "email": "Charles@Babbage.org"}], "ada@lovelace.org")[1]
    six = [{"name": f"Guest {i}", "email": f"guest{i}@babbage.org"} for i in range(6)]
    assert "up to 5" in flow.clean_attendees(six, "ada@lovelace.org")[1]
    assert flow.clean_attendees(None, "ada@lovelace.org") == ([], None)


@respx.mock
def test_confirm_passes_guests_to_the_worker_and_stores_them(monkeypatch):
    mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
    monkeypatch.setattr(bb, "available", lambda: True)
    seen = {}

    def fake_book(url, start_utc, name, email, notes, dry_run=None, attendees=None):
        seen["attendees"] = attendees
        return {"ok": True, "status": "booked", "links": {"join": "https://zoom.us/j/9"}, "attendees_on_zoom": attendees}

    monkeypatch.setattr(bb, "book", fake_book)
    d = FakeDeps()
    r = req(); r.attendees = GUESTS + [{"name": "", "email": ""}]
    res = flow.confirm(svc(), r, d.deps)
    assert res["status"] == "confirmed" and seen["attendees"] == ["charles@babbage.org", "mary@somerville.org"]
    assert d.bookings[0]["attendees"] == GUESTS and res["booking"]["attendees"] == GUESTS
    r2 = req(); r2.attendees = [{"name": "Ada Again", "email": "ada@lovelace.org"}]
    bad = flow.confirm(svc(), r2, FakeDeps().deps)
    assert bad["status"] == "invalid" and "your own email" in bad["message"]


@respx.mock
def test_meetings_api_invites_every_guest():
    respx.post(url__startswith=ZOOM_OAUTH).mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600}))
    route = respx.post(f"{ZOOM_API}/users/host@x.org/meetings").mock(return_value=httpx.Response(201, json={"id": 1, "join_url": "https://zoom.us/j/1"}))
    c = ZoomOfficialClient(httpx.Client())
    c._token, c._token_exp = "t", 1e12  # skip the OAuth round trip
    c.create_meeting("host@x.org", "T", datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc), 15, "", "ada@lovelace.org", guests=["charles@babbage.org"])
    body = json.loads(route.calls[0].request.content)
    assert body["settings"]["meeting_invitees"] == [{"email": "ada@lovelace.org"}, {"email": "charles@babbage.org"}]


def test_runner_payload_carries_guest_emails(monkeypatch):
    sent = {}
    monkeypatch.setattr(bb, "run", lambda task, payload, timeout=None: sent.update(payload) or {"ok": True, "status": "booked"})
    bb.book("https://scheduler.zoom.us/x", datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc), "Ada Lovelace", "ada@lovelace.org", "", attendees=["charles@babbage.org"])
    assert sent["attendees"] == ["charles@babbage.org"]
    bb.book("https://scheduler.zoom.us/x", datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc), "Ada Lovelace", "ada@lovelace.org", "")
    assert sent["attendees"] == []


def test_worker_goal_keeps_the_guests():
    spec = importlib.util.spec_from_file_location("zw", Path(__file__).resolve().parent.parent / "scripts" / "zoom_browser_worker.py")
    w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)  # type: ignore[union-attr]
    start = w.parse_start("2026-10-15T11:00:00+00:00", "Asia/Kolkata")
    g = w.build_goal("book", {"first_name": "Ada", "last_name": "L", "email": "ada@lovelace.org", "attendees": ["c@b.org"]}, start, dry_run=False)
    assert "already added; leave them" in g
    assert "already added" not in w.build_goal("book", {"first_name": "Ada", "last_name": "L", "email": "ada@lovelace.org"}, start, dry_run=False)


def test_invite_and_booking_emails_name_every_guest():
    b = dict(templates.SAMPLE_BOOKING, attendees=GUESTS)
    cal = ics.build(b, "Deep")
    assert "ATTENDEE;CN=Charles Babbage;ROLE=REQ-PARTICIPANT:mailto:charles@babbage.org" in cal and "mailto:mary@somerville.org" in cal
    m = M()
    send_booking_emails(b, mailer=m)
    tos = [x[0] for x in m.items]
    assert tos[:2] == ["ada@lovelace.org", settings.host_email] and tos[2:] == ["charles@babbage.org", "mary@somerville.org"]
    assert "Guests:   Charles Babbage <charles@babbage.org>, Mary Somerville <mary@somerville.org>" in m.items[0][2]  # visitor copy
    assert "Guests:   Charles Babbage" in m.items[1][2]                                                             # host copy
    subject, body, kw = m.items[2][1], m.items[2][2], m.items[2][3]
    assert subject.startswith("Ada Lovelace invited you: LakeB2B Discovery Call with Deep on") and body.startswith("Hi Charles,")
    assert "With:     Ada Lovelace, Mary Somerville" in body and kw["attachments"][0][0] == "invite.ics" and kw["kind"] == "attendee_booked"
    # no guests: exactly the two emails as before, and no empty Guests line
    m = M()
    send_booking_emails(dict(templates.SAMPLE_BOOKING, attendees=[]), mailer=m)
    assert len(m.items) == 2 and "Guests:" not in m.items[0][2]


def test_guests_hear_about_moves_cancels_and_reminders():
    b = dict(templates.SAMPLE_BOOKING, attendees=GUESTS[:1])
    m = M()
    send_reschedule_emails(dict(b, old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)"), mailer=m)
    g = [x for x in m.items if x[0] == "charles@babbage.org"]
    assert len(g) == 1 and g[0][1].startswith("Moved:") and "Was:      Tue 06 Oct, 10:00" in g[0][2] and g[0][3]["attachments"]
    m = M()
    send_cancel_emails(dict(b, status="cancelled"), mailer=m)
    g = [x for x in m.items if x[0] == "charles@babbage.org"]
    assert len(g) == 1 and g[0][1].startswith("Cancelled:") and "has been cancelled" in g[0][2]
    m = M()
    assert send_reminder_email(b, mailer=m) is True
    g = [x for x in m.items if x[0] == "charles@babbage.org"]
    assert len(g) == 1 and g[0][1].startswith("Reminder:") and "is tomorrow" in g[0][2]
    s, body, cta = attendee_notice(dict(b, status="pending_zoom", method="handoff", join_url=""), GUESTS[0], "booked")
    assert "held while it is confirmed on Zoom" in body and cta is None
    assert send_attendee_emails(dict(b, attendees=[]), "booked", mailer=M()) == 0
