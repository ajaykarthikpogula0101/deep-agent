"""Visitor detections (app/intent.py): wrong-fit visitors and the buying moment, plus the console switches and the Knowledge
wording the widget gets (app/knowledge.py)."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import intent as I
from app import knowledge as K
from app.chat import respond
from app.rag.retrieve import Hit

_REAL_ALERT_ASYNC = I.alert_async   # captured at import, before the conftest stub replaces it for each test


# ---------------------------------------------------------------- wrong fit
@pytest.mark.parametrize("message,kind", [
    ("Are you hiring?", "job"),
    ("Hi, I'm looking for a job in marketing, any openings?", "job"),
    ("Can I send my CV to someone?", "job"),
    ("Do you have internships for freshers", "job"),
    ("I'd like to join your team", "job"),
    ("We offer SEO and web development services at great rates", "seller"),
    ("Can I pitch our services to you?", "seller"),
    ("Do you accept guest posts?", "seller"),
    ("I'm a student working on my college project about B2B marketing", "student"),
    ("for my thesis I want to understand how Deep built these companies", "student"),
])
def test_wrong_fit(message, kind):
    assert I.wrong_fit(message) == kind


@pytest.mark.parametrize("message", [
    "What does LakeB2B do?",
    "We provide marketing services and need contact lists of CMOs",           # a seller who buys data is a customer
    "Do you have email lists of HR managers who are hiring?",                   # asks for data, not a job
    "I'm a student recruiter looking for university contacts database",
    "How do I book a call with Deep?",
    "",
])
def test_not_wrong_fit(message):
    assert I.wrong_fit(message) is None


# ---------------------------------------------------------------- buying moment
def test_buying_needs_two_kinds_and_a_sign_now():
    m = I.buying("What's the price for 50,000 nurse contacts?", [])
    assert m and m["kinds"] == ["price", "volume"]
    assert "50,000" in m["details"]["volume"] and "named a volume (50,000" in m["why"]
    assert I.buying("How much does it cost?", []) is None                                    # one kind
    assert I.buying("Thanks", ["How much does it cost?", "We need 10k leads"]) is None      # nothing now
    later = I.buying("We need them by Friday", ["How much does it cost?"])
    assert later["kinds"] == ["price", "timeline"] and later["details"]["timeline"].lower() == "by friday"
    assert I.buying("send us a quote, our budget is $5,000", [])["kinds"] == ["price", "budget", "decision"]


@pytest.mark.parametrize("message,earlier", [
    ("What does LakeB2B do?", []),
    ("What is your email bounce rate?", ["Tell me about SPAN"]),
    ("Our 2 companies are in Texas", ["What's new?"]),
])
def test_no_buying_moment(message, earlier):
    assert I.buying(message, earlier) is None


def test_volume_words():
    for text, vol in [("we need 10k leads", "10k leads"), ("2 million emails", "2 million emails"),
                      ("about 5,000 verified physicians", "5,000 verified physicians")]:
        assert I._kinds(text)["volume"].lower() == vol


def test_alert_email_reads_well():
    m = I.buying("How much for 20,000 IT managers? We need them by Friday.", [])
    subject, body = I.render_alert(m, {"city": "Austin", "country": "United States", "page": "https://deependhq.com/companies",
                                       "net_org": "Acme Corp", "questions": ["Do you have IT manager lists?", "How much for 20,000 IT managers?"]})
    assert subject == "Hot visitor on the site now: 20,000 IT managers · needs it by Friday"
    assert "BUYING SIGNS" in body and 'named a volume: "20,000 IT managers"' in body and "Location: Austin, United States" in body
    assert "they do not change the lead score" in body


# ---------------------------------------------------------------- the chat turn (a fake model)
def _piece(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


class FakeStream:
    def __init__(self):
        self.calls = []

    def __call__(self, client, messages, tools, max_tokens=500, model=None):
        self.calls.append(messages)
        return iter([_piece("LakeB2B sells B2B data [1].")])


class FakeClient:
    def __init__(self, reply="Thanks for your interest! This chat is for customers, so I can't help with jobs here."):
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.reply = reply

    def _create(self, **kw):
        self.sent.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))], usage=None)


def _turn(message, fit=None, buy=None, fr=None):
    fake, client, searched, alerts = FakeStream(), FakeClient(), [], []
    hit = Hit(url="https://deependhq.com/x", title="x", section=None, text="LakeB2B sells data", score=0.9, metadata={})
    with patch("app.chat.intent.check_fit", return_value=fit), patch("app.chat.intent.check_buying", return_value=buy), \
            patch("app.chat.intent.alert_async", side_effect=lambda sid, m: alerts.append(m)), \
            patch("app.chat.mood.check", return_value=fr), patch("app.chat.intent.enabled", return_value=True), \
            patch("app.chat._create_stream", new=fake), \
            patch("app.chat.search", side_effect=lambda *a, **k: searched.append(1) or [hit]), patch("app.chat.embed_query", return_value=[0.1]), \
            patch("app.chat.match_custom_answer", return_value=None), patch("app.chat.get_guidance", return_value=""), \
            patch("app.chat.titles.maybe_generate_async"), patch("app.chat.log_event"), \
            patch("app.chat.inbox.log_message", return_value=7), \
            patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")):
        events = [json.loads(x[6:]) for x in respond(message, [], "UTC", "s-intent-1", client=client,
                                                     service=SimpleNamespace(session_id=None, list_schedules=lambda: []))
                  if x.startswith("data: ")]
    return events, (fake.calls[0][0]["content"] if fake.calls else ""), client, searched, alerts


def test_a_job_seeker_gets_a_short_reply_and_the_route_not_a_search():
    fit = {"kind": "job", "label": "job seeker", "link": "https://example.com/careers", "button": "See open roles"}
    events, system, client, searched, _ = _turn("Are you hiring?", fit=fit)
    assert [e for e in events if e["type"] == "wrong_fit"] == [{"type": "wrong_fit", "kind": "job", "link": "https://example.com/careers",
                                                               "button": "See open roles"}]
    text = "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert text.startswith("Thanks for your interest") and not searched and not system
    assert not [e for e in events if e["type"] in ("handover_offer", "refusal", "buying")]
    assert "https://example.com/careers" in client.sent[0]["messages"][0]["content"]


def test_the_fixed_reply_when_the_model_is_down():
    assert I.fit_reply_fixed("job", "https://example.com/careers").endswith("You can see open roles here: https://example.com/careers")
    assert I.fit_reply_fixed("seller", "mailto:partners@example.com").endswith("here: partners@example.com")
    assert "careers page" in I.fit_reply_fixed("job")


def test_a_student_is_answered_without_a_call_offer():
    fit = {"kind": "student", "label": "student", "link": "", "button": "Read more"}
    events, system, _, searched, _ = _turn("I'm a student, what does LakeB2B do?", fit=fit)
    assert searched and "seems to be a student" in system
    assert "".join(e.get("text", "") for e in events if e["type"] == "token") == "LakeB2B sells B2B data [1]."


def test_a_buying_moment_offers_a_call_and_tells_deep_once():
    buy = {"kinds": ["price", "volume"], "details": {"price": "price", "volume": "50,000 contacts"},
           "why": "asked about price; named a volume (50,000 contacts)", "offer": True}
    events, system, _, _, alerts = _turn("What's the price for 50,000 contacts?", buy=buy)
    kinds = [e["type"] for e in events if e["type"] not in ("status", "lang")]
    assert kinds.index("buying") < kinds.index("token") and len(alerts) == 1
    assert "The visitor is showing buying intent (asked about price; named a volume (50,000 contacts))" in system
    events, system, _, _, alerts = _turn("And by Friday?", buy={**buy, "offer": False})   # later turns: the note only
    assert not [e for e in events if e["type"] == "buying"] and "buying intent" in system
    assert alerts == []   # Deep was told on the first one


def test_frustration_card_wins_over_the_buying_card():
    buy = {"kinds": ["price", "volume"], "details": {}, "why": "x", "offer": True}
    fr = {"score": 4, "frustrated": True, "reasons": ["says_so"], "offer": True, "why": "said it isn't helping"}
    events, system, _, _, alerts = _turn("this is useless, what's the price for 10k leads?", buy=buy, fr=fr)
    assert [e["type"] for e in events if e["type"] in ("buying", "frustration")] == ["frustration"]
    assert len(alerts) == 1 and "seems frustrated" in system and "buying intent" in system   # Deep is still told


def test_alert_async_respects_the_switch_and_the_offer(monkeypatch):
    started = []
    monkeypatch.setattr(I.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: started.append(kw)))
    monkeypatch.setattr(I.settings, "host_email", "ajaykarthik.ldn+intent@gmail.com")
    monkeypatch.setattr(I, "enabled", lambda name: True)
    _REAL_ALERT_ASYNC("s1", {"offer": False})
    _REAL_ALERT_ASYNC("s1", {"offer": True})
    monkeypatch.setattr(I, "enabled", lambda name: name != "buying_alerts")
    _REAL_ALERT_ASYNC("s1", {"offer": True})
    assert len(started) == 1 and started[0]["args"] == ("s1", {"offer": True})


# ---------------------------------------------------------------- switches and routes (settings stubbed: no real rows)
@pytest.fixture
def store(monkeypatch):
    rows: dict[str, str] = {}
    monkeypatch.setattr(I, "get_setting", rows.get)
    monkeypatch.setattr(I, "set_setting", lambda k, v: rows.pop(k, None) if v is None else rows.__setitem__(k, v))
    monkeypatch.setattr(I, "_counts", lambda days: {"frustration": 1, "wrong_fit": 2, "buying": 3, "buying_alerts": 1})
    I.clear_cache()
    yield rows
    I.clear_cache()


def test_switches(store, monkeypatch):
    assert I.enabled("buying") and I.enabled("wrong_fit") and I.enabled("frustration")
    st = I.set_switch("buying", False)
    assert store["detect:buying"] == "off" and not I.enabled("buying")
    assert [s["count"] for s in st["switches"]] == [1, 2, 3, 1] and [s["on"] for s in st["switches"]] == [True, True, False, True]
    I.set_switch("buying", True)
    assert "detect:buying" not in store and I.enabled("buying")
    monkeypatch.setattr(I.settings, "wrong_fit_detection", False)
    I.clear_cache()
    assert not I.enabled("wrong_fit") and I.check_fit("s1", "Are you hiring?") is None
    with pytest.raises(LookupError):
        I.set_switch("nope", True)


def test_routes(store):
    I.set_route("job", "https://example.com/careers", "Open roles")
    assert I.route("job") == {"link": "https://example.com/careers", "label": "Open roles"}
    I.set_route("seller", "partners@example.com", "")
    assert I.route("seller") == {"link": "mailto:partners@example.com", "label": "Send your proposal"}
    with pytest.raises(ValueError):
        I.set_route("job", "javascript:alert(1)", "")
    I.set_route("job", "", "")
    assert I.route("job") == {"link": "", "label": "See open roles"}


# ---------------------------------------------------------------- Knowledge: the visitor-facing wording
def _sources(lake=True, span=True, own=True):
    return [{"key": "deependhq", "name": "deependhq.com", "host": "deependhq.com", "on": own},
            {"key": "lakeb2b", "name": "LakeB2B", "host": "lakeb2b.com", "on": lake},
            {"key": "spanglobalservices", "name": "Span Global Services", "host": "spanglobalservices.com", "on": span}]


@pytest.mark.parametrize("lake,span,brand", [(True, True, "LakeB2B"), (False, True, "Span Global Services"), (False, False, None)])
def test_brand_follows_the_switches(monkeypatch, lake, span, brand):
    monkeypatch.setattr(K, "sources", lambda: _sources(lake, span))
    monkeypatch.setattr(K, "own_enabled", lambda: True)
    scope = K.widget_scope(["What is LakeB2B?", "What does Lake B2B do?", "Tell me about SPAN", "What is Deep working on?"])
    assert scope["brand"] == brand
    kept = scope["suggestions"]
    assert ("What is LakeB2B?" in kept) == lake and ("What does Lake B2B do?" in kept) == lake
    assert ("Tell me about SPAN" in kept) == span and "What is Deep working on?" in kept


def test_widget_scope_never_breaks_the_widget(monkeypatch):
    monkeypatch.setattr(K, "sources", lambda: 1 / 0)
    assert K.widget_scope(["a"]) == {"brand": "LakeB2B", "own": True, "suggestions": ["a"]}


def test_extras_switches(monkeypatch):
    rows: dict[str, str] = {}
    monkeypatch.setattr(K, "get_setting", rows.get)
    monkeypatch.setattr(K, "set_setting", lambda k, v: rows.pop(k, None) if v is None else rows.__setitem__(k, v))
    monkeypatch.setattr(K, "sources", lambda: [])
    K.clear_cache()
    assert K.extra_enabled("help") and K.extra_enabled("custom")
    K.set_source("custom", False)
    assert rows == {"kb:custom": "off"} and not K.extra_enabled("custom") and K.extra_enabled("help")
    K.set_source("custom", True)
    assert rows == {} and K.extra_enabled("custom")
    K.clear_cache()


def test_custom_answers_switch_is_honoured_in_the_chat():
    called = []
    with patch("app.chat.knowledge.extra_enabled", side_effect=lambda k: k != "custom"):
        with patch("app.chat.match_custom_answer", side_effect=lambda v: called.append(v)):
            _turn_custom()
    assert not called


def _turn_custom():
    hit = Hit(url="https://deependhq.com/x", title="x", section=None, text="LakeB2B sells data", score=0.9, metadata={})
    with patch("app.chat.intent.check_fit", return_value=None), patch("app.chat.intent.check_buying", return_value=None), \
            patch("app.chat.mood.check", return_value=None), patch("app.chat._create_stream", new=FakeStream()), \
            patch("app.chat.search", return_value=[hit]), patch("app.chat.embed_query", return_value=[0.1]), \
            patch("app.chat.get_guidance", return_value=""), patch("app.chat.titles.maybe_generate_async"), patch("app.chat.log_event"), \
            patch("app.chat.inbox.log_message", return_value=7), patch("app.chat.knowledge.scope_note", return_value=""), \
            patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")):
        list(respond("What does LakeB2B do?", [], "UTC", "s-intent-2", client=FakeClient(),
                     service=SimpleNamespace(session_id=None, list_schedules=lambda: [])))


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

    I.clear_cache()
    sid = f"test-intent-{uuid.uuid4().hex[:16]}"
    inbox.log_message(sid, "user", "Do you have IT manager email lists?")
    inbox.log_message(sid, "assistant", "Yes, LakeB2B has them [1].", question="Do you have IT manager email lists?", outcome="answered")
    yield sid
    with conn() as c:
        for t in ("events", "leads", "messages", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


def test_buying_moment_is_offered_once_and_alerted(chat, monkeypatch):
    from app import inbox

    sid = chat
    monkeypatch.setattr(I, "enabled", lambda name: True)
    assert I.check_buying(sid, "Do you have IT manager email lists?") is None
    inbox.log_message(sid, "user", "How much for 20,000 IT managers?")
    first = I.check_buying(sid, "How much for 20,000 IT managers?")
    assert first["offer"] and first["kinds"] == ["price", "volume"]
    inbox.log_message(sid, "user", "we need them by Friday")
    later = I.check_buying(sid, "we need them by Friday")
    assert later["offer"] is False and later["kinds"] == ["price", "volume", "timeline"]

    sent = []
    fake = SimpleNamespace(enqueue=lambda to, subject, body, **kw: sent.append((to, subject, body, kw)))
    monkeypatch.setattr(I.settings, "host_email", "ajaykarthik.ldn+intent@gmail.com")
    assert I._alert(sid, first, mailer=fake)
    assert sent[0][0] == "ajaykarthik.ldn+intent@gmail.com" and "Hot visitor on the site now: 20,000 IT managers" in sent[0][1]
    assert "How much for 20,000 IT managers?" in sent[0][2] and sent[0][3]["kind"] == "buying_alert"
    assert inbox.metrics(1)["buying"] >= 1
    row = [c for c in inbox.conversations(1, 500) if c["session_id"] == sid][0]
    assert row["buying"] is True and row["wrong_fit"] is None


def test_wrong_fit_is_logged_once_and_blocks_the_buying_moment(chat, monkeypatch):
    from app import inbox
    from app.db import conn

    sid = chat
    monkeypatch.setattr(I, "enabled", lambda name: True)
    monkeypatch.setattr(I, "route", lambda kind: {"link": "", "label": I.FIT_DEFAULT_BUTTON[kind]})
    assert I.check_fit(sid, "Are you hiring? I can send my CV")["kind"] == "job"
    assert I.check_fit(sid, "any job openings?")["kind"] == "job"
    with conn() as c:
        assert c.execute("SELECT count(*) FROM events WHERE session_id = %s AND kind = 'wrong_fit'", (sid,)).fetchone()[0] == 1
    assert I.is_wrong_fit(sid)
    inbox.log_message(sid, "user", "how much for 10k leads?")
    assert I.check_buying(sid, "how much for 10k leads?") is None
    assert [c for c in inbox.conversations(1, 500) if c["session_id"] == sid][0]["wrong_fit"] == "job"


def test_no_buying_card_after_a_booking(chat, monkeypatch):
    from app import inbox
    from app.db import conn

    sid = chat
    monkeypatch.setattr(I, "enabled", lambda name: True)
    with conn() as c:
        c.execute("INSERT INTO leads(name, email, reason, status, session_id) VALUES ('Ada', 'ajaykarthik.ldn+intent@gmail.com', 'x', 'booked', %s)", (sid,))
        c.commit()
    inbox.log_message(sid, "user", "How much for 20,000 IT managers?")
    assert I.check_buying(sid, "How much for 20,000 IT managers?") is None
