"""The Ledger HTML of the lifecycle emails (#3-#13 and the Send test kinds), through the real send functions:
state-accurate pills and copy, the right buttons for the right people, no meeting link while pending or cancelled,
time zones, escaping, every link of the text part still clickable, and the simple-card fallback."""
from __future__ import annotations

import html as H
import re
from datetime import datetime, timedelta, timezone

import pytest

from app import precall, templates
from app.booking import email as mail
from app.booking import email_html as E
from app.config import settings
from tests.email_golden import BRIEF, HANDOFF, SETTINGS, capture

GUESTS = [{"name": "Charles Babbage", "email": "charles@babbage.org"}, {"name": "Mary Somerville", "email": "mary@somerville.org"}]
CONF = dict(templates.SAMPLE_BOOKING, manage_token="Tok", attendees=GUESTS)
PEND = dict(CONF, method="handoff", status="pending_zoom", zoom_meeting_id=None, meeting_id=None, join_url="", passcode="", handoff_url=HANDOFF)
JOIN = CONF["join_url"]


class M:
    def __init__(self):
        self.items = []

    def enqueue(self, to, subject, body, **kw):
        self.items.append((to, subject, body, kw))

    def one(self, kind, to=None):
        return next(x for x in self.items if x[3]["kind"] == kind and (to is None or x[0] == to))


@pytest.fixture(autouse=True)
def _pinned(monkeypatch):
    for k, v in SETTINGS.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(templates, "get_templates", lambda: dict(templates.DEFAULTS))


def text(h: str) -> str:
    """What a reader sees: tags, head and the preheader filler removed."""
    body = h.split("<body", 1)[1]
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", body.replace("&#847;&zwnj;&nbsp;", ""))))


def never_confirmed(h: str) -> bool:
    return "confirmed" not in text(h).lower().replace("confirmation", "")


def ledger(h: str) -> bool:
    return 'class="card dm-card"' in h and "#F28C28" not in h and h.count("<img") == 1 and "logo.png" in h   # the logo only


def pills(h: str) -> list[str]:
    return re.findall(r'class="(st-[a-z]+)"', h)


# ---------------------------------------------------------------- #3 #4 #12 cancelled
def test_cancelled_emails_are_calm_have_no_join_link_and_the_right_buttons():
    m = M()
    mail.send_cancel_emails(dict(CONF, status="cancelled", zoom_note="Cancelled here; please also cancel the event in Zoom Scheduler."), mailer=m)
    v, h, g = m.one("cancel_visitor")[3]["html"], m.one("cancel_host")[3]["html"], m.one("attendee_cancelled", "charles@babbage.org")[3]["html"]
    for x in (v, h, g):
        assert ledger(x) and pills(x) == ["st-off"] and ">Cancelled</span>" in x and "line-through" not in x
        assert JOIN not in x and "Join meeting" not in x and "Join Zoom" not in x and "Passcode" not in x
        assert "color:#6B6B6B;mso-line-height-rule:exactly;text-transform:uppercase" in x   # the tile's month greyed out
        assert "Add to calendar" not in x
    assert "Your call with Deep is cancelled" in v and "Thanks for letting us know." in v and "Wed, 07 Oct 2026" in v and "9:30 AM EDT" in v
    assert v.count('href="https://www.example.com"') == 2 and "Book a new time" in v      # VML + link
    assert 'href="https://scheduler.zoom.us/sreedeep"' in v                              # the booking link in the text, still a link
    assert "Cancelled by the visitor." in h and "Ada Lovelace" in h and 'href="mailto:ada@lovelace.org"' in h
    assert "7:00 PM IST" in h and "Cancelled here; please also cancel the event in Zoom Scheduler." in h   # host time zone + note
    assert "Open booking page" in h and "/host/booking/42?t=" in h and "Book a new time" not in h
    assert "The call Ada Lovelace added you to has been cancelled" in g and "Hi Charles," in g and "Book a new time" not in g
    m = M()
    mail.send_cancel_emails(dict(CONF, status="cancelled", manage_token=None), mailer=m)          # no host page: no button
    assert "Open booking page" not in m.one("cancel_host")[3]["html"] and ">Note<" not in m.one("cancel_host")[3]["html"]


