"""Live chat (app/live.py): the hub, taking a chat over from the assistant, typing, "Seen", and the console's inbox."""
from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import live
from app.chat import respond


# ---------------------------------------------------------------- the hub
def test_the_hub_delivers_to_every_open_stream_of_a_topic_and_nowhere_else():
    async def run():
        hub = live.Hub()
        a, b, other = hub.subscribe("s:1"), hub.subscribe("s:1"), hub.subscribe("s:2")
        assert hub.publish("s:1", {"type": "message"}) == 2 and hub.count("s:1") == 2
        await asyncio.sleep(0)
        assert (await asyncio.wait_for(a[1].get(), 1))["type"] == "message" and b[1].qsize() == 1 and other[1].qsize() == 0
        hub.unsubscribe("s:1", a)
        hub.unsubscribe("s:1", b)
        assert hub.count("s:1") == 0 and hub.publish("s:1", {"type": "x"}) == 0
    asyncio.run(run())


def test_visitor_streams_only_get_their_side():
    seen = []
    with patch.object(live.hub, "publish", side_effect=lambda topic, ev: seen.append((topic, ev["type"]))):
        live.emit("abc", {"type": "message", "role": "agent"})
        live.emit("abc", {"type": "seen"}, visitor=False)
        live.typing("abc", "visitor", True)          # the visitor's own typing goes to the console only
        live.typing("abc", "agent", True, author="Deep")
    assert seen == [("s:abc", "message"), ("console", "message"), ("console", "seen"), ("console", "typing"),
                    ("s:abc", "typing"), ("console", "typing")]


def test_the_stream_sends_the_first_event_then_published_ones():
    async def run():
        out, gone = [], {"v": False}

        async def disconnected():
            return gone["v"]

        async def consume():
            async for line in live.stream("s:t1", disconnected, first={"type": "live", "on": False}):
                out.append(line)
                if len(out) == 3:
                    gone["v"] = True
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        live.hub.publish("s:t1", {"type": "message", "text": "hi"})
        await asyncio.wait_for(task, 20)
        assert out[0].startswith("retry:") and json.loads(out[1][6:])["type"] == "live" and json.loads(out[2][6:])["text"] == "hi"
        assert live.hub.count("s:t1") == 0
    asyncio.run(run())


