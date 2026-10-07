"""Inbox, hand-over and owner guidance: pure helpers hermetically, DB round trips when Postgres is up."""
from __future__ import annotations

import uuid

import pytest

from app import inbox
from app.guidance import guidance_block
from app.inbox import wants_human


def test_wants_human_detects_requests_for_a_person_not_bookings():
    for t in ("Can I talk to a real person?", "connect me with someone from the team", "I want to speak to a human",
              "is this a bot? I'd like a live agent", "please get in touch with support"):
        assert wants_human(t), t
    for t in ("What does Lake B2B do?", "book a call with Deep", "what did Deep ship on day 338?"):
        assert not wants_human(t), t


def test_guidance_block_is_framed_under_the_rules():
    assert guidance_block("") == ""
    block = guidance_block("Always suggest the discovery call first.")
    assert "OWNER GUIDANCE" in block and "rules win" in block and block.rstrip().endswith("first.")


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
def test_turns_feedback_metrics_and_gaps_round_trip():
    from app.db import conn

    sid = f"test-{uuid.uuid4()}"
    try:
        inbox.log_message(sid, "user", "What does Lake B2B do?")
        a1 = inbox.log_message(sid, "assistant", "Lake B2B sells data. [1]", question="What does Lake B2B do?",
                               outcome="answered", sources=[{"n": 1, "url": "https://deependhq.com/company/lake-b2b"}], latency_ms=900)
        inbox.log_message(sid, "user", "What's the weather in Paris?")
        a2 = inbox.log_message(sid, "assistant", "I couldn't find that.", question="What's the weather in Paris?",
                               outcome="refused", reason="low_confidence", latency_ms=120)
        assert inbox.set_feedback(a1, 1, None, sid)
        assert inbox.set_feedback(a2, -1, "not helpful", sid)
        assert not inbox.set_feedback(a2, 1, None, "someone-else")  # another session cannot rate it
        assert not inbox.set_feedback(a2, 5, None, sid)              # only 1 / -1
        m = inbox.metrics(1)
        assert m["conversations"] >= 1 and m["csat"]["up"] >= 1 and m["csat"]["down"] >= 1
        convo = next(c for c in inbox.conversations(1, 500) if c["session_id"] == sid)
        assert convo["questions"] == 2 and convo["resolved"] == 1 and convo["refused"] == 1 and convo["first_question"] == "What does Lake B2B do?"
        t = inbox.transcript(sid)
        assert [x["role"] for x in t["messages"]] == ["user", "assistant", "user", "assistant"]
        assert t["messages"][1]["feedback"] == 1 and t["messages"][3]["feedback_note"] == "not helpful"
        g = inbox.gaps(1)
        assert any(x["question"] == "what's the weather in paris?" for x in g["unanswered"])
        assert any(x["id"] == a2 for x in g["thumbs_down"])
    finally:
        with conn() as c:
            c.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
            c.commit()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_handover_saves_a_lead_and_briefs_the_host_with_the_transcript():
    from app.db import conn

    sid = f"test-{uuid.uuid4()}"
    sent: list[dict] = []
    try:
        inbox.log_message(sid, "user", "Do you offer EU data residency?")
        inbox.log_message(sid, "assistant", "I couldn't find that.", question="Do you offer EU data residency?", outcome="refused")
        acks: list[dict] = []
        r = inbox.save_handover(sid, "Ada Lovelace", "ada@lovelace.org", "Need EU residency details",
                                lambda lead: sent.append(lead) or True, send_visitor=lambda lead: acks.append(lead) or True)
        lead_id, ok = r["lead_id"], r["brief_sent"]
        assert ok and lead_id and r["visitor_mailed"]
        assert sent[0]["status"] == "handover" and "EU data residency" in sent[0]["note"]
        assert acks[0]["email"] == "ada@lovelace.org"
        with conn() as c:
            status, brief = c.execute("SELECT status, brief_sent FROM leads WHERE id = %s", (lead_id,)).fetchone()
        assert (status, brief) == ("handover", True)
        assert inbox.metrics(1)["handovers"] >= 1
    finally:
        with conn() as c:
            c.execute("DELETE FROM leads WHERE session_id = %s", (sid,))
            c.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
            c.commit()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_custom_answers_match_close_questions_only():
    from app.db import conn
    from app.embeddings import embed_query
    from app.guidance import add_custom_answer, delete_custom_answer, list_custom_answers, match_custom_answer, update_custom_answer

    cid = add_custom_answer("What are your office hours?", "Deep's team works 9 to 6 IST, Monday to Friday.", "https://deependhq.com/now")
    try:
        assert any(x["id"] == cid for x in list_custom_answers())
        hit = match_custom_answer(embed_query("when are you open? office hours?"))
        assert hit and hit["id"] == cid and hit["link"].endswith("/now")
        assert match_custom_answer(embed_query("What does Lake B2B do?")) is None
        assert update_custom_answer(cid, enabled=False)
        assert match_custom_answer(embed_query("what are your office hours")) is None  # disabled answers never fire
        with conn() as c:
            hits, = c.execute("SELECT hits FROM custom_answers WHERE id = %s", (cid,)).fetchone()
        assert hits == 1
    finally:
        assert delete_custom_answer(cid)
