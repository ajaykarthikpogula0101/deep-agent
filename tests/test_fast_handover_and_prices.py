"""Email Deep confirms at once (the emails go out on a worker thread), and the assistant never states prices."""
from __future__ import annotations

import json
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import escalate, inbox
from app.chat import respond
from app.rag import prompts
from app.rag.retrieve import Hit


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
    from app import tracking
    from app.db import conn

    sid, vid = f"test-fast-{uuid.uuid4().hex[:16]}", f"test-vid-{uuid.uuid4().hex[:12]}"
    tracking.ensure_session(sid, visitor_id=vid, ip="127.0.0.1", user_agent="pytest")
    inbox.log_message(sid, "user", "Do you have nurse email lists for Texas?")
    inbox.log_message(sid, "assistant", "I couldn't find that.", question="Do you have nurse email lists for Texas?", outcome="refused")
    yield sid, vid
    escalate._cache.pop(sid, None)
    with conn() as c:
        for t in ("events", "leads", "messages", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


def _wait(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_background_handover_saves_first_and_sends_after(chat):
    from app.db import conn

    sid, _ = chat
    gate, briefs, copies = threading.Event(), [], []

    def slow_brief(lead):
        gate.wait(5)           # a slow mail server
        briefs.append(lead["email"])
        return True

    t0 = time.monotonic()
    r = inbox.save_handover(sid, "Ada", "ajaykarthik.ldn+fast@gmail.com", "Hi Deep", slow_brief,
                            send_visitor=lambda lead: copies.append(lead["email"]) or True, chat_line="Email sent to Deep.", background=True)
    assert time.monotonic() - t0 < 2 and r["brief_sent"] is None and r["visitor_mailed"] is None and "copy_queued" in r
    with conn() as c:   # saved before returning: the lead, the chat line, the team status
        assert c.execute("SELECT status FROM leads WHERE id = %s", (r["lead_id"],)).fetchone()[0] == "handover"
        assert c.execute("SELECT text FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT 1", (sid,)).fetchone()[0] == "Email sent to Deep."
        assert c.execute("SELECT team_status FROM sessions WHERE session_id = %s", (sid,)).fetchone()[0] == "waiting"
    assert not briefs
    gate.set()
    assert _wait(lambda: briefs and copies)
    assert _wait(lambda: conn().__enter__().execute("SELECT brief_sent FROM leads WHERE id = %s", (r["lead_id"],)).fetchone()[0] is True)


def test_the_synchronous_path_is_unchanged(chat):
    sid, _ = chat
    r = inbox.save_handover(sid, "Ada", "ajaykarthik.ldn+fast@gmail.com", "Hi Deep", lambda lead: True, send_visitor=lambda lead: True)
    assert r["brief_sent"] is True and r["visitor_mailed"] is True and "copy_queued" not in r


def test_the_endpoint_answers_before_deeps_summary_is_written(chat):
    from fastapi.testclient import TestClient

    from app.main import app

    sid, vid = chat
    gate, sent = threading.Event(), []

    def slow_draft(session_id, client=None):
        gate.wait(5)                                      # a slow model call
        return escalate.fallback(escalate.conversation(session_id))

    with patch("app.main.escalate.draft", side_effect=slow_draft), patch.object(escalate.settings, "handover_summary", True), \
            patch("app.main.escalate.send_host", side_effect=lambda lead, d: sent.append(d) or True), \
            patch("app.booking.email.send_visitor_confirmation", return_value=True):
        t0 = time.monotonic()
        r = TestClient(app).post("/handover", json={"session_id": sid, "name": "Ada", "email": "ajaykarthik.ldn+fast@gmail.com",
                                                    "message": "Hi Deep, Texas nurses?"}, headers={"X-Visitor-Id": vid}).json()
        assert time.monotonic() - t0 < 3 and r["ok"] and r["chat_line"].startswith("Email sent to ")
        assert not sent                                    # Deep's email waits for the summary, on the worker thread
        gate.set()
        assert _wait(lambda: bool(sent))


def test_a_draft_written_when_the_form_opened_is_reused(chat):
    sid, _ = chat
    assert escalate.cached(sid) is None
    d = {"subject": "Texas nurse lists", "message": "Hi Deep", "by_ai": True, "summary": "x"}
    turns = escalate.conversation(sid)
    escalate._cache[sid] = (time.monotonic(), turns[-1]["id"], dict(d))
    assert escalate.cached(sid) == d
    inbox.log_message(sid, "user", "And Ohio?")
    assert escalate.cached(sid) is None                    # the chat moved on: written again


# ---------------------------------------------------------------- prices
def _piece(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


def _system(policy):
    calls = []

    def fake(client, messages, tools, max_tokens=500, model=None):
        calls.append(messages)
        return iter([_piece("Pricing depends on the volume [1].")])

    hit = Hit(url="https://lakeb2b.com/blog", title="Buying lists", section=None, text="Lists cost $373 per 1,000 contacts", score=0.9, metadata={})
    with patch("app.chat._create_stream", new=fake), patch("app.chat.search", return_value=[hit]), patch("app.chat.embed_query", return_value=[0.1]), \
            patch("app.chat.match_custom_answer", return_value=None), patch("app.chat.get_guidance", return_value=""), \
            patch("app.chat.titles.maybe_generate_async"), patch("app.chat.log_event"), patch("app.chat.inbox.log_message", return_value=7), \
            patch("app.chat.knowledge.scope_note", return_value=""), patch("app.chat.settings.price_policy", policy), \
            patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")):
        list(respond("How much do nurse lists cost?", [], "UTC", "s-price-1", service=SimpleNamespace(session_id=None, list_schedules=lambda: [])))
    return calls[0][0]["content"]


def test_the_assistant_is_told_never_to_state_prices():
    assert prompts.PRICE_NOTE.strip() in _system("quote")
    assert "never state a price" in prompts.PRICE_NOTE and "Get a quote" in prompts.PRICE_NOTE
    assert "PRICES:" not in _system("sources")              # the older behaviour, when the owner wants it
    json.dumps(prompts.PRICE_NOTE)


@pytest.mark.parametrize("text,out", [
    ("Pricing depends on volume. Plans cost roughly $373 to $582 per 1,000 contacts, depending on tier. Seat plans differ.",
     "Pricing depends on volume. Seat plans differ."),                                    # the whole price sentence goes
    ("From USD 5k a month.\nWe cover 160+ countries.", "\nWe cover 160+ countries."),
    ("about 50 cents per record", ""),
    ("Rs. 4,999 per list. Free samples available.", " Free samples available."),
    ("$0.37/contact", ""),
    ("20,000 contacts in 2026, over 1.9 million emails.", "20,000 contacts in 2026, over 1.9 million emails."),   # counts stay
    ("The US market and US 500 companies.", "The US market and US 500 companies."),
])
def test_price_sentences_are_left_out_of_the_pages(text, out):
    assert prompts.redact_prices(text) == out


def test_the_model_never_sees_the_pages_prices():
    seen = []

    def fake(client, messages, tools, max_tokens=500, model=None):
        seen.append(json.dumps(messages))
        return iter([_piece("Pricing depends on the volume [1].")])

    hit = Hit(url="https://lakeb2b.com/blog", title="Buying lists", section=None,
              text="Lists cost $373 to $582 per 1,000 contacts. Data is verified monthly.", score=0.9, metadata={})
    for policy, shown in (("quote", False), ("sources", True)):
        with patch("app.chat._create_stream", new=fake), patch("app.chat.search", return_value=[hit]), patch("app.chat.embed_query", return_value=[0.1]), \
                patch("app.chat.match_custom_answer", return_value=None), patch("app.chat.get_guidance", return_value=""), \
                patch("app.chat.titles.maybe_generate_async"), patch("app.chat.log_event"), patch("app.chat.inbox.log_message", return_value=7), \
                patch("app.chat.knowledge.scope_note", return_value=""), patch("app.chat.settings.price_policy", policy), \
                patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")):
            list(respond("How much do lists cost?", [], "UTC", "s-price-2", service=SimpleNamespace(session_id=None, list_schedules=lambda: [])))
        assert ("per 1,000 contacts" in seen[-1]) is shown and "Data is verified monthly." in seen[-1]
