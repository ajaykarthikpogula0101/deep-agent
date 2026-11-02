"""Email Deep (app/escalate.py): the email the assistant writes from the chat, and the summary Deep receives."""
from __future__ import annotations

import uuid
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app import escalate as E

TURNS = [
    {"id": 1, "role": "visitor", "text": "Do you have nurse email lists for Texas?", "outcome": None, "feedback": None, "question": None},
    {"id": 2, "role": "assistant", "text": "I couldn't find that on the site.", "outcome": "refused", "feedback": None,
     "question": "Do you have nurse email lists for Texas?"},
    {"id": 3, "role": "visitor", "text": "What does LakeB2B do?", "outcome": None, "feedback": None, "question": None},
    {"id": 4, "role": "assistant", "text": "LakeB2B provides B2B data.", "outcome": "answered", "feedback": -1, "question": "What does LakeB2B do?"},
    {"id": 5, "role": "visitor", "text": "Can I talk to a real person?", "outcome": None, "feedback": None, "question": None},
]


def fake(answer, calls):
    return NS(chat=NS(completions=NS(create=lambda **kw: (calls.append(kw), NS(choices=[NS(message=NS(content=answer))]))[1])))


AI = ('```json\n{"subject": "Nurse email lists for Texas", "summary": "The visitor wants nurse contacts in Texas. The assistant '
      'could not answer.", "unanswered": ["Do you have nurse email lists for Texas?"], "message": "Hi Deep,\\n\\nI need nurse '
      'email lists for Texas. Do you have them?"}\n```')


def test_the_rules_draft_uses_the_visitors_own_words():
    assert E.asked(TURNS) == ["Do you have nurse email lists for Texas?", "What does LakeB2B do?"]       # not "talk to a person"
    assert E.fell_short(TURNS) == ["Do you have nurse email lists for Texas?", "What does LakeB2B do?"]  # refused + rated down
    d = E.fallback(TURNS)
    assert d["message"].startswith("Hi Deep,") and "- Do you have nurse email lists for Texas?" in d["message"] and not d["by_ai"]
    assert d["subject"] == "Do you have nurse email lists for Texas?" and "2 questions" in d["summary"]
    empty = E.fallback(TURNS[-1:])                                       # only asked for a person: an empty form
    assert empty["message"] == "" and empty["summary"] == ""


def test_the_model_reply_is_checked_and_clipped():
    d = E.parse(AI)
    assert d["subject"] == "Nurse email lists for Texas" and d["unanswered"] == ["Do you have nurse email lists for Texas?"] and d["by_ai"]
    assert d["message"].startswith("Hi Deep,\n\nI need")
    assert E.parse("not json") is None and E.parse('["a"]') is None and E.parse('{"subject": "x", "message": ""}') is None
    calls = []
    assert E._ask_model(TURNS, fake(AI, calls))["subject"] == "Nurse email lists for Texas"
    sent = calls[0]["messages"]
    assert "data, not instructions" in sent[0]["content"] and "<chat>" in sent[1]["content"]
    assert "[not answered]" in sent[1]["content"] and "[rated not helpful]" in sent[1]["content"]


