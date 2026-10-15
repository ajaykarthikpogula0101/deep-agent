"""The Zoom join link for browser bookings, read from Zoom's own invitation (app/booking/zoom_mail.py): parsing,
matching a message to a booking, the IMAP read, the deferred confirmation emails, the worker's extra attendee and
the backfill job. No real mailbox is ever opened."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

from app import templates
from app.booking import browser_booking as bb
from app.booking import email_html as E
from app.booking import flow, zoom_mail
from app.config import settings
from tests.test_booking import avail_url, mock_schedules
from tests.test_booking_email_html import CONFIRMED, NOW
from tests.test_browser_booking import SCHED, req, svc
from tests.test_inchat_booking import FakeDeps, week_spots

JOIN = "https://us06web.zoom.us/j/81234567890?pwd=aBcD1234efGh5678.1"
START = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)  # 19:30 in Kolkata


def invitation(start_local="20261020T193000", tzid="Asia/Kolkata", method="REQUEST", subject=None, date="Thu, 15 Oct 2026 10:00:05 +0000",
               calendar=True, booker="rahul@example.com"):
    """Zoom Scheduler's invitation as Google Calendar sends it for the host's calendar: text, HTML and the .ics."""
    m = EmailMessage()
    m["From"] = "Sreedeep Surapaneni <deep1499@gmail.com>"
    m["To"] = "bookings@example.com"
    m["Date"] = date
    m["Subject"] = subject or "Invitation: GTM Strategy Session with Sreedeep Surapaneni @ Tue Oct 20, 2026 7:30pm - 8:15pm (IST)"
    m.set_content(f"Sreedeep Surapaneni is inviting you to a scheduled Zoom meeting.\n\nJoin Zoom Meeting\n{JOIN}\n\n"
                  f"Meeting ID: 812 3456 7890\nPasscode: 742913\n\nGuests: {booker}\n")
    m.add_alternative(f'<p>Join Zoom Meeting<br><a href="https://www.google.com/url?q={JOIN.replace(":", "%3A").replace("/", "%2F")}&amp;sa=D">'
                      f'{JOIN}</a></p><p>Meeting ID: 812 3456 7890<br>Passcode: 742913</p>', subtype="html")
    if calendar:
        ics = ("BEGIN:VCALENDAR\r\nPRODID:-//Google Inc//Google Calendar 70.9054//EN\r\nVERSION:2.0\r\n"
               f"METHOD:{method}\r\nBEGIN:VEVENT\r\nDTSTART;TZID={tzid}:{start_local}\r\nDTEND;TZID={tzid}:20261020T201500\r\n"
               f"DESCRIPTION:Join Zoom Meeting\\n{JOIN[:40]}\r\n {JOIN[40:]}\\n\\nMeeting ID: 812 3456 7890\\nPasscode: 742913\r\n"
               f"LOCATION:{JOIN}\r\nSTATUS:{'CANCELLED' if method == 'CANCEL' else 'CONFIRMED'}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        m.add_attachment(ics.encode(), maintype="text", subtype="calendar", filename="invite.ics")
    return m.as_bytes()


BOOKING = {"id": 7, "method": "browser", "status": "confirmed", "email": "rahul@example.com", "start_utc": START,
           "created_at": datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc), "join_url": None}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "zoom_link_from_email", True)
    monkeypatch.setattr(settings, "zoom_link_mailbox", "bookings@example.com")
    monkeypatch.setattr(settings, "zoom_link_imap_password", "app-password")
    monkeypatch.setattr(zoom_mail, "POLL_SECONDS", 0)


def test_parse_reads_the_link_meeting_id_passcode_and_start():
    info = zoom_mail.parse(invitation())
    assert info["join_url"] == JOIN and info["meeting_id"] == "812 3456 7890" and info["passcode"] == "742913"
    assert info["start_utc"] == START and info["cancelled"] is False
    assert info["received"] == datetime(2026, 10, 15, 10, 0, 5, tzinfo=timezone.utc)


def test_parse_without_meeting_id_line_groups_the_url_digits_and_utc_starts():
    raw = invitation(start_local="20261020T140000Z", tzid="").replace(b"DTSTART;TZID=:", b"DTSTART:")
    assert zoom_mail.parse(raw)["start_utc"] == START
    assert zoom_mail.format_meeting_id("81234567890") == "812 3456 7890" and zoom_mail.format_meeting_id("8123456789") == "812 345 6789"
    m = EmailMessage(); m.set_content("Join: https://zoom.us/j/912345678")
    assert zoom_mail.parse(m.as_bytes())["meeting_id"] == "912 345 678"


def test_matching_needs_the_same_start_a_live_invite_and_a_recent_message():
    assert zoom_mail.matches(zoom_mail.parse(invitation()), BOOKING, after=BOOKING["created_at"])
    assert not zoom_mail.matches(zoom_mail.parse(invitation(start_local="20261020T200000")), BOOKING)       # another call
    assert not zoom_mail.matches(zoom_mail.parse(invitation(method="CANCEL")), BOOKING)                     # a cancellation
    assert not zoom_mail.matches(zoom_mail.parse(invitation(subject="Canceled event: GTM")), BOOKING)
    old = zoom_mail.parse(invitation(date="Wed, 14 Oct 2026 09:00:00 +0000"))
    assert not zoom_mail.matches(old, BOOKING, after=BOOKING["created_at"])                                 # before the booking
    assert zoom_mail.parse(invitation())["from"] == "deep1499@gmail.com"
    bare = zoom_mail.parse(invitation(calendar=False))                                                      # no calendar part:
    assert zoom_mail.matches(bare, BOOKING) and not zoom_mail.matches(bare, dict(BOOKING, email="other@example.com"))  # the booker named


def test_our_own_booking_emails_never_count(on, monkeypatch):
    """The host copy of our confirmation lands in the same mailbox with a Zoom link and an .ics at the same start."""
    monkeypatch.setattr(settings, "email_from", "assistant@example.com")
    for sender in ("bookings@example.com", "Assistant@Example.com"):
        info = zoom_mail.parse(invitation().replace(b"Sreedeep Surapaneni <deep1499@gmail.com>", f"Deep <{sender}>".encode()))
        assert info["join_url"] == JOIN and not zoom_mail.matches(info, BOOKING)


class FakeIMAP:
    calls: list = []
    boxes: dict = {}

    def __init__(self, host, timeout=None):
        FakeIMAP.calls.append(("connect", host))

    def login(self, user, pw):
        FakeIMAP.calls.append(("login", user, pw))

    def select(self, folder, readonly=False):
        FakeIMAP.calls.append(("select", folder, readonly))
        self.folder = folder
        return ("OK", [b"1"]) if folder in FakeIMAP.boxes else ("NO", [b""])

    def search(self, charset, query):
        FakeIMAP.calls.append(("search", query))
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(FakeIMAP.boxes[self.folder])))]

    def fetch(self, i, what):
        FakeIMAP.calls.append(("fetch", i, what))
        return "OK", [(b"1", FakeIMAP.boxes[self.folder][int(i) - 1])]

    def logout(self):
        FakeIMAP.calls.append(("logout",))


def test_find_reads_the_mailbox_read_only_newest_first(on, monkeypatch):
    other = invitation(start_local="20261021T100000")
    FakeIMAP.calls, FakeIMAP.boxes = [], {"INBOX": [invitation(), other]}
    monkeypatch.setattr(zoom_mail.imaplib, "IMAP4_SSL", FakeIMAP)
    info = zoom_mail.find(BOOKING)
    assert info and info["join_url"] == JOIN
    assert ("login", "bookings@example.com", "app-password") in FakeIMAP.calls and ("select", "INBOX", True) in FakeIMAP.calls
    assert ("search", '(SINCE 14-Oct-2026 BODY "zoom.us/j/")') in FakeIMAP.calls
    fetched = [c[1] for c in FakeIMAP.calls if c[0] == "fetch"]
    assert fetched == [b"2", b"1"] and all(c[2] == "(BODY.PEEK[])" for c in FakeIMAP.calls if c[0] == "fetch")   # never marks read
    assert FakeIMAP.calls[-1] == ("logout",)
    FakeIMAP.boxes = {'"[Gmail]/All Mail"': [invitation()]}                                                   # archived: All Mail
    assert zoom_mail.find(BOOKING)["join_url"] == JOIN


def test_find_never_raises(on, monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(zoom_mail.imaplib, "IMAP4_SSL", boom)
    assert zoom_mail.find(BOOKING) is None


def test_settings_fall_back_to_the_smtp_account(monkeypatch):
    monkeypatch.setattr(settings, "zoom_link_from_email", True)
    monkeypatch.setattr(settings, "zoom_link_mailbox", "")
    monkeypatch.setattr(settings, "zoom_link_imap_password", "")
    monkeypatch.setattr(settings, "smtp_user", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_password", "pw")
    assert zoom_mail.mailbox() == "sender@example.com" and zoom_mail.enabled()
    monkeypatch.setattr(settings, "smtp_password", "")
    assert not zoom_mail.enabled() and zoom_mail.extra_attendee("a@x.org", []) == []
    monkeypatch.setattr(settings, "smtp_password", "pw")
    monkeypatch.setattr(settings, "zoom_link_from_email", False)
    assert not zoom_mail.enabled()


def test_extra_attendee_skips_the_booker_and_guests(on):
    assert zoom_mail.extra_attendee("ada@lovelace.org", ["c@b.org"]) == ["bookings@example.com"]
    assert zoom_mail.extra_attendee("Bookings@Example.com", []) == []
    assert zoom_mail.extra_attendee("ada@lovelace.org", ["bookings@example.com"]) == []


def test_after_booking_sends_at_once_when_there_is_nothing_to_wait_for(on, monkeypatch):
    monkeypatch.setattr(zoom_mail, "find", lambda *a, **k: pytest.fail("no lookup"))
    for b in (dict(BOOKING, method="handoff"), dict(BOOKING, join_url="https://zoom.us/j/1")):
        sent = []
        assert zoom_mail.after_booking(b, sent.append) is False and sent == [b]
    monkeypatch.setattr(settings, "zoom_link_from_email", False)
    sent = []
    assert zoom_mail.after_booking(dict(BOOKING), sent.append) is False and len(sent) == 1


def _run_deferred(booking, monkeypatch, found):
    stored, done = [], threading.Event()
    monkeypatch.setattr(zoom_mail, "find", lambda b, after=None: found)
    monkeypatch.setattr("app.store_bookings.set_zoom_link", lambda *a: stored.append(a) or True)
    sent = []
    assert zoom_mail.after_booking(booking, lambda b: (sent.append(dict(b)), done.set())) is True
    assert done.wait(5)
    return sent, stored


def test_after_booking_waits_for_the_link_then_sends_with_it(on, monkeypatch):
    b = dict(BOOKING)
    sent, stored = _run_deferred(b, monkeypatch, zoom_mail.parse(invitation()))
    assert sent[0]["join_url"] == JOIN and sent[0]["meeting_id"] == "812 3456 7890" and sent[0]["passcode"] == "742913"
    assert stored == [(7, JOIN, "812 3456 7890", "742913")]


def test_after_booking_sends_without_the_link_when_none_arrives(on, monkeypatch):
    monkeypatch.setattr(settings, "zoom_link_wait_seconds", 0)
    sent, stored = _run_deferred(dict(BOOKING), monkeypatch, None)
    assert len(sent) == 1 and not sent[0]["join_url"] and stored == []


def test_the_confirmation_gets_the_join_button_and_phone_row_once_the_link_is_in():
    b = dict(CONFIRMED, method="browser", join_url=None, meeting_id=None, zoom_meeting_id=None, passcode=None)
    before = E.render(b, "visitor", dict(templates.DEFAULTS), now=NOW)
    assert "Join Zoom meeting" not in before and "zoomconference" not in before and "Zoom sends the meeting link" in before
    zoom_mail.store(b, zoom_mail.parse(invitation()))  # no id: nothing written
    after = E.render(b, "visitor", dict(templates.DEFAULTS), now=NOW)
    assert "Join Zoom meeting" in after and JOIN in after and "zoomconference" in after and "812 3456 7890" in after


def test_confirm_adds_the_mailbox_on_zoom_and_defers_the_emails(on, monkeypatch):
    import respx
    import httpx

    with respx.mock:
        mock_schedules(); respx.get(url__startswith=avail_url(SCHED.slug)).mock(return_value=httpx.Response(200, json=week_spots()))
        monkeypatch.setattr(bb, "available", lambda: True)
        seen, deferred = {}, []
        monkeypatch.setattr(bb, "book", lambda url, start_utc, name, email, notes, dry_run=None, attendees=None:
                            seen.update(attendees=attendees) or {"ok": True, "status": "booked", "links": {}})
        monkeypatch.setattr(zoom_mail, "after_booking", lambda b, mail: deferred.append(b) or True)
        d = FakeDeps()
        res = flow.confirm(svc(), req(), d.deps)
    assert res["status"] == "confirmed" and seen["attendees"] == ["bookings@example.com"]
    assert deferred and deferred[0]["method"] == "browser" and d.bookings[0]["attendees"] == []   # not one of the visitor's guests


def test_backfill_stores_late_links(on, monkeypatch):
    rows = [dict(BOOKING, id=1), dict(BOOKING, id=2, start_utc=START + timedelta(days=1))]
    stored = []
    monkeypatch.setattr("app.store_bookings.missing_zoom_link", lambda: rows)
    monkeypatch.setattr("app.store_bookings.set_zoom_link", lambda *a: stored.append(a[0]) or True)
    monkeypatch.setattr(zoom_mail, "_messages", lambda since, limit=25: [invitation()])
    assert zoom_mail.backfill() == 1 and stored == [1]
    monkeypatch.setattr(settings, "zoom_link_from_email", False)
    assert zoom_mail.backfill() == 0