# ---------------------------------------------------------------- the database side
def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture
def chat():
    if not _db_up():
        pytest.skip("Postgres not reachable")
    from app import inbox, tracking
    from app.db import conn

    sid, vid = f"test-live-{uuid.uuid4().hex[:16]}", f"test-vid-{uuid.uuid4().hex[:12]}"
    tracking.ensure_session(sid, visitor_id=vid, ip="127.0.0.1", user_agent="pytest")
    inbox.log_message(sid, "user", "Do you have nurse lists for Texas?")
    inbox.log_message(sid, "assistant", "Yes [1].", question="Do you have nurse lists for Texas?", outcome="answered")
    yield sid, vid
    with conn() as c:
        for t in ("events", "leads", "messages", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


def test_take_over_and_hand_back(chat):
    from app.db import conn

    sid, _ = chat
    events = []
    with patch.object(live, "emit", side_effect=lambda s, ev, **kw: events.append(ev)):
        assert live.agent_for(sid) is None
        assert live.take_over(sid, "Deep") == {"ok": True, "live_agent": "Deep"}
        assert live.agent_for(sid) == "Deep"
        with conn() as c:
            assert c.execute("SELECT team_status FROM sessions WHERE session_id = %s", (sid,)).fetchone()[0] == "replied"
        assert live.hand_back(sid) and live.agent_for(sid) is None and not live.hand_back(sid)
    assert [e["on"] for e in events if e["type"] == "live"] == [True, False]


def test_an_idle_take_over_ends_by_itself(chat):
    from app.db import conn

    sid, _ = chat
    live.take_over(sid, "Deep")
    with conn() as c:
        c.execute("UPDATE sessions SET live_at = now() - interval '2 hours' WHERE session_id = %s", (sid,))
        c.commit()
    assert live.agent_for(sid) is None
    with conn() as c:
        assert c.execute("SELECT live_agent FROM sessions WHERE session_id = %s", (sid,)).fetchone()[0] is None


def test_while_taken_over_the_assistant_stays_quiet(chat):
    from app.db import conn

    sid, _ = chat
    live.take_over(sid, "Deep")
    called = []
    with patch("app.chat._create_stream", side_effect=lambda *a, **k: called.append(1)), patch("app.chat.search", side_effect=AssertionError):
        events = [json.loads(x[6:]) for x in respond("Are you there, Deep?", [], "UTC", sid,
                                                     service=SimpleNamespace(session_id=None, list_schedules=lambda: []))
                  if x.startswith("data: ")]
    assert events == [{"type": "live", "on": True, "agent": "Deep"}, {"type": "done"}] and not called
    with conn() as c:
        rows = c.execute("SELECT role, text FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT 2", (sid,)).fetchall()
    assert rows[0] == ("user", "Are you there, Deep?") and rows[1][0] == "assistant"   # stored for Deep; no new assistant turn


def test_a_team_reply_reaches_the_visitor_at_once(chat):
    from app import team

    sid, _ = chat
    events = []
    with patch.object(live, "emit", side_effect=lambda s, ev, **kw: events.append(ev)):
        out = team.reply(sid, "Hi, Deep here.", "Deep")
    assert events[0]["type"] == "message" and events[0]["role"] == "agent" and events[0]["id"] == out["id"] and events[0]["text"] == "Hi, Deep here."
    assert team.updates(sid, chat[1], None)["live_agent"] is None


def test_closing_a_chat_ends_the_take_over(chat):
    from app import team

    sid, _ = chat
    live.take_over(sid, "Deep")
    assert team.set_status(sid, "closed") and live.agent_for(sid) is None


def test_the_inbox_lists_chats_waiting_for_a_person(chat):
    from app import inbox, team

    sid, _ = chat
    assert sid not in [i["session_id"] for i in live.inbox("waiting")["items"]]
    team.set_status(sid, "waiting")
    got = [i for i in live.inbox("waiting")["items"] if i["session_id"] == sid]
    assert got and got[0]["waiting_since"] is not None and got[0]["last_role"] == "assistant"
    team.reply(sid, "On it.", "Deep")
    assert sid not in [i["session_id"] for i in live.inbox("waiting")["items"]]                 # answered: no longer waiting
    assert sid in [i["session_id"] for i in live.inbox("team")["items"]]
    inbox.log_message(sid, "user", "Thanks, and Florida?")
    assert sid in [i["session_id"] for i in live.inbox("waiting")["items"]]                     # wrote again: waiting
    live.take_over(sid, "Deep")
    box = live.inbox("live")
    assert sid in [i["session_id"] for i in box["items"]] and box["counts"]["live"] >= 1


def test_the_profile(chat):
    from app.db import conn

    sid, _ = chat
    with conn() as c:
        c.execute("""INSERT INTO leads(name, email, reason, status, session_id, company) VALUES ('Priya', 'ajaykarthik.ldn+live@gmail.com',
                     'x', 'quote', %s, 'Acme Health')""", (sid,))
        c.commit()
    p = live.profile(sid)
    assert p["name"] == "Priya" and p["email"] == "ajaykarthik.ldn+live@gmail.com" and p["company"] == "Acme Health"
    assert p["leads"][0]["status"] == "quote" and "score" in p


def test_the_endpoints(chat):
    from fastapi.testclient import TestClient

    from app.main import app, settings

    sid, vid = chat
    c = TestClient(app)
    assert c.post(f"/admin/conversations/{sid}/takeover", json={"on": True}).status_code == 403
    assert c.get(f"/conversations/{sid}/live", headers={"X-Visitor-Id": "someone-else"}).status_code == 404
    assert c.post(f"/conversations/{sid}/typing", json={"on": True}, headers={"X-Visitor-Id": "someone-else"}).status_code == 404
    with patch.object(settings, "admin_token", "t0k"):
        h = {"X-Admin-Token": "t0k"}
        assert c.post(f"/admin/conversations/{sid}/takeover", json={"on": True, "author": "Deep"}, headers=h).json()["live_agent"] == "Deep"
        assert c.get(f"/admin/inbox/{sid}", headers=h).json()["profile"]["live_agent"] == "Deep"
        assert sid in [i["session_id"] for i in c.get("/admin/inbox?view=live", headers=h).json()["items"]]
        assert c.post(f"/admin/conversations/{sid}/typing", json={"on": True}, headers=h).json()["ok"]
        assert c.post(f"/admin/conversations/{sid}/takeover", json={"on": False}, headers=h).json()["live_agent"] is None
    assert c.post(f"/conversations/{sid}/typing", json={"on": True}, headers={"X-Visitor-Id": vid}).json()["ok"]