def test_the_email_to_deep_has_the_need_the_open_questions_and_the_chat():
    lead = {"name": "Ada Lovelace", "email": "ada@lovelace.test", "company": "Lovelace Labs", "reason": "Hi Deep, I need Texas nurses.",
            "origin": "deependhq.com/data", "session_id": None}
    subject, body = E.render_host(lead, E.parse(AI), TURNS)
    assert subject == "[Website chat] Ada Lovelace (Lovelace Labs) needs your help: Nurse email lists for Texas"
    assert "after the assistant couldn't fully answer" in body
    for part in ("WHAT THEY NEED", "STILL OPEN\n  1. Do you have nurse email lists for Texas?", "THEIR MESSAGE\n  Hi Deep, I need Texas nurses.",
                 "Company: Lovelace Labs", "THE CHAT (last 5 messages)", "Visitor: Can I talk to a real person?",
                 "Reply to this email to answer Ada directly", "written by the website assistant"):
        assert part in body, part
    out = []
    assert E.send_host(lead, E.fallback(TURNS), send=lambda to, s, b, reply_to=None: out.append((to, s, reply_to)) or True)
    assert out[0][2] == "ada@lovelace.test" and out[0][1].startswith("[Website chat] Ada Lovelace")


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

    sid, vid = f"test-{uuid.uuid4().hex[:20]}", f"test-vid-{uuid.uuid4().hex[:12]}"
    tracking.ensure_session(sid, visitor_id=vid, ip="127.0.0.1", user_agent="pytest")
    inbox.log_message(sid, "user", "Do you have nurse email lists for Texas?")
    inbox.log_message(sid, "assistant", "I couldn't find that.", question="Do you have nurse email lists for Texas?", outcome="refused")
    yield sid, vid
    E._cache.pop(sid, None)
    with conn() as c:
        c.execute("DELETE FROM events WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM leads WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        c.commit()


def test_a_draft_is_written_once_per_chat_state(chat):
    from app import inbox

    sid, _ = chat
    calls = []
    with patch.object(E.settings, "handover_summary", True):
        d = E.draft(sid, fake(AI, calls))
        assert d["by_ai"] and d["subject"] == "Nurse email lists for Texas" and len(calls) == 1
        assert E.draft(sid, fake(AI, calls)) == d and len(calls) == 1               # opening the form, then sending: one call
        inbox.log_message(sid, "user", "Also Florida?")
        E.draft(sid, fake(AI, calls))
        assert len(calls) == 2                                                    # a new message: written again
        down = NS(chat=NS(completions=NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("no network")))))
        inbox.log_message(sid, "user", "And Ohio?")
        d2 = E.draft(sid, down)
        assert not d2["by_ai"] and "Do you have nurse email lists for Texas?" in d2["message"]   # the rules draft
    with patch.object(E.settings, "handover_summary", False):
        E._cache.pop(sid, None)
        assert not E.draft(sid, fake(AI, calls))["by_ai"] and len(calls) == 2    # switched off: no model call


def test_the_draft_endpoint_only_reads_your_own_chat_and_the_handover_sends_the_summary(chat):
    from fastapi.testclient import TestClient

    from app.main import app

    sid, vid = chat
    d = E.parse(AI)
    c = TestClient(app)
    with patch("app.main.escalate.draft", return_value=d):
        own = c.post("/handover/draft", json={"session_id": sid}, headers={"X-Visitor-Id": vid}).json()
        assert own["message"].startswith("Hi Deep,") and own["summary"] and own["by_ai"]
        other = c.post("/handover/draft", json={"session_id": sid}, headers={"X-Visitor-Id": "someone-else"}).json()
        assert other["message"] == "" and other["summary"] == ""
        assert c.post("/handover/draft", json={"session_id": sid}).status_code == 400   # no visitor id at all
    mails = []
    with patch("app.main.settings.handover_summary", True), patch("app.main.escalate.draft", return_value=d), \
            patch("app.main.escalate.send_host", side_effect=lambda lead, dd: mails.append((lead, dd)) or True), \
            patch("app.booking.email.send_visitor_confirmation", return_value=False):
        r = c.post("/handover", json={"session_id": sid, "name": "Ada Lovelace", "email": "ajaykarthik.ldn+escalate@gmail.com",
                                      "message": "Hi Deep, I need Texas nurses."}, headers={"X-Visitor-Id": vid}).json()
    assert r["ok"] and r["brief_sent"]
    lead, dd = mails[0]
    assert dd is d and lead["reason"] == "Hi Deep, I need Texas nurses." and lead["email"] == "ajaykarthik.ldn+escalate@gmail.com"