# ---------------------------------------------------------------- #5 #6 #11 moved
def test_moved_emails_show_before_and_after_and_follow_the_pending_state():
    prev = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)
    m = M()
    mail.send_reschedule_emails(dict(CONF, previous_start_utc=prev, old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)"), mailer=m)
    v, h, g = m.one("reschedule_visitor")[3]["html"], m.one("reschedule_host")[3]["html"], m.one("attendee_moved", "charles@babbage.org")[3]["html"]
    for x in (v, h, g):
        assert ledger(x) and pills(x) == ["st-move"] and ">Was<" in x and ">Now<" in x and "border-left:3px solid #F26722" in x
    assert "Tue, 06 Oct 2026" in v and "10:00 AM EDT" in v and "9:30 AM EDT" in v           # visitor time zone, both sides
    assert "7:30 PM IST" in h and "7:00 PM IST" in h and "rescheduled on Zoom Scheduler" in h  # host time zone
    assert v.count(f'href="{H.escape(JOIN)}"') >= 3 and "Join Zoom" in v                     # Join row + button (VML + link)
    assert "Open booking page" in h and "Join Zoom" in h and "/host/booking/42?t=" in h
    assert "The call Ada Lovelace added you to has a new time." in g and "Join Zoom" in g

    m = M()
    mail.send_reschedule_emails(dict(PEND, old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)"), mailer=m)
    v, h, g = m.one("reschedule_visitor")[3]["html"], m.one("reschedule_host")[3]["html"], m.one("attendee_moved", "charles@babbage.org")[3]["html"]
    for x in (v, h, g):
        assert pills(x) == ["st-move", "st-wait"] and never_confirmed(x) and "zoom.us/j/" not in x and "Join" not in text(x)
        assert "Tue 06 Oct, 10:00 (America/New_York)" in x                                   # the old time from the text part
    assert v.count(f'href="{H.escape(HANDOFF)}"') >= 3 and "Confirm on Zoom" in v              # the note's link + the button
    assert HANDOFF not in h and H.escape(HANDOFF) not in h and "held, waiting for the visitor to confirm on Zoom" in h
    assert "Open booking page" in h and "Join Zoom" not in h


# ---------------------------------------------------------------- #7 #13 reminder
def test_reminder_pill_follows_the_dates_and_the_button_the_state():
    now = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)            # 11:00 in New York, the call is tomorrow 09:30
    s, b = templates.render_booking_visitor(dict(CONF, status="reminder", booking_status="confirmed"))
    h = E.render_reminder(CONF, s, b, now=now, pending=False, actions=[("Join Zoom", JOIN)])
    assert ledger(h) and pills(h) == ["st-soon"] and ">Tomorrow</span>" in h and "Join Zoom" in h and "is tomorrow</h1>" in h
    assert "A quick reminder that your LakeB2B Discovery Call with Deep is tomorrow." in h
    assert ">Today</span>" in E.render_reminder(CONF, s, b, now=now + timedelta(hours=20), pending=False, actions=[])
    assert ">Upcoming</span>" in E.render_reminder(CONF, s, b, now=now - timedelta(days=3), pending=False, actions=[])
    m = M()
    mail.send_reminder_email(dict(PEND), mailer=m)
    v, g = m.one("reminder_visitor")[3]["html"], m.one("attendee_reminder", "mary@somerville.org")[3]["html"]
    assert pills(v)[1:] == ["st-wait"] and "Confirm on Zoom" in v and never_confirmed(v) and "zoom.us/j/" not in v
    assert pills(g)[1:] == ["st-wait"] and "Join Zoom" not in g and "The time is held" not in g    # guest reminder text has no held line
    m = M()
    mail.send_reminder_email(dict(CONF, join_url="", zoom_meeting_id=None, passcode="", method="scheduler"), mailer=m)
    v = m.one("reminder_visitor")[3]["html"]
    assert "v:roundrect" not in v and "Join Zoom" not in v and "Join meeting" not in v                # nothing to join: no button
    m = M()
    mail.send_reminder_email(dict(CONF), mailer=m)
    g = m.one("attendee_reminder", "charles@babbage.org")[3]["html"]
    assert "Join Zoom" in g and "With Ada Lovelace, Mary Somerville" in text(g) and ">Guests<" not in g


# ---------------------------------------------------------------- #8 the host's brief
def test_host_day_before_brief_agrees_with_its_subject_and_carries_the_brief(monkeypatch):
    monkeypatch.setattr(precall, "build_for_booking", lambda booking, refresh=False, ask=None, save=True, **k: dict(BRIEF))
    for hours, word in ((22, "Tomorrow"), (3, "Today")):
        m = M()
        start = datetime.now(timezone.utc) + timedelta(hours=hours)
        precall.send_host_reminder(dict(CONF, start_utc=start, end_utc=start + timedelta(minutes=15)), mailer=m)
        to, subject, body, kw = m.items[0]
        h = kw["html"]
        assert ledger(h) and f">{word}</span>" in h and ("today" in subject) == (word == "Today")
        assert f"is {word.lower()}</h1>" in h and "PRE-CALL BRIEF" in h and "WHY THIS SCORE" in h and "<ul" in h and "#257A4D" in h
        assert ">Visitor time<" in h and "EDT" in h and "IST" in h                                  # both time zones
        assert "Open booking page" in h and "Join Zoom" in h and 'href="mailto:ada@lovelace.org"' in h
        assert h.index("Open booking page") < h.index("PRE-CALL BRIEF")                            # the buttons above the brief
    m = M()
    precall.send_host_reminder(dict(PEND, manage_token=None), mailer=m)
    h = m.items[0][3]["html"]
    assert "Open booking page" not in h and "Join Zoom" not in h and "st-wait" in h and HANDOFF not in h


# ---------------------------------------------------------------- #9 the unconfirmed-hold reminder
def test_nudge_gets_an_html_part_with_the_wanted_time_and_the_same_prefilled_link(monkeypatch):
    from app import nudge
    from app.booking.zoom import Schedule

    sent = []
    monkeypatch.setattr(mail, "_send", lambda to, subject, body, reply_to=None, html=None, attachments=None: sent.append((subject, body, html)) or True)
    row = {"id": 1, "ts": datetime.now(timezone.utc), "name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "demo",
           "slot_start": datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc), "visitor_tz": "America/New_York",
           "schedule_slug": "discovery-call", "company": None, "session_id": None}
    lead = nudge.lead_for_email(row, [Schedule(slug="discovery-call", id="x", name="LakeB2B Discovery Call", duration_min=15,
                                               booking_link="https://scheduler.zoom.us/sreedeep/discovery-call")])
    assert mail.send_visitor_confirmation(lead)
    subject, body, h = sent[0]
    assert ledger(h) and pills(h) == ["st-wait"] and "LakeB2B Discovery Call" in h and "Thu, 08 Oct 2026" in h and "8:00 AM EDT" in h
    assert h.count(f'href="{H.escape(lead["handoff_url"])}"') >= 3 and "Confirm on Zoom" in h and never_confirmed(h)
    assert "wasn&#x27;t completed" in h and "Your time isn’t reserved yet</h1>" in h
    for status in ("handoff", "handover"):                                  # the other callers stay text only
        sent.clear()
        mail.send_visitor_confirmation(dict(templates.SAMPLE_LEAD, status=status))
        assert sent[0][2] is None


