"""Step 2 (docs/ROADMAP.md): "I don't know" answers reach the gap list, the conversation rating, and the team answering
inside the chat (app/team.py, app/chat.py). Database tests use only rows they create and delete them afterwards."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.chat import _DECLINED, respond
from app.config import settings


# ---------------------------------------------------------------- "I don't know" on good sources
@pytest.mark.parametrize("text,declined", [
    ("I don't know who the CEO of Ampliz is from the available information.", True),
    ("The sources do not specify which AI models Deep uses.", True),
    ("I don't have details on how to apply to Champions Accelerator from the sources.", True),
    ("I couldn't find any mention of a newsletter on deependhq.com.", True),
    ("Pricing is not mentioned on the site.", True),
    ("You can book a call with Deep right here in the chat or email deep@championsmail.com.", False),
    ("Lake B2B is a B2B growth stack focused on data, demand and delivery.", False),
    ("Data is available through Lake Stream.", False),
])
def test_decline_detector(text, declined):
    assert bool(_DECLINED.search(text)) is declined


def _hit(score=0.9):
    from app.rag.retrieve import Hit

    return Hit(url="https://deependhq.com/company/ampliz", title="Ampliz", section=None, text="t", score=score, metadata={})


def _piece(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


def _turn(reply, message="who is the CEO of Ampliz?", booking=False):
    def stream(client, messages, tools, max_tokens=500, model=None):
        return iter([_piece(reply)])
    with patch("app.chat.search", return_value=[_hit()]), patch("app.chat.embed_query", return_value=[0.1]), \
            patch("app.chat.match_custom_answer", return_value=None), patch("app.chat.get_guidance", return_value=""), \
            patch("app.chat.titles.maybe_generate_async"), patch("app.chat.team.visitor_wrote"), \
            patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")), \
            patch("app.chat._create_stream", new=stream), patch("app.chat.booking_in_progress", return_value=booking), \
            patch("app.chat.log_event") as log_event, patch("app.chat.inbox.log_message", return_value=4) as log_message:
        events = [json.loads(c[6:]) for c in respond(message, [], "UTC", "s-t", service=SimpleNamespace(session_id=None, list_schedules=lambda: []),
                                                     client=object()) if c.startswith("data: ")]
    return events, log_event, log_message


def test_uncited_i_dont_know_on_good_sources_is_an_unanswered_question():
    events, log_event, log_message = _turn("I don't know who the CEO of Ampliz is from the available information.")
    assert [e for e in events if e["type"] == "refusal"] == [{"type": "refusal", "reason": "not_in_sources"}]
    assert any(e["type"] == "handover_offer" for e in events)
    assert [c for c in log_event.call_args_list if c[0][0] == "refusal"][0][0][2]["reason"] == "not_in_sources"
    stored = log_message.call_args_list[-1][1]
    assert stored["outcome"] == "refused" and stored["reason"] == "not_in_sources"     # reaches inbox.gaps()


def test_normal_answers_are_unchanged():
    for reply in ("Ampliz is a healthcare data company. [1]",                      # cited
                  "You can book a call with Deep right here in the chat."):        # uncited, but not a decline
        events, _, log_message = _turn(reply)
        assert not [e for e in events if e["type"] in ("refusal", "handover_offer")]
        assert log_message.call_args_list[-1][1]["outcome"] == "answered"
    events, _, _ = _turn("I don't know which day suits you; pick one below.", message="book a call", booking=True)
    assert not [e for e in events if e["type"] == "refusal"]                        # booking turns never count


# ---------------------------------------------------------------- database: rating, team replies, emails
def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


db = pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")


@pytest.fixture
def convo():
    """One visitor conversation with a hand-over lead; everything it creates is removed afterwards."""
    from app import inbox
    from app.db import conn
    from app.tracking import attach_visitor

    vid, sid = f"vis-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    attach_visitor(sid, vid)
    inbox.log_message(sid, "user", "Do you cover the Nordics?")
    inbox.log_message(sid, "assistant", "I couldn't find that on deependhq.com.", question="Do you cover the Nordics?", outcome="refused")
    yield SimpleNamespace(vid=vid, sid=sid)
    with conn() as c:
        c.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM leads WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM events WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        c.commit()


@db
def test_rating_is_owned_and_reported(convo):
    from app import inbox, team

    assert not team.rate(convo.sid, "someone-else", None, 5)
    assert not team.rate(convo.sid, convo.vid, None, 7)
    assert team.rate(convo.sid, convo.vid, None, 2, "  could not answer  ")
    t = inbox.transcript(convo.sid)
    assert t["rating"] == 2 and t["rating_note"] == "could not answer"
    m = inbox.metrics(1)["conversation_rating"]
    assert m["count"] >= 1 and m["average"] is not None


@db
def test_handover_puts_the_conversation_with_the_team(convo):
    from app import inbox, team

    out = inbox.save_handover(convo.sid, "Ada Lovelace", "ada+test@example.com", "Do you cover the Nordics?",
                              send_brief=lambda lead: True, send_visitor=lambda lead: True)
    assert out["lead_id"] and team.status_of(convo.sid) == "waiting"
    assert inbox.metrics(1)["team"]["waiting"] >= 1


@db
def test_team_reply_shows_in_the_chat_unread_and_owned(convo):
    from app import conversations, inbox, team

    r = team.reply(convo.sid, "Yes, we cover the Nordics. I'll send a sample list.", "Deep")
    assert r["role"] == "agent" and team.status_of(convo.sid) == "replied"
    assert team.reply(f"test-{uuid.uuid4()}", "x") is None                         # no such conversation
    up = team.updates(convo.sid, convo.vid, None, 0)
    assert up["team_status"] == "replied" and [m["text"] for m in up["messages"]] == [r["text"]]
    assert team.updates(convo.sid, convo.vid, None, r["id"])["messages"] == []      # nothing newer
    assert team.updates(convo.sid, "someone-else", None, 0) is None
    h = conversations.history(convo.sid, convo.vid, None)
    agent = [m for m in h["messages"] if m.get("agent")]
    assert agent and agent[0]["author"] == "Deep" and agent[0]["role"] == "bot" and h["team_status"] == "replied"
    assert conversations.list_for(convo.vid, None)[0]["unread"] == 2                # the bot's answer + the team reply
    assert [m["role"] for m in inbox.transcript(convo.sid)["messages"]][-1] == "agent"
    assert team.set_status(convo.sid, "closed") and team.status_of(convo.sid) == "closed"
    assert not team.set_status(convo.sid, "bogus")


@db
def test_unread_team_reply_is_emailed_once_with_a_link_back(convo, monkeypatch):
    from app import inbox, team
    from app.db import conn

    monkeypatch.setattr(settings, "site_base_url", "https://deependhq.com")
    inbox.save_handover(convo.sid, "Ada Lovelace", "ada+test@example.com", "Nordics?", send_brief=lambda l: True, send_visitor=lambda l: True)
    r = team.reply(convo.sid, "Yes, we cover the Nordics.", "Deep")
    sent = []
    send = lambda *a, **k: sent.append((a, k))
    now = datetime.now(timezone.utc)
    assert team.notify_unread_replies(send=send, now=now)["sent"] == 0 and not sent          # too soon
    later = now + timedelta(minutes=settings.team_email_after_minutes + 1)
    assert team.notify_unread_replies(send=send, now=later)["sent"] >= 1
    mine = [s for s in sent if s[1].get("ref") == r["id"]]
    (to, subject, body), kw = mine[0]
    assert to == "ada+test@example.com" and subject == "Deep replied to your message" and kw["reply_to"] == settings.host_email
    assert "Yes, we cover the Nordics." in body and f"https://deependhq.com/#dh-chat={convo.sid}" in body and "Hi Ada" in body
    sent.clear()
    team.notify_unread_replies(send=send, now=later + timedelta(minutes=5))
    assert not [s for s in sent if s[1].get("ref") == r["id"]]                               # once only

    r2 = team.reply(convo.sid, "Second note.", "Deep")
    with conn() as c:   # the visitor read it in the chat: no email
        c.execute("UPDATE sessions SET last_read_at = now() + interval '1 minute' WHERE session_id = %s", (convo.sid,))
        c.commit()
    team.notify_unread_replies(send=send, now=later + timedelta(minutes=10))
    assert not [s for s in sent if s[1].get("ref") == r2["id"]]


@db
def test_host_hears_when_the_visitor_writes_again_throttled(convo):
    from app import team

    sent = []
    send = lambda *a, **k: sent.append((a, k))
    assert not team.visitor_wrote(convo.sid, "hello?", send=send)                   # not with the team: nothing
    team.set_status(convo.sid, "waiting")
    assert team.visitor_wrote(convo.sid, "Any update on the Nordics list?", send=send)
    (to, subject, body), kw = sent[0]
    assert to == settings.host_email and "Any update on the Nordics list?" in body and kw["kind"] == "team_visitor_wrote"
    assert not team.visitor_wrote(convo.sid, "and another", send=send)              # within TEAM_HOST_NOTIFY_MINUTES


def test_team_reply_template_preview_and_switch(monkeypatch):
    from app import team, templates

    pv = templates.previews()["visitor_team_reply"]
    assert pv["subject"] == "Deep replied to your message" and "#dh-chat=sample" in pv["body"]
    tpl = dict(templates.DEFAULTS, visitor_team_reply_enabled="false")
    assert team.render_reply_email("Ada", "Deep", "x", "https://l", tpl) is None
