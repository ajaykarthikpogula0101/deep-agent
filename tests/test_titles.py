"""Conversation titles: cleaning, fallbacks, the generate/regenerate decision, storage, and renaming."""
from __future__ import annotations

import uuid

import pytest

from app import titles
from app.titles import GREETING_TITLE, clean_title, fallback_title, should_generate


def test_clean_title_strips_quotes_prefixes_and_trailing_punctuation():
    assert clean_title('"Booking a Call with Deep."') == "Booking a Call with Deep"
    assert clean_title("Title: Lake B2B Services Overview!\nextra line") == "Lake B2B Services Overview"
    assert clean_title("one two three four five six seven eight nine ten") == "one two three four five six seven eight"
    assert clean_title("   ") == "" and clean_title(None) == ""


def test_fallback_is_the_first_message_cut_to_about_40_chars():
    assert fallback_title("What does Lake B2B do?") == "What does Lake B2B do?"
    long = "Which companies are part of Champions Group and what do they each do exactly"
    f = fallback_title(long)
    assert f.endswith("…") and len(f) <= 42 and f.startswith("Which companies are part of Champions")
    assert fallback_title("good morning!") == GREETING_TITLE and fallback_title("hi") == GREETING_TITLE
    assert fallback_title("") == "New conversation"
    assert fallback_title("look at this [attached: brief.txt](/uploads/x)") == "look at this brief.txt"


def test_should_generate_rules():
    base = {"title": None, "source": None, "title_turns": None, "turns": 1}
    assert should_generate(base)
    assert not should_generate({**base, "turns": 0})
    assert not should_generate({**base, "title": "Lake B2B Services", "source": "auto", "title_turns": 1})
    assert should_generate({**base, "title": GREETING_TITLE, "source": "auto", "title_turns": 1, "turns": 2})
    assert should_generate({**base, "title": "Lake B2B Services", "source": "auto", "title_turns": 1, "turns": 6})
    assert not should_generate({**base, "title": "Lake B2B Services", "source": "auto", "title_turns": 6, "turns": 6})
    assert not should_generate({**base, "title": "Lake B2B Services", "source": "auto", "title_turns": 1, "turns": 7})
    assert not should_generate({**base, "title": "My name", "source": "user", "turns": 6})


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
def test_generate_stores_title_and_rename_wins():
    from app import conversations, inbox
    from app.db import conn
    from app.tracking import attach_visitor

    vid, sid = f"vis-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    calls: list[int] = []
    fake = lambda rows: (calls.append(len(rows)), "Lake B2B Services Overview")[1]
    try:
        attach_visitor(sid, vid)
        assert titles.generate(sid, ask=fake) == {"title": None, "generated": False}  # no turns yet
        inbox.log_message(sid, "user", "What does Lake B2B do?")
        inbox.log_message(sid, "assistant", "Lake B2B sells data.", question="What does Lake B2B do?", outcome="answered")
        assert conversations.list_for(vid, None)[0]["title"] == "What does Lake B2B do?"          # fallback before generation
        assert titles.generate(sid, ask=fake) == {"title": "Lake B2B Services Overview", "generated": True}
        assert titles.generate(sid, ask=fake)["generated"] is False and len(calls) == 1              # not regenerated on load
        row = conversations.list_for(vid, None)[0]
        assert row["title"] == "Lake B2B Services Overview" and row["title_source"] == "auto"
        # failures keep the stored title
        assert titles.generate(sid, force=True, ask=lambda rows: (_ for _ in ()).throw(RuntimeError("down")))["generated"] is False
        assert conversations.list_for(vid, None)[0]["title"] == "Lake B2B Services Overview"
        # visitor rename sticks and blocks auto regeneration
        assert titles.rename(sid, '"My Lake B2B notes."', vid, None) == "My Lake B2B notes"
        assert titles.rename(sid, "x", "someone-else", None) is None
        assert titles.generate(sid, force=True, ask=fake)["generated"] is False
        assert conversations.list_for(vid, None)[0]["title_source"] == "user"
    finally:
        with conn() as c:
            c.execute("DELETE FROM messages WHERE session_id = %s", (sid,)); c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,)); c.commit()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_greeting_only_chat_gets_a_placeholder_then_a_real_title():
    from app import inbox
    from app.db import conn
    from app.tracking import attach_visitor

    vid, sid = f"vis-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    try:
        attach_visitor(sid, vid)
        inbox.log_message(sid, "user", "good morning"); inbox.log_message(sid, "assistant", "Good morning! How can I help?", question="good morning", outcome="answered")
        assert titles.generate(sid, ask=lambda rows: "Should Not Be Called")["title"] == GREETING_TITLE
        inbox.log_message(sid, "user", "Tell me about ChampGraph"); inbox.log_message(sid, "assistant", "ChampGraph is a knowledge graph.", question="Tell me about ChampGraph", outcome="answered")
        assert titles.generate(sid, ask=lambda rows: "ChampGraph Questions") == {"title": "ChampGraph Questions", "generated": True}
    finally:
        with conn() as c:
            c.execute("DELETE FROM messages WHERE session_id = %s", (sid,)); c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,)); c.commit()
