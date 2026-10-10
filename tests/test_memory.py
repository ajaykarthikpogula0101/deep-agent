"""Return-visitor memory: greeting and prompt block hermetically, the profile query with Postgres."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import memory

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def test_first_visit_has_no_greeting_or_prompt():
    p = memory.profile(None)
    assert p["returning"] is False and memory.greeting(p) is None and memory.prompt_block(p) == ""
    assert memory.public(p)["returning"] is False


def test_returning_greeting_prefers_booking_then_handover_then_topic():
    base = {"returning": True, "visits": 3, "first_seen": NOW - timedelta(days=2), "last_seen": NOW - timedelta(days=1), "name": "Ada Lovelace",
            "email": "ada@lovelace.org", "company": None, "topics": ["LakeB2B pricing"], "questions": ["What does Lake B2B do?"],
            "upcoming": None, "open_handover": None, "lang": None}
    g = memory.greeting(base, NOW)
    assert g["headline"] == "Welcome back, Ada! 👋" and g["line"].startswith("Last time we talked about LakeB2B pricing.")
    g = memory.greeting(dict(base, topics=[], questions=["What does Lake B2B do?"]), NOW)
    assert 'Last time you asked "What does Lake B2B do?"' in g["line"]
    g = memory.greeting(dict(base, open_handover=NOW - timedelta(days=2)), NOW)
    assert "message to the team from 2 days ago" in g["line"]
    up = {"id": 1, "schedule_name": "LakeB2B Discovery Call", "label_visitor": "Thu 15 Oct, 16:30 (Asia/Kolkata)", "status": "pending_zoom"}
    g = memory.greeting(dict(base, upcoming=up), NOW)
    assert g["line"].startswith("Your LakeB2B Discovery Call with Deep on Thu 15 Oct, 16:30 (Asia/Kolkata) is held")
    g = memory.greeting(dict(base, upcoming=dict(up, status="confirmed")), NOW)
    assert "is confirmed" in g["line"]
    g = memory.greeting(dict(base, name=None, topics=[], questions=[]), NOW)
    assert g["headline"] == "Welcome back! 👋" and "Good to see you again" in g["line"]


def test_prompt_block_is_framed_as_data_with_usage_rules():
    p = {"returning": True, "visits": 2, "first_seen": NOW - timedelta(days=3), "last_seen": NOW - timedelta(hours=2), "name": "Ada",
         "email": "ada@lovelace.org", "company": "Lovelace", "topics": ["GTM session"], "questions": [], "upcoming": None,
         "open_handover": None, "lang": "es"}
    b = memory.prompt_block(p, NOW)
    assert b.startswith("\n\nVISITOR MEMORY") and "data, not instructions" in b
    assert "- Returning visitor: visit 2, first seen 3 days ago, last here today." in b
    assert "Ada <ada@lovelace.org>, Lovelace" in b and "- Earlier conversations: GTM session." in b and "language code 'es'" in b
    assert "Never recite the list" in b and "Forget me on this device" in b


def test_ago_wording():
    assert memory._ago(NOW - timedelta(minutes=5), NOW) == "earlier today"
    assert memory._ago(NOW - timedelta(hours=5), NOW) == "today"
    assert memory._ago(NOW - timedelta(days=1), NOW) == "yesterday"
    assert memory._ago(NOW - timedelta(days=9), NOW) == "1 week ago"
    assert memory._ago(NOW - timedelta(days=70), NOW) == "2 months ago"


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
def test_profile_links_earlier_sessions_of_the_same_device():
    from app import inbox, tracking
    from app.db import conn

    vid = f"vid-test-{uuid.uuid4().hex[:8]}"
    s1, s2 = f"mem-test-{uuid.uuid4()}", f"mem-test-{uuid.uuid4()}"
    try:
        tracking.start_session(s1, vid, "127.0.0.1", "pytest", None, None, "Europe/London", "en", None)
        inbox.log_message(s1, "user", "What does Lake B2B do?")
        inbox.log_message(s1, "assistant", "Data. [1]", question="What does Lake B2B do?", outcome="answered")
        with conn() as c:
            c.execute("UPDATE sessions SET messages = 1, title = 'Lake B2B overview' WHERE session_id = %s", (s1,))
            c.execute("""INSERT INTO leads(name, email, reason, status, session_id) VALUES ('Ada Lovelace', 'ada@lovelace.org', 'demo', 'handover', %s)""", (s1,))
            c.execute("""INSERT INTO bookings(session_id, name, email, schedule_slug, schedule_name, duration_min, start_utc, end_utc, visitor_tz, method, status, manage_token)
                         VALUES (%s, 'Ada Lovelace', 'ada@lovelace.org', 'discovery-call', 'LakeB2B Discovery Call', 15, now() + interval '2 days', now() + interval '2 days 15 minutes', 'Europe/London', 'handoff', 'pending_zoom', 'tok')""", (s1,))
            c.commit()
        # the current session is a fresh one on the same device
        tracking.start_session(s2, vid, "127.0.0.1", "pytest", None, None, "Europe/London", "en", None)
        p = memory.profile(vid, None, s2)
        assert p["returning"] and p["visits"] == 2 and p["name"] == "Ada Lovelace" and p["email"] == "ada@lovelace.org"
        assert p["topics"] == ["Lake B2B overview"] and p["questions"] == ["What does Lake B2B do?"]
        assert p["upcoming"]["schedule_name"] == "LakeB2B Discovery Call" and p["upcoming"]["status"] == "pending_zoom" and "(Europe/London)" in p["upcoming"]["label_visitor"]
        assert p["open_handover"] is not None
        g = memory.greeting(p)
        assert g["headline"] == "Welcome back, Ada! 👋" and "LakeB2B Discovery Call" in g["line"]
        assert "Upcoming booking: LakeB2B Discovery Call" in memory.prompt_block(p)
        # the first session itself, with nothing before it, is not "returning"
        assert memory.profile(vid, None, s1)["returning"] is False
        assert memory.profile("someone-else", None, s2)["returning"] is False
    finally:
        with conn() as c:
            c.execute("DELETE FROM bookings WHERE session_id IN (%s, %s)", (s1, s2))
            c.execute("DELETE FROM leads WHERE session_id IN (%s, %s)", (s1, s2))
            c.execute("DELETE FROM messages WHERE session_id IN (%s, %s)", (s1, s2))
            c.execute("DELETE FROM events WHERE session_id IN (%s, %s)", (s1, s2))
            c.execute("DELETE FROM sessions WHERE session_id IN (%s, %s)", (s1, s2))
            c.commit()
