"""Smart suggestions: cleaning and merging hermetically, the top-questions query with Postgres."""
from __future__ import annotations

import random
import string
import uuid

import pytest

from app import suggestions as sg


def test_clean_keeps_real_questions_and_drops_personal_or_chatty_text():
    assert sg.clean("what does lake b2b do") == "What does lake b2b do?"
    assert sg.clean("  Tell me about the companies.  ") == "Tell me about the companies"
    assert sg.clean("How many companies does Deep run?") == "How many companies does Deep run?"
    for bad in ("hi", "my email is ada@lovelace.org", "yes please", "what did deep do on day 338", "I'm Ada, about EU fintech",
                "what is " + "x" * 80, "ok thanks", "lake b2b"):
        assert sg.clean(bad) is None, bad


def test_merge_pins_booking_first_dedupes_and_pads_with_defaults():
    out = sg.merge(["What does Lake B2B do?", "what does lake b2b do", "Can I book a meeting?"])
    assert out == ["Book a call with Deep", "What does Lake B2B do?", "What is Deep working on?"]
    assert sg.merge([]) == ["Book a call with Deep", "What is Deep working on?", "Tell me about the companies"]
    assert sg.merge(["Who is Deep?", "What is Ampliz?", "Where is the team?"], limit=4) == ["Book a call with Deep", "Who is Deep?", "What is Ampliz?", "Where is the team?"]


def test_current_falls_back_to_defaults_without_a_database(monkeypatch):
    monkeypatch.setattr(sg, "top_questions", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    sg.invalidate()
    assert sg.current(force=True) == sg.merge([])
    e = sg.explain()
    assert e["cached"] is True and e["asked"] == []
    sg.invalidate()


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
def test_top_questions_counts_answered_questions_across_sessions():
    from app import inbox
    from app.db import conn

    q = f"What does Zorblax {''.join(random.choices(string.ascii_lowercase, k=6))} do?"
    sids = [f"sugg-test-{uuid.uuid4()}" for _ in range(3)]
    try:
        for sid in sids:
            inbox.log_message(sid, "user", q)
            inbox.log_message(sid, "assistant", "It does things. [1]", question=q, outcome="answered")
        inbox.log_message(sids[0], "assistant", "I couldn't find that.", question="What is the pricing of Zorblax?", outcome="refused")
        top = sg.top_questions(days=1, limit=20)
        hit = next((t for t in top if t["question"] == q), None)
        assert hit and hit["count"] == 3
        assert not any("pricing of Zorblax" in t["question"] for t in top)  # refused answers never become suggestions
        sg.invalidate()
        assert q in sg.current(force=True) or len(sg.current()) == sg.LIMIT
    finally:
        with conn() as c:
            c.execute("DELETE FROM messages WHERE session_id = ANY(%s)", (sids,))
            c.commit()
        sg.invalidate()