# ---------------------------------------------------------------- #10 guests
def test_guest_invitation_is_written_to_the_guest_and_follows_the_state():
    for b, pending in ((CONF, False), (PEND, True)):
        m = M()
        mail.send_booking_emails(dict(b), mailer=m)
        g = m.one("attendee_booked", "mary@somerville.org")
        h = g[3]["html"]
        assert ledger(h) and pills(h) == (["st-inv", "st-wait"] if pending else ["st-inv"]) and ">Invitation</span>" in h
        assert "invited you to a call with Deep</h1>" in h and "/ics?t=" not in h        # a guest never gets the booker's token
        assert "Hi Mary," in h and "Ada Lovelace added you to a call with Deep." in h and "With Ada Lovelace, Charles Babbage" in text(h)
        assert "Your booking" not in h and "View booking details" not in h and CONF["manage_url"] not in h and "/host/booking" not in h
        assert g[3]["attachments"][0][0] == "invite.ics"
        if pending:
            assert "The time is held while it is confirmed on Zoom" in h and 'class="st-wait"' in h
            assert never_confirmed(h.replace("while it is confirmed on Zoom", ""))           # the held line is the only "confirmed"
            assert "Join" not in text(h) and "zoom.us/j/" not in h
        else:
            assert "Join Zoom" in h and f'href="{H.escape(JOIN)}"' in h and "Passcode 742913" in h


def test_guest_and_booker_values_are_escaped_and_unsafe_links_dropped():
    evil = dict(CONF, name="<b>Eve</b>", join_url="javascript:alert(1)",
                attendees=[{"name": '"><script>x</script>', "email": "ev<il>@x.org"}, {"name": "Ok", "email": "ok@x.org"}])
    m = M()
    mail.send_booking_emails(evil, mailer=m)
    mail.send_reschedule_emails(dict(evil, old_label_visitor="<i>then</i>"), mailer=m)
    mail.send_cancel_emails(dict(evil, status="cancelled"), mailer=m)
    mail.send_reminder_email(dict(evil), mailer=m)
    for to, subject, body, kw in m.items:
        h = kw["html"]
        assert "<script>" not in h and "<b>Eve" not in h and "<i>then" not in h and 'href="javascript:' not in h, kw["kind"]
        assert 'href="mailto:ev<il>' not in h and "javascript:alert" not in re.findall(r'href="([^"]*)"', h)
    assert any("&lt;b&gt;Eve&lt;/b&gt;" in kw["html"] for *_, kw in m.items)


