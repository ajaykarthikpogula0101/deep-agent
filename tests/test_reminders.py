"""Booking lifecycle emails (moved, cancelled, day-before reminder), the reminder job, and the memory greeting after a
reschedule or a cancel. Templates render hermetically; the job and the memory run against Postgres when it is up."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import memory, reminders, templates
from app.booking.email import send_cancel_emails, send_reminder_email, send_reschedule_emails
from app.config import settings


class M:
    def __init__(self):
        self.items = []

    def enqueue(self, to, subject, body, **kw):
        self.items.append((to, subject, body, kw))


def _booking(**over):
    b = dict(templates.SAMPLE_BOOKING)
    b.update(over)
    return b


def test_lifecycle_templates_render_with_greeting_and_next_step():
    r = templates.render_booking_visitor(templates.sample_booking_for("rescheduled"))
    assert r and r[0] == "Your call with Deep has moved: LakeB2B Discovery Call now on Wed 07 Oct, 09:30 (America/New_York)"
    assert "Hi Ada," in r[1] and "Thanks for letting us know" in r[1] and "Was:      Tue 06 Oct, 10:00" in r[1] and "zoom.us/j/81234567890" in r[1]
    assert "Join with the Zoom link above" in r[1] and "See you then," in r[1]
    r = templates.render_booking_visitor(templates.sample_booking_for("cancelled"))
    assert r and r[0].startswith("Your call with Deep is cancelled:") and "always welcome back" in r[1] and "scheduler.zoom.us" in r[1]
    assert "One last step" not in r[1]  # a cancelled booking has no next step
    r = templates.render_booking_visitor(templates.sample_booking_for("reminder"))
    assert r and r[0] == "Reminder: LakeB2B Discovery Call with Deep tomorrow, Wed 07 Oct, 09:30 (America/New_York)"
    assert "is tomorrow" in r[1] and "Looking forward to it," in r[1] and "Join with the Zoom link above" in r[1]
    # a pending hold keeps its confirm-on-Zoom next step
    b = dict(templates.sample_booking_for("reminder"), booking_status="pending_zoom", handoff_url="https://scheduler.zoom.us/x?prefill=1")
    r = templates.render_booking_visitor(b)
    assert r and "confirm the time on Zoom here" in r[1] and "scheduler.zoom.us/x?prefill=1" in r[1]
    pv = templates.previews()
    assert {"visitor_rescheduled", "visitor_cancelled", "visitor_reminder"} <= set(pv) and pv["visitor_reminder"]["subject"].startswith("Reminder:")
    # the console can switch each one off
    tpl = dict(templates.get_templates(), visitor_cancelled_enabled="false")
    assert templates.render_booking_visitor(templates.sample_booking_for("cancelled"), tpl) is None


def test_reschedule_cancel_and_reminder_emails_use_the_templates():
    m = M()
    b = _booking(old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)", manage_url="https://a/manage?t=tok")
    send_reschedule_emails(b, mailer=m)
    assert len(m.items) == 2
    to, subject, body, kw = m.items[0]
    assert to == "ada@lovelace.org" and subject.startswith("Your call with Deep has moved:") and "Tue 06 Oct, 10:00" in body and "Hi Ada," in body
    assert kw["attachments"][0][0] == "invite.ics" and kw["kind"] == "reschedule_visitor"
    assert m.items[1][0] == settings.host_email and "Moved:" in m.items[1][1]
    m = M()
    send_cancel_emails(_booking(status="cancelled"), mailer=m)
    assert m.items[0][1].startswith("Your call with Deep is cancelled:") and "welcome back" in m.items[0][2] and m.items[0][3]["kind"] == "cancel_visitor"
    assert m.items[1][0] == settings.host_email and "Cancelled by the visitor" in m.items[1][2]
    m = M()
    assert send_reminder_email(_booking(), mailer=m) is True
    assert m.items[0][1].startswith("Reminder:") and m.items[0][3]["kind"] == "reminder_visitor" and "zoom.us/j/81234567890" in m.items[0][2]
    assert send_reminder_email(_booking(email=""), mailer=M()) is False


def test_memory_greeting_reflects_a_move_and_a_cancel():
    base = {"returning": True, "visits": 2, "name": "Ada", "topics": [], "questions": [], "open_handover": None}
    up = {"id": 7, "schedule_name": "LakeB2B Discovery Call", "label_visitor": "Thu 15 Oct, 16:30", "status": "confirmed", "can_reschedule": True}
    moved = dict(base, upcoming=up, recent_change={"id": 7, "kind": "rescheduled", "schedule_name": up["schedule_name"], "label_visitor": up["label_visitor"],
                                                   "old_label_visitor": "Wed 14 Oct, 16:30", "when": datetime.now(timezone.utc) - timedelta(hours=2)})
    g = memory.greeting(moved)
    assert g["headline"] == "Welcome back, Ada! 👋" and "moved to Thu 15 Oct, 16:30" in g["line"] and "reminder" in g["line"]
    blk = memory.prompt_block(moved)
    assert "They moved that call" in blk and "from Wed 14 Oct, 16:30" in blk and "reminder email goes to them" in blk
    gone = dict(base, upcoming=None, recent_change={"id": 7, "kind": "cancelled", "schedule_name": up["schedule_name"], "label_visitor": up["label_visitor"],
                                                    "old_label_visitor": None, "when": datetime.now(timezone.utc) - timedelta(days=1)})
    g = memory.greeting(gone)
    assert "You cancelled your LakeB2B Discovery Call on Thu 15 Oct, 16:30" in g["line"] and "pick a new time" in g["line"]
    assert "they have no booking now" in memory.prompt_block(gone)
    pub = memory.public(gone)
    assert pub["recent_change"]["kind"] == "cancelled" and pub["upcoming"] is None


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_reminder_job_sends_once_per_upcoming_booking_and_memory_sees_the_change():
    from app import store_bookings as sb
    from app.db import conn

    tag = uuid.uuid4().hex[:8]
    sid, vid = f"rem-{tag}", f"rem-vid-{tag}"
    now = datetime.now(timezone.utc)
    mk = lambda start, status="confirmed": sb.insert({"session_id": sid, "name": "Ada Lovelace", "email": "ada@lovelace.org", "schedule_slug": "discovery-call",  # noqa: E731
                                                       "schedule_name": "LakeB2B Discovery Call", "duration_min": 15, "start_utc": start, "end_utc": start + timedelta(minutes=15),
                                                       "visitor_tz": "Asia/Kolkata", "method": "browser", "status": status, "manage_token": "t" + tag})
    soon = mk(now + timedelta(hours=20))           # due
    later = mk(now + timedelta(hours=40))          # not yet
    gone = mk(now + timedelta(hours=20), "cancelled")  # never
    try:
        with conn() as c:  # the session belongs to a visitor so memory can see the bookings
            c.execute("INSERT INTO sessions(session_id, visitor_id, messages) VALUES (%s, %s, 1) ON CONFLICT (session_id) DO UPDATE SET visitor_id = EXCLUDED.visitor_id, messages = 1", (sid, vid))
            c.commit()
        sent = []
        since_iso = (now - timedelta(minutes=5)).isoformat()
        r = reminders.run(send=lambda b: sent.append(b["id"]) or True, before_hours=24, since_iso=since_iso)
        assert r == {"checked": 1, "sent": 1, "skipped": 0} and sent == [soon]
        assert reminders.run(send=lambda b: True, before_hours=24, since_iso=since_iso)["checked"] == 0  # once only
        assert reminders.run(send=lambda b: True, before_hours=48, since_iso=since_iso) == {"checked": 1, "sent": 1, "skipped": 0}  # the later one, with a wider window
        assert sb.get(gone)["reminder_sent_at"] is None
        # a reschedule and then a cancel show up in the visitor's memory
        assert sb.reschedule(soon, now + timedelta(hours=30), now + timedelta(hours=30, minutes=15))
        p = memory.profile(vid)
        assert p["recent_change"]["kind"] == "rescheduled" and p["recent_change"]["id"] == soon and p["upcoming"]["id"] == soon
        assert "moved to" in memory.greeting(p)["line"]
        sb.cancel(soon); sb.cancel(later)
        p = memory.profile(vid)
        assert p["upcoming"] is None and p["recent_change"]["kind"] == "cancelled" and "You cancelled" in memory.greeting(p)["line"]
    finally:
        with conn() as c:
            c.execute("DELETE FROM bookings WHERE session_id = %s", (sid,))
            c.execute("DELETE FROM events WHERE kind = 'reminder' AND detail->>'booking_id' IN (%s, %s, %s)", (str(soon), str(later), str(gone)))
            c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
            c.commit()


def test_same_session_booking_gives_the_model_preparation_context(monkeypatch):
    """A first-time visitor who just booked: the memory block names the call, what it covers, and forbids re-selling."""
    sb = {"id": 9, "schedule_name": "GTM Strategy Session", "label_visitor": "Fri 16 Oct, 19:30 (Asia/Kolkata)", "duration_min": 45,
          "status": "confirmed", "description": "A 45-minute working session on data, AI and revenue acceleration."}
    p = dict(memory._empty(), session_booking=sb)
    blk = memory.prompt_block(p)
    assert "They booked in this conversation: GTM Strategy Session (45 min) on Fri 16 Oct, 19:30" in blk
    assert "The call covers: A 45-minute working session" in blk and "Never offer to book again" in blk and "what to have ready" in blk.lower() or "have ready" in blk
    assert memory.prompt_block(memory._empty()) == ""  # nothing booked, first visit: no block at all
    # a returning visitor with the same booking gets the guidance once, attached to the upcoming line
    p2 = dict(memory._empty(), returning=True, visits=2, upcoming=dict(sb, status="confirmed"), session_booking=sb)
    blk2 = memory.prompt_block(p2)
    assert "Upcoming booking: GTM Strategy Session" in blk2 and "The call covers:" in blk2 and blk2.count("do not propose a booking") == 1
    from app.rag import prompts
    assert "do not propose booking again" in prompts.SYSTEM_PROMPT
