"""Frustration detection (app/mood.py): rules on the visitor's words and the chat so far; what the chat does with it."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import mood as M
from app.chat import respond
from app.rag.retrieve import Hit


def A(outcome="answered", feedback=None):
    return {"role": "assistant", "text": "an answer", "outcome": outcome, "feedback": feedback}


def V(text):
    return {"role": "visitor", "text": text}


@pytest.mark.parametrize("message,turns,why", [
    ("this is useless", [], "said it isn't helping"),
    ("You don't understand what I'm asking", [A()], "said it isn't helping"),
    ("seriously? this is so frustrating", [A()], "said it isn't helping"),
    ("that's not what I asked", [A()], "said it isn't helping"),
    ("Do you have nurse email lists for Texas?", [V("do you have nurse email lists in Texas"), A("refused")],
     "asked the same thing again; the assistant couldn't answer"),
    ("WHY CAN'T YOU ANSWER THIS", [A("refused"), A("refused")], "the assistant couldn't answer; wrote in capitals or with !!"),
    ("ugh!!", [A()], "sounded annoyed; wrote in capitals or with !!"),
    ("no", [V("pricing for SPAN?"), A("refused", -1), V("hello?"), A("refused")],
     "the assistant couldn't answer; rated an answer not helpful; replied with a curt no"),
])
def test_frustrated(message, turns, why):
    m = M.assess(message, turns)
    assert m["frustrated"] and m["score"] >= M.FRUSTRATED_AT and m["why"] == why, m


@pytest.mark.parametrize("message,turns", [
    ("What does LakeB2B do?", []),
    ("I am annoyed by bounced emails, can LakeB2B help?", []),                 # their own problem, not the bot
    ("our onboarding is frustrating for the team, can you help?", []),
    ("no", []),                                                               # no answer to say no to yet
    ("Thanks! That's great!!", [A()]),                                        # excited, not angry: 1 point
    ("And for Florida?", [V("nurse email lists for Texas"), A("refused")]),  # a new question after one miss
])
def test_not_frustrated(message, turns):
    assert not M.assess(message, turns)["frustrated"]


def test_asking_again_means_the_same_question_in_other_words():
    assert M.similar("Do you have nurse email lists for Texas?", "nurse email lists in texas, do you have them")
    assert M.similar("vet clinic lists in Iceland with owners mobile numbers, do you have them or not??",
                     "Do you sell lists of veterinary clinics in Iceland with the owners mobile numbers?")   # vet = veterinary
    assert M.similar("how do I export intent data from LakeB2B to Salesforce", "export LakeB2B intent data into salesforce how")
    assert not M.similar("nurse email lists for Texas", "dentist email lists for Ohio")
    assert not M.similar("nurse email lists for Texas", "nurse email lists for Florida")   # a new question
    assert not M.similar("pricing?", "pricing?")                                # too short to tell
    assert not M.assess("nurse email lists for Florida", [V("nurse email lists for Texas"), A("refused")])["frustrated"]


# ---------------------------------------------------------------- the chat turn (a fake model)
def _piece(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


class FakeStream:
    def __init__(self, reply="Sorry about that. LakeB2B sells B2B data [1]."):
        self.reply, self.calls = reply, []

    def __call__(self, client, messages, tools, max_tokens=500, model=None):
        self.calls.append(messages)
        return iter([_piece(self.reply)])


FR = {"score": 4, "frustrated": True, "reasons": ["says_so", "asked_again"], "offer": True,
      "why": "said it isn't helping; asked the same thing again"}


def _turn(fr, message="this isn't helping, what does LakeB2B actually sell?"):
    fake = FakeStream()
    hit = Hit(url="https://deependhq.com/x", title="x", section=None, text="LakeB2B sells data", score=0.9, metadata={})
    with patch("app.chat.mood.check", return_value=fr), patch("app.chat._create_stream", new=fake), \
            patch("app.chat.search", return_value=[hit]), patch("app.chat.embed_query", return_value=[0.1]), \
            patch("app.chat.match_custom_answer", return_value=None), patch("app.chat.get_guidance", return_value=""), \
            patch("app.chat.titles.maybe_generate_async"), patch("app.chat.log_event"), \
            patch("app.chat.inbox.log_message", return_value=7), \
            patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")):
        events = [json.loads(x[6:]) for x in respond(message, [], "UTC", "s-mood-1",
                                                     service=SimpleNamespace(session_id=None, list_schedules=lambda: []))
                  if x.startswith("data: ")]
    return events, fake.calls[0][0]["content"] if fake.calls else ""


def test_a_frustrated_turn_tells_the_model_and_offers_a_person_once():
    events, system = _turn(FR)
    kinds = [e["type"] for e in events if e["type"] not in ("status", "lang")]
    assert kinds.index("frustration") < kinds.index("token")
    assert [e for e in events if e["type"] == "frustration"] == [{"type": "frustration", "reasons": ["says_so", "asked_again"]}]
    assert "The visitor seems frustrated (said it isn't helping; asked the same thing again)" in system
    events, system = _turn({**FR, "offer": False})                        # offered already: a kinder answer, no second card
    assert not [e for e in events if e["type"] == "frustration"] and "seems frustrated" in system
    events, system = _turn(None, "What does LakeB2B sell?")
    assert not [e for e in events if e["type"] == "frustration"] and "seems frustrated" not in system


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
    from app import inbox
    from app.db import conn

    sid = f"test-mood-{uuid.uuid4().hex[:16]}"
    inbox.log_message(sid, "user", "Do you have nurse email lists for Texas?")
    inbox.log_message(sid, "assistant", "I couldn't find that.", question="Do you have nurse email lists for Texas?", outcome="refused")
    yield sid
    with conn() as c:
        for t in ("events", "leads", "messages", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


def test_the_card_is_offered_once_and_deep_is_told(chat):
    from app import escalate, inbox

    sid = chat
    assert M.check(sid, "What does LakeB2B do?") is None                     # not frustrated: nothing logged
    inbox.log_message(sid, "user", "nurse email lists in Texas, do you have them??")
    first = M.check(sid, "nurse email lists in Texas, do you have them??")
    assert first["frustrated"] and first["offer"] and "asked the same thing again" in first["why"]
    inbox.log_message(sid, "user", "this is useless")
    assert M.check(sid, "this is useless")["offer"] is False                   # once per chat
    assert M.last(sid)["why"].startswith("said it isn't helping")
    assert inbox.metrics(1)["frustrated"] >= 1
    assert [c for c in inbox.conversations(1, 500) if c["session_id"] == sid][0]["frustrated"] is True
    lead = {"name": "Ada Lovelace", "email": "ajaykarthik.ldn+mood@gmail.com", "reason": "Hi Deep", "session_id": sid}
    subject, body = escalate.render_host(lead, escalate.fallback(escalate.conversation(sid)))
    assert "(frustrated)" in subject and "HOW THEY FELT\n  Frustrated: said it isn't helping" in body


def test_no_card_after_the_visitor_already_wrote_to_deep(chat):
    from app.db import conn

    sid = chat
    with conn() as c:
        c.execute("INSERT INTO leads(name, email, reason, status, session_id) VALUES ('Ada', 'ajaykarthik.ldn+mood@gmail.com', 'x', 'handover', %s)", (sid,))
        c.commit()
    assert M.check(sid, "this is useless")["offer"] is False
