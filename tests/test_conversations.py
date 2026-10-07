"""Messages screen data: a visitor's own conversations, newest first, with previews, unread counts and history."""
from __future__ import annotations

import uuid

import pytest

from app import conversations, inbox
from app.tracking import attach_visitor


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")


def test_list_history_unread_and_ownership():
    from app.db import conn

    vid, other = f"vis-{uuid.uuid4()}", f"vis-{uuid.uuid4()}"
    a, b = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    try:
        attach_visitor(a, vid); attach_visitor(b, vid)
        inbox.log_message(a, "user", "What does Lake B2B do?")
        inbox.log_message(a, "assistant", "Lake B2B sells data. [1]", question="What does Lake B2B do?", outcome="answered",
                          sources=[{"n": 1, "url": "https://deependhq.com/company/lake-b2b", "title": "Lake B2B"}])
        inbox.log_message(b, "user", "Book a call")
        inbox.log_message(b, "assistant", "Pick a call type below.", question="Book a call", outcome="booking")

        items = conversations.list_for(vid, None)
        assert [i["session_id"] for i in items] == [b, a]                       # newest first
        assert items[0]["preview"] == "Pick a call type below." and items[0]["unread"] == 1 and items[0]["questions"] == 1
        assert conversations.unread_total(vid, None) == 2
        assert conversations.list_for(other, None) == []                          # someone else sees nothing
        assert conversations.history(a, other, None) is None

        h = conversations.history(a, vid, None)
        assert [m["role"] for m in h["messages"]] == ["user", "bot"]
        assert h["messages"][1]["sources"][0]["url"].endswith("/lake-b2b")

        assert conversations.mark_read(a, vid, None)
        assert not conversations.mark_read(a, other, None)
        by_id = {i["session_id"]: i for i in conversations.list_for(vid, None)}
        assert by_id[a]["unread"] == 0 and by_id[b]["unread"] == 1
        assert conversations.unread_total(vid, None) == 1

        inbox.log_message(a, "user", "and ChampGraph?")
        inbox.log_message(a, "assistant", "A knowledge graph.", question="and ChampGraph?", outcome="answered")
        items = conversations.list_for(vid, None)
        assert items[0]["session_id"] == a and items[0]["preview"] == "A knowledge graph." and items[0]["unread"] == 1  # moved to top
    finally:
        with conn() as c:
            c.execute("DELETE FROM messages WHERE session_id = ANY(%s)", ([a, b],))
            c.execute("DELETE FROM sessions WHERE session_id = ANY(%s)", ([a, b],))
            c.commit()


def test_signed_in_user_sees_sessions_across_devices():
    from app.db import conn
    from app.tracking import attach_user

    a = f"test-{uuid.uuid4()}"
    try:
        attach_visitor(a, "vis-on-phone")
        attach_user(a, {"sub": "user_42", "name": "Ada", "email": "ada@lovelace.org"})
        inbox.log_message(a, "user", "hi"); inbox.log_message(a, "assistant", "hello", question="hi", outcome="answered")
        assert [i["session_id"] for i in conversations.list_for("vis-on-laptop", "user_42")] == [a]
        assert conversations.list_for("vis-on-laptop", None) == []
        assert conversations.list_for(None, None) == []
    finally:
        with conn() as c:
            c.execute("DELETE FROM messages WHERE session_id = %s", (a,))
            c.execute("DELETE FROM sessions WHERE session_id = %s", (a,))
            c.commit()
