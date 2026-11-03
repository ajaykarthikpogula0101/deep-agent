"""Quote request (app/quote.py) and Shorter / Simpler / More detail (app/rewrite.py)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app import quote as Q
from app import rewrite as RW
from app.config import Settings


# ---------------------------------------------------------------- quote: prefill from the chat
def test_prefill_reads_the_chat():
    pf = Q.from_texts(["Do you have IT manager email lists in the US?",
                       "How much for 20,000 IT managers? We need them by Friday, budget is $5k"])
    assert pf["data_types"] == ["Contact data / email lists"]
    assert pf["titles"] == "IT managers" and pf["regions"] == "US"
    assert pf["volume"] == "5,000 – 25,000" and pf["timeline"] == "ASAP" and pf["budget"] == "$2,000 – $10,000"
    assert pf["notes"].startswith("From the chat: ") and "volume 20,000 IT managers" in pf["notes"]


@pytest.mark.parametrize("texts,key,value", [
    (["intent data for 150k CTOs in Germany and France"], "data_types", ["Intent data"]),
    (["intent data for 150k CTOs in Germany and France"], "volume", "100,000+"),
    (["intent data for 150k CTOs in Germany and France"], "regions", "Germany, France"),
    (["we need 500 contacts next week"], "timeline", "Within 2 weeks"),
    (["we need 500 contacts"], "titles", ""),                               # "contacts" is not a job title
    (["physician lists in Texas"], "data_types", ["Healthcare data"]),
    (["What does LakeB2B do?"], "notes", ""),
])
def test_prefill_cases(texts, key, value):
    assert Q.from_texts(texts)[key] == value


def test_clean_keeps_only_known_choices_and_needs_the_basics():
    q = Q.clean({"name": " Ada  Lovelace ", "email": "Ajaykarthik.LDN+q@gmail.com", "data_types": ["Intent data", "<script>"],
                 "volume": "100,000+", "timeline": "whenever", "budget": "$50,000+", "titles": "CTOs"})
    assert q["name"] == "Ada Lovelace" and q["email"] == "ajaykarthik.ldn+q@gmail.com"
    assert q["data_types"] == ["Intent data"] and q["timeline"] == "" and q["budget"] == "$50,000+"
    for bad, msg in [({"name": "A", "email": "a@b.co", "titles": "x"}, "name"), ({"name": "Ada", "email": "nope", "titles": "x"}, "email"),
                     ({"name": "Ada", "email": "ajaykarthik.ldn+q@gmail.com"}, "data you need")]:
        with pytest.raises(ValueError, match=msg):
            Q.clean(bad)


def test_the_email_to_deep():
    q = Q.clean({"name": "Ada", "email": "ajaykarthik.ldn+q@gmail.com", "company": "Acme", "data_types": ["Intent data"], "titles": "CTOs",
                 "regions": "Germany", "volume": "100,000+", "timeline": "This month", "notes": "verified emails please"})
    assert Q.headline(q) == "100,000+ CTOs · Germany · This month"
    subject, body = Q.render_host(q, ["Do you have CTO lists in Germany?"])
    assert subject == "[Quote request] Ada (Acme): 100,000+ CTOs · Germany · This month"
    assert "• Data: Intent data" in body and "• Budget: -" in body and "verified emails please" in body
    assert "• Do you have CTO lists in Germany?" in body and "never quotes prices" in body
    assert Q.chat_line(q).startswith("Quote request sent to ") and "ajaykarthik.ldn+q@gmail.com" in Q.chat_line(q)


# ---------------------------------------------------------------- rewrite: the prompt
def test_rewrite_prompts():
    msg = {"question": "What does LakeB2B do?", "text": "LakeB2B sells B2B data [1].", "sources": []}
    short = RW.messages_for("shorter", msg)
    assert "at most three short sentences" in short[0]["content"] and "never add facts" in short[0]["content"]
    assert "SOURCES" not in short[1]["content"] and "ORIGINAL ANSWER:\nLakeB2B sells B2B data [1]." in short[1]["content"]
    detail = RW.messages_for("detail", msg, "[1] page text")
    assert "SOURCES:\n[1] page text" in detail[1]["content"] and "cite the SOURCES" in detail[0]["content"]
    assert "everyday words" in RW.messages_for("simpler", msg)[0]["content"]


# ---------------------------------------------------------------- the database side and the endpoints
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

    sid, vid = f"test-qr-{uuid.uuid4().hex[:16]}", f"test-vid-{uuid.uuid4().hex[:12]}"
    tracking.ensure_session(sid, visitor_id=vid, ip="127.0.0.1", user_agent="pytest")
    inbox.log_message(sid, "user", "How much for 20,000 IT managers in the US?")
    mid = inbox.log_message(sid, "assistant", "LakeB2B has IT manager data [1]. Pricing depends on volume.", question="How much for 20,000 IT managers in the US?",
                            outcome="answered", sources=[{"n": 1, "url": "https://lakeb2b.com/it", "title": "IT lists"}])
    yield sid, vid, mid
    RW._cache.clear()
    with conn() as c:
        for t in ("events", "leads", "messages", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


FORM = {"name": "Ada", "email": "ajaykarthik.ldn+quote@gmail.com", "data_types": ["Contact data / email lists"], "titles": "IT managers",
        "regions": "US", "volume": "5,000 – 25,000", "timeline": "ASAP"}


def test_submit_stores_a_lead_tells_deep_and_writes_the_chat_line(chat, monkeypatch):
    from app import intent
    from app.db import conn

    sid, _, _ = chat
    sent = []
    fake = NS(enqueue=lambda to, subject, body, **kw: sent.append((to, subject, body, kw)))
    monkeypatch.setattr(Q.settings, "host_email", "ajaykarthik.ldn+host@gmail.com")
    r = Q.submit(sid, FORM, mailer=fake)
    assert r["ok"] and r["headline"] == "5,000 – 25,000 IT managers · US · ASAP"
    to, subject, body, kw = sent[0]
    assert to == "ajaykarthik.ldn+host@gmail.com" and subject.startswith("[Quote request] Ada:") and kw["reply_to"] == "ajaykarthik.ldn+quote@gmail.com"
    assert "How much for 20,000 IT managers in the US?" in body and kw["kind"] == "quote"
    with conn() as c:
        assert c.execute("SELECT status, email FROM leads WHERE session_id = %s", (sid,)).fetchall() == [("quote", "ajaykarthik.ldn+quote@gmail.com")]
        line = c.execute("SELECT text, outcome FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    assert line == (r["chat_line"], "quote")
    monkeypatch.setattr(intent, "enabled", lambda name: True)
    assert intent.check_buying(sid, "and the price for 10k more by Friday?") is None   # already asked Deep for a quote
    Q.submit(sid, FORM, mailer=fake)
    Q.submit(sid, FORM, mailer=fake)
    with pytest.raises(Q.Limited):
        Q.submit(sid, FORM, mailer=fake)


def test_quote_endpoints_only_for_your_own_chat(chat):
    from fastapi.testclient import TestClient

    from app.main import app

    sid, vid, _ = chat
    c = TestClient(app)
    own = c.get(f"/quote/form?session_id={sid}", headers={"X-Visitor-Id": vid}).json()
    assert own["prefill"]["titles"] == "IT managers" and own["volumes"][0] == "Under 5,000"
    other = c.get(f"/quote/form?session_id={sid}", headers={"X-Visitor-Id": "someone-else"}).json()
    assert other["prefill"]["titles"] == ""                                             # someone else's chat: nothing prefilled
    with patch("app.main.quote.submit", return_value={"ok": True}) as submit:
        assert c.post("/quote", json={"session_id": sid, **FORM}, headers={"X-Visitor-Id": vid}).status_code == 200
        assert c.post("/quote", json={"session_id": sid, **FORM}, headers={"X-Visitor-Id": "someone-else"}).status_code == 404
        assert submit.call_count == 1
    with patch("app.main.quote.submit", side_effect=ValueError("Please enter your name.")):
        r = c.post("/quote", json={"session_id": sid, **FORM}, headers={"X-Visitor-Id": vid})
        assert r.status_code == 422 and r.json()["detail"] == "Please enter your name."


def _fake_client(reply, calls):
    def create(**kw):
        calls.append(kw)
        return NS(choices=[NS(message=NS(content=reply))], usage=None)
    return NS(chat=NS(completions=NS(create=create)))


def test_rewrite_once_per_mode_and_only_your_answers(chat, monkeypatch):
    sid, _, mid = chat
    calls = []
    out = RW.rewrite(sid, mid, "shorter", client=_fake_client("LakeB2B has IT manager data [1].", calls))
    assert out == {"text": "LakeB2B has IT manager data [1].", "sources": [{"n": 1, "url": "https://lakeb2b.com/it", "title": "IT lists"}], "mode": "shorter"}
    assert RW.rewrite(sid, mid, "shorter", client=_fake_client("again", calls))["text"] == out["text"] and len(calls) == 1   # cached
    with pytest.raises(RW.NotFound):
        RW.rewrite("test-qr-someone-else", mid, "shorter", client=_fake_client("x", calls))
    monkeypatch.setattr(RW, "_detail_sources", lambda q: ("[1] IT lists: 40 job functions", [{"n": 1, "url": "https://lakeb2b.com/it", "title": "IT lists"}]))
    d = RW.rewrite(sid, mid, "detail", client=_fake_client("LakeB2B covers 40 IT job functions [1].", calls))
    assert d["mode"] == "detail" and "SOURCES:\n[1] IT lists" in calls[-1]["messages"][1]["content"]
    with pytest.raises(ValueError):
        RW.rewrite(sid, mid, "louder")


def test_rewrite_endpoint(chat):
    from fastapi.testclient import TestClient

    from app.main import app

    sid, vid, mid = chat
    c = TestClient(app)
    with patch("app.main.rewrite.rewrite", return_value={"text": "Short.", "sources": [], "mode": "shorter"}), \
            patch.object(Settings, "chat_api_key", property(lambda self: "test")):
        assert c.post("/chat/rewrite", json={"session_id": sid, "message_id": mid, "mode": "shorter"}, headers={"X-Visitor-Id": vid}).json()["text"] == "Short."
        assert c.post("/chat/rewrite", json={"session_id": sid, "message_id": mid, "mode": "shorter"}, headers={"X-Visitor-Id": "x"}).status_code == 404
        assert c.post("/chat/rewrite", json={"session_id": sid, "message_id": mid, "mode": "louder"}, headers={"X-Visitor-Id": vid}).status_code == 422