# ---------------------------------------------------------------- every path: links, placeholders, size, fallback
def test_every_link_in_the_text_part_is_clickable_in_the_html_and_nothing_leaks(monkeypatch):
    sink: list[dict] = []
    out = [e for e in capture(monkeypatch.setattr, html_sink=sink) if e["via"] != "return"]
    assert len(out) == len(sink)
    for e, s in zip(out, sink):
        h = s["html"]
        if not h or "dm-card" not in h:
            continue
        # visitor and guest HTML leave out the text part's manage link (2026-10-15: the Ask Deep panel moves or cancels
        # the call); the host emails keep every link
        skip_manage = not ((s["kind"] or "").endswith("_host") or e["case"] == "send_test:host_booking")
        hrefs = {H.unescape(u) for u in re.findall(r'href="([^"]+)"', h)}
        if skip_manage:
            assert not any("/manage" in u for u in hrefs), (e["case"], e["to"])
        for url in re.findall(r"https?://[^\s<>\"']+", e["body"]):
            url = url.rstrip(".,;:!?)")
            if skip_manage and "/manage" in url:
                continue
            if E.safe_url(url) and not (url == JOIN and ("pending" in e["case"] or "cancel" in e["case"])):
                assert url in hrefs, (e["case"], e["to"], url)
        seen = text(h)
        assert "None" not in seen and not re.search(r"\{[a-z_]+\}", seen), (e["case"], e["to"])
        assert len(h.encode()) < 100_000 and h.count("<style>") == 2
        css = "".join(re.findall(r"<style>(.*?)</style>", h, flags=re.S))
        assert len(css.encode()) < 3000
        pre = re.search(r"<body[^>]*>\s*<div[^>]*>(.*?)</div>", h, flags=re.S).group(1)
        assert pre.strip(), (e["case"], "preheader")
        assert "Champions Group" in h                                     # the brand from brand_default


def test_a_failing_render_falls_back_to_the_simple_card_and_the_mail_still_goes(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    for name in ("render_cancelled", "render_moved", "render_reminder", "render_host_brief", "render_nudge", "render_guest"):
        monkeypatch.setattr(E, name, boom)
    monkeypatch.setattr(precall, "build_for_booking", lambda *a, **k: dict(BRIEF))
    m = M()
    mail.send_cancel_emails(dict(CONF, status="cancelled"), mailer=m)
    mail.send_reschedule_emails(dict(PEND, old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)"), mailer=m)
    mail.send_reminder_email(dict(CONF), mailer=m)
    precall.send_host_reminder(dict(CONF), mailer=m)
    kinds = {x[3]["kind"] for x in m.items}
    assert {"cancel_visitor", "cancel_host", "attendee_cancelled", "reschedule_visitor", "reschedule_host", "attendee_moved",
            "reminder_visitor", "attendee_reminder", "precall_host"} <= kinds
    for to, subject, body, kw in m.items:
        assert kw["html"] and "#F28C28" in kw["html"] and "dm-card" not in kw["html"], kw["kind"]   # templates.html_wrap
    assert "Book a new time" in m.one("cancel_visitor")[3]["html"] and "Confirm on Zoom" in m.one("reschedule_visitor")[3]["html"]
    sent = []
    monkeypatch.setattr(mail, "_send", lambda to, subject, body, reply_to=None, html=None, attachments=None: sent.append(html) or True)
    assert mail.send_visitor_confirmation(dict(templates.SAMPLE_LEAD, status="nudge")) and "#F28C28" in sent[0]


def test_send_test_kinds_use_the_new_design(monkeypatch):
    seen = {}
    monkeypatch.setattr(mail, "_send", lambda to, subject, body, reply_to=None, html=None, attachments=None: seen.update(html=html) or True)
    want = {"host_booking": "New booking confirmed", "visitor_confirmed": "Your call with Deep is confirmed",
            "visitor_cancelled": "is cancelled", "visitor_rescheduled": "has moved", "visitor_reminder": "A quick reminder",
            "visitor_nudge": "Your time isn’t reserved yet"}
    for kind, words in want.items():
        assert mail.send_test(kind)["ok"]
        assert ledger(seen["html"]) and words in seen["html"], kind
    assert "Book a new time" in (mail.send_test("visitor_cancelled") and seen["html"])
    for kind in ("host", "visitor_booking", "visitor_handover"):
        mail.send_test(kind)
        assert seen["html"] is None, kind
