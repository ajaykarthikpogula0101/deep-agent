"""Compare side by side (app/compare.py) and Email me this chat (app/chat_email.py)."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import chat_email as CE
from app import compare as C
from app.chat import respond
from app.rag.retrieve import Hit

KNOWN = [{"name": "Lake B2B", "aliases": ["lake b2b", "lake-b2b", "lakeb2b"]},
         {"name": "SPAN Global Services", "aliases": ["spanglobalservices", "span global services", "span global", "span"]},
         {"name": "Ampliz", "aliases": ["ampliz"]}]


@pytest.fixture
def known(monkeypatch):
    monkeypatch.setattr(C, "_known", lambda: KNOWN)


# ---------------------------------------------------------------- spotting a comparison
@pytest.mark.parametrize("q,subjects,aspect", [
    ("Compare LakeB2B and SPAN", ["Lake B2B", "SPAN Global Services"], None),
    ("Ampliz vs Lake B2B: data coverage?", ["Ampliz", "Lake B2B"], "Data & coverage"),
    ("what is the difference between span global and lakeb2b services", ["SPAN Global Services", "Lake B2B"], "Services"),
    ("LakeB2B vs SPAN vs Ampliz", ["Lake B2B", "SPAN Global Services", "Ampliz"], None),
    ("which is better, intent data or technographics?", ["intent data", "technographics"], None),
    ("How does LakeB2B differ from ZoomInfo?", ["LakeB2B", "ZoomInfo"], None),
    ("Compare Lake B2B and SPAN Global Services side by side: industries served", ["Lake B2B", "SPAN Global Services"], "Industries served"),
])
def test_detect(known, q, subjects, aspect):
    assert C.detect(q) == {"subjects": subjects, "aspect": aspect}


@pytest.mark.parametrize("q", ["What does LakeB2B do?", "I want to compare prices", "is it better than nothing", "Tell me about SPAN and Ampliz", ""])
def test_not_a_comparison(known, q):
    assert C.detect(q) is None


def test_switched_off(known, monkeypatch):
    monkeypatch.setattr(C.settings, "compare_enabled", False)
    assert C.detect("Compare LakeB2B and SPAN") is None and C.options()["enabled"] is False


def test_known_merges_a_company_page_and_its_website(monkeypatch):
    from app import knowledge

    monkeypatch.setattr(knowledge, "own_enabled", lambda: True)
    monkeypatch.setattr(knowledge, "active_sites", lambda: [{"slug": "lakeb2b", "name": "LakeB2B"}])
    monkeypatch.setattr("app.rag.retrieve.company_names", lambda: ["Ampliz", "Lake B2B"])
    assert [k["name"] for k in C._known()] == ["Ampliz", "Lake B2B"]
    monkeypatch.setattr(knowledge, "own_enabled", lambda: False)      # deependhq.com off: only the websites still on
    assert [k["name"] for k in C._known()] == ["LakeB2B"]


def _hit(title, site=None, text=None):
    return Hit(url=f"https://x/{title}", title=title, section=None, text=text or f"{title} text", score=0.8, metadata={"site": site} if site else {})


def test_balanced_hits_interleave_each_side():
    pages = {"Lake B2B": [_hit("Lake B2B data"), _hit("Lake B2B services"), _hit("other")],
             "SPAN Global Services": [_hit("SPAN data services", "spanglobalservices.com")]}
    searched = []

    def search(q, vec=None, today=None):
        searched.append(q)
        return pages["Lake B2B" if q.startswith("Lake") else "SPAN Global Services"]

    out = C.balanced_hits({"subjects": ["Lake B2B", "SPAN Global Services"], "aspect": "Services"}, search, lambda q: [0.1])
    assert searched == ["Lake B2B Services", "SPAN Global Services Services"]
    assert [h.title for h in out] == ["Lake B2B data", "SPAN data services", "Lake B2B services"]


def test_note_asks_for_a_table_and_no_verdict():
    n = C.note({"subjects": ["Lake B2B", "SPAN Global Services", "Ampliz"], "aspect": "Services"})
    assert "Lake B2B, SPAN Global Services and Ampliz compared side by side on services" in n
    assert "Table" in n and "Do not say which is better" in n and "Pricing is never in the table" in n


# ---------------------------------------------------------------- the chat turn (a fake model)
def _piece(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


class FakeStream:
    def __init__(self):
        self.calls = []

    def __call__(self, client, messages, tools, max_tokens=500, model=None):
        self.calls.append(messages)
        return iter([_piece("Both sell B2B data [1][2].")])


def test_a_comparison_turn_searches_each_side_and_asks_for_the_table():
    fake, logged = FakeStream(), []
    cmp = {"subjects": ["Lake B2B", "SPAN Global Services"], "aspect": None}
    side = [_hit("Lake B2B data"), _hit("SPAN data", "spanglobalservices.com")]
    with patch("app.chat.compare.detect", return_value=cmp), patch("app.chat.compare.balanced_hits", return_value=side), \
            patch("app.chat._create_stream", new=fake), patch("app.chat.search", return_value=[_hit("Lake B2B data")]), \
            patch("app.chat.embed_query", return_value=[0.1]), patch("app.chat.match_custom_answer", return_value=None), \
            patch("app.chat.get_guidance", return_value=""), patch("app.chat.titles.maybe_generate_async"), \
            patch("app.chat.log_event", side_effect=lambda k, s, d: logged.append((k, d))), patch("app.chat.inbox.log_message", return_value=7), \
            patch("app.chat.knowledge.scope_note", return_value=""), patch("app.chat.settings.ui_cards_enabled", True), \
            patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")):
        events = [json.loads(x[6:]) for x in respond("Compare LakeB2B and SPAN", [], "UTC", "s-cmp-1",
                                                     service=SimpleNamespace(session_id=None, list_schedules=lambda: []))
                  if x.startswith("data: ")]
    system = fake.calls[0][0]["content"]
    assert any(e["type"] == "status" and e.get("label") == "Comparing Lake B2B and SPAN Global Services…" for e in events)
    assert "COMPARISON: the visitor wants Lake B2B and SPAN Global Services compared side by side" in system
    assert "ANSWER CARD" in system   # the table is drawn by an answer card
    packed = json.dumps(fake.calls[0])   # both sides' pages reach the model
    assert "SPAN data" in packed and "Lake B2B data" in packed
    assert ("compare", {"subjects": cmp["subjects"], "aspect": None, "found": 2, "message": "Compare LakeB2B and SPAN"}) in logged


# ---------------------------------------------------------------- email me this chat: the email
TURNS = [
    {"role": "user", "text": "What does LakeB2B do?", "sources": []},
    {"role": "assistant", "text": "LakeB2B sells **B2B data** [1].\n\n- Intent data\n- Email lists [2]",
     "sources": [{"n": 1, "url": "https://lakeb2b.com/a", "title": "About"}, {"n": 2, "url": "https://lakeb2b.com/b", "title": "Lists"},
                 {"n": 3, "url": "https://lakeb2b.com/c", "title": "Unused"}]},
    {"role": "agent", "text": "Happy to help, Deep here.", "sources": [], "author": "Deep"},
]


def test_render_reads_well(monkeypatch):
    monkeypatch.setattr(CE.settings, "zoom_booking_base", "https://scheduler.zoom.us/x")
    subject, body = CE.render(TURNS, "Ada Lovelace", "LakeB2B's data")
    assert subject.endswith("assistant: LakeB2B's data")
    lines = body.split("\n")
    assert lines[0] == "Hi Ada," and "YOU ASKED" in lines and "THE ASSISTANT" in lines and "DEEP REPLIED" in lines
    assert "LakeB2B sells B2B data [1]." in lines and "• Intent data" in lines and "• Email lists [2]" in lines
    assert "• [1] About — https://lakeb2b.com/a" in lines and "• [2] Lists — https://lakeb2b.com/b" in lines
    assert "Unused" not in body and "Pages this answer used" in lines
    assert "book a short call with the button above" in body and 'reply "stop"' in body


def test_render_survives_html_wrap():
    from app import templates

    subject, body = CE.render(TURNS)
    html = templates.html_wrap(subject, templates._tidy(body), None, audience="visitor")
    assert "YOU ASKED" in html and "Pages this answer used" in html and "https://lakeb2b.com/a" in html and "Hi there," in html


# ---------------------------------------------------------------- the database side and the endpoint
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

    sid, vid = f"test-cmail-{uuid.uuid4().hex[:16]}", f"test-vid-{uuid.uuid4().hex[:12]}"
    tracking.ensure_session(sid, visitor_id=vid, ip="127.0.0.1", user_agent="pytest")
    inbox.log_message(sid, "user", "What does LakeB2B do?")
    yield sid, vid
    with conn() as c:
        for t in ("events", "leads", "messages", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


def test_send_needs_an_answer_keeps_the_lead_and_limits(chat):
    from app import inbox
    from app.db import conn

    sid, _ = chat
    sent = []
    fake = SimpleNamespace(enqueue=lambda to, subject, body, **kw: sent.append((to, subject, body, kw)))
    with pytest.raises(CE.Empty):
        CE.send(sid, "ajaykarthik.ldn+cmail@gmail.com", mailer=fake)
    inbox.log_message(sid, "assistant", "LakeB2B sells B2B data [1].", question="What does LakeB2B do?", outcome="answered",
                      sources=[{"n": 1, "url": "https://lakeb2b.com/a", "title": "About"}])
    inbox.log_message(sid, "assistant", "(stopped before any text)", question="x", outcome="stopped")
    r = CE.send(sid, "AjayKarthik.LDN+cmail@gmail.com", "Ada", mailer=fake)
    assert r == {"ok": True, "to": "ajaykarthik.ldn+cmail@gmail.com", "messages": 2}
    to, subject, body, kw = sent[0]
    assert to == "ajaykarthik.ldn+cmail@gmail.com" and kw["kind"] == "chat_email" and kw["reply_to"] == (CE.settings.host_email or None)
    assert "What does LakeB2B do?" in body and "stopped" not in body and "https://lakeb2b.com/a" in kw["html"]
    with conn() as c:
        leads = c.execute("SELECT name, email, status FROM leads WHERE session_id = %s", (sid,)).fetchall()
    assert leads == [("Ada", "ajaykarthik.ldn+cmail@gmail.com", "transcript")]
    CE.send(sid, "ajaykarthik.ldn+cmail@gmail.com", "Ada", mailer=fake)
    CE.send(sid, "ajaykarthik.ldn+cmail@gmail.com", "Ada", mailer=fake)
    with pytest.raises(CE.Limited):
        CE.send(sid, "ajaykarthik.ldn+cmail@gmail.com", "Ada", mailer=fake)
    with conn() as c:
        assert c.execute("SELECT count(*) FROM leads WHERE session_id = %s", (sid,)).fetchone()[0] == 1   # one lead, not one per email
    assert len(sent) == 3


def test_the_endpoint_only_sends_your_own_chat(chat):
    from fastapi.testclient import TestClient

    from app.main import app

    sid, vid = chat
    c = TestClient(app)
    with patch("app.main.chat_email.send", return_value={"ok": True, "to": "ajaykarthik.ldn+cmail@gmail.com", "messages": 2}) as send:
        ok = c.post("/chat/email", json={"session_id": sid, "email": "ajaykarthik.ldn+cmail@gmail.com"}, headers={"X-Visitor-Id": vid})
        assert ok.status_code == 200 and ok.json()["ok"] and send.call_count == 1
        other = c.post("/chat/email", json={"session_id": sid, "email": "ajaykarthik.ldn+cmail@gmail.com"}, headers={"X-Visitor-Id": "someone-else"})
        assert other.status_code == 404 and send.call_count == 1
        bad = c.post("/chat/email", json={"session_id": sid, "email": "not-an-email"}, headers={"X-Visitor-Id": vid})
        assert bad.status_code == 422
    with patch("app.main.chat_email.send", side_effect=CE.Limited()):
        assert c.post("/chat/email", json={"session_id": sid, "email": "ajaykarthik.ldn+cmail@gmail.com"}, headers={"X-Visitor-Id": vid}).status_code == 429
    with patch.object(CE.settings, "chat_email_enabled", False):
        assert c.post("/chat/email", json={"session_id": sid, "email": "ajaykarthik.ldn+cmail@gmail.com"}, headers={"X-Visitor-Id": vid}).status_code == 404
    opts = c.get("/compare/options").json()
    assert opts["aspects"][0] == "Services" and isinstance(opts["companies"], list)


def test_the_email_carries_a_comparison_table():
    program = ('root = Card("Lake B2B vs SPAN", [t])\nt = Table(\n  ["Aspect", "Lake B2B", "SPAN Global Services"],\n'
               '  [["Data", "Contact data [x]", "Intent data"], ["Reach", "-", "189+ countries"]]\n)')
    tb = CE.table(program)
    assert tb == {"columns": ["Aspect", "Lake B2B", "SPAN Global Services"],
                  "rows": [["Data", "Contact data [x]", "Intent data"], ["Reach", "-", "189+ countries"]]}
    assert CE.table('root = Card("x", [s])') is None and CE.table("Table([unclosed") is None
    _, body = CE.render([TURNS[0], {**TURNS[1], "table": tb}])
    lines = body.split("\n")
    assert "At a glance" in lines and "• Data — Lake B2B: Contact data [x] · SPAN Global Services: Intent data" in lines
    assert "• Reach — SPAN Global Services: 189+ countries" in lines   # a dash is left out
