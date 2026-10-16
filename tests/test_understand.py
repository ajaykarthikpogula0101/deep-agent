"""Small talk, greetings in front of questions, follow-ups, pinned pages and the loose-sources path (app/rag/understand.py,
app/rag/retrieve.py, app/chat.py). No DB, no model."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.chat import respond
from app.rag import prompts, understand
from app.rag.retrieve import Hit, pinned_rules


def _hit(score: float, url: str = "https://deependhq.com/x") -> Hit:
    return Hit(url=url, title="x", section=None, text="t", score=score, metadata={})


def _collect(gen) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in gen if line.startswith("data: ")]


def _piece(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


class FakeStream:
    def __init__(self, reply: str):
        self.reply, self.calls = reply, []

    def __call__(self, client, messages, tools, max_tokens=500):
        self.calls.append({"messages": messages, "tools": tools})
        return iter([_piece(self.reply[i:i + 7]) for i in range(0, len(self.reply), 7)])


class FakeClient:
    """client.chat.completions.create(...) -> a reply with .choices[0].message.content (or raises)."""

    def __init__(self, reply: str = "", exc: Exception | None = None):
        self.reply, self.exc, self.calls = reply, exc, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))], usage=None)


def _no_lang(message, history, client):
    return SimpleNamespace(english=None, code=None, name=None, note="")


def _spanish(message, history, client):
    return SimpleNamespace(english="hello", code="es", name="Spanish", note="\nThe visitor writes in Spanish.")


def _service():
    return SimpleNamespace(session_id=None, list_schedules=lambda: [])


def _text(events) -> str:
    return "".join(e.get("text", "") for e in events if e["type"] == "token")


# ---------------------------------------------------------------- pure helpers
@pytest.mark.parametrize("msg,kind", [
    ("hello", "greeting"), ("Hi!", "greeting"), ("hey there 👋", "greeting"), ("Good morning", "greeting"),
    ("hello deep", "greeting"), ("namaste", "greeting"), ("hi, how are you?", "how_are_you"),
    ("thanks", "thanks"), ("Thank you so much!", "thanks"), ("ok thanks", "thanks"), ("bye", "bye"),
    ("thanks, bye", "bye"), ("ok", "ack"), ("cool", "ack"), ("got it", "ack"), ("who are you?", "identity"),
    ("are you a bot", "identity"), ("what can you do?", "capabilities"), ("help", "capabilities"),
    ("hi, what can you do", "capabilities"), ("hii", "greeting"), ("heyyy", "greeting"), ("hey again", "greeting"),
    ("how r  u", "how_are_you"), ("how r u?", "how_are_you"), ("hru", "how_are_you"), ("hi, how's your day going", "how_are_you"),
    ("whats up", "how_are_you"), ("thnx", "thanks"), ("ok thnx bye", "bye"), ("am i talking to deep?", "identity"),
    ("who am i talking to", "identity"), ("are u a bot", "identity"),
])
def test_small_talk_is_recognised(msg, kind):
    assert understand.smalltalk_kind(msg) == kind


@pytest.mark.parametrize("msg", ["hi, who is Deep?", "hello what does Lake B2B do", "thanks for explaining Ampliz, what else",
                                 "what is Champions Group", "ok book a call", "", "hello " * 30])
def test_questions_are_not_small_talk(msg):
    assert understand.smalltalk_kind(msg) is None


def test_ack_after_an_offer_is_an_answer_not_small_talk():
    asked = [{"role": "user", "content": "what is lake b2b"}, {"role": "assistant", "content": "B2B data. [1] Want me to book a call?"}]
    told = [{"role": "assistant", "content": "Lake B2B sells B2B data. [1]"}]
    open_q = [{"role": "assistant", "content": "Hi there! What would you like to know about Deep?"}]
    assert understand.answers_a_question("ack", asked) and understand.answers_a_question("thanks", asked)
    assert not understand.answers_a_question("ack", told) and not understand.answers_a_question("ack", [])
    assert not understand.answers_a_question("ack", open_q)   # "ok" after an open question is still small talk
    assert not understand.answers_a_question("greeting", asked)


def test_fallback_replies_never_repeat_what_the_visitor_saw():
    first = understand.smalltalk_reply("greeting", [], pick=lambda xs: xs[0])
    assert first in understand.SMALLTALK_REPLIES["greeting"]
    hist = [{"role": "user", "content": "hii"}, {"role": "assistant", "content": first}]
    again = understand.smalltalk_reply("greeting", hist, pick=lambda xs: xs[0])
    assert again in understand.SMALLTALK_REPLIES["greeting_again"] and again != first
    seen = understand.SMALLTALK_REPLIES["how_are_you"][0]
    hist += [{"role": "user", "content": "how r u"}, {"role": "assistant", "content": seen}]
    assert understand.smalltalk_reply("how_are_you", hist, pick=lambda xs: xs[0]) != seen
    for kind, options in understand.SMALLTALK_REPLIES.items():
        assert len(options) >= 2 and len(set(options)) == len(options), kind


def test_small_talk_prompt_carries_the_conversation():
    hist = [{"role": "user", "content": "hii"}, {"role": "assistant", "content": "Hey! What brings you here?"}]
    msgs = understand.smalltalk_messages("hello", hist, " The visitor writes in Spanish.")
    assert msgs[0]["role"] == "system" and "Never repeat" in msgs[0]["content"] and msgs[0]["content"].endswith("Spanish.")
    assert msgs[1:] == [*hist, {"role": "user", "content": "hello"}]


def test_greeting_in_front_of_a_question_is_dropped_for_search():
    assert understand.strip_greeting("Hi Deep, who are you working with?") == "who are you working with?"
    assert understand.strip_greeting("hello! what is Lake B2B") == "what is Lake B2B"
    assert understand.strip_greeting("hello") == "hello"
    assert understand.strip_greeting("history of Ampliz") == "history of Ampliz"   # 'hi' inside a word is not a greeting


def test_follow_up_detection_needs_a_previous_question():
    hist = [{"role": "user", "content": "what is Lake B2B?"}, {"role": "assistant", "content": "B2B data. [1]"}]
    assert understand.is_follow_up("tell me more", hist)
    assert understand.is_follow_up("what about Ampliz?", hist)
    assert understand.is_follow_up("who runs it", hist)
    assert understand.is_follow_up("pricing?", hist)
    assert not understand.is_follow_up("tell me more", [])
    assert not understand.is_follow_up("what does Champions Accelerator invest in", hist)


def test_standalone_query_uses_the_model_and_falls_back():
    hist = [{"role": "user", "content": "what is Lake B2B?"}, {"role": "assistant", "content": "B2B data. [1]"}]
    client = FakeClient("Lake B2B pricing")
    assert understand.standalone_query("how much does it cost?", hist, client) == "Lake B2B pricing"
    sent = client.calls[0]["messages"][1]["content"]
    assert "Visitor: what is Lake B2B?" in sent and "how much does it cost?" in sent and client.calls[0]["temperature"] == 0
    assert understand.standalone_query("tell me more", hist, FakeClient(exc=RuntimeError("down"))) == "what is Lake B2B? tell me more"
    assert understand.standalone_query("tell me more", hist, FakeClient("")) == "what is Lake B2B? tell me more"


@pytest.mark.parametrize("q,rules", [
    ("who is Deep?", ["about"]), ("Who's Sreedeep?", ["about"]), ("where is he based", ["about"]),
    ("what does Deep do", ["about"]), ("tell me about him", ["about"]), ("what tools does he use", ["tools"]),
    ("what is his tech stack", ["tools"]), ("what is Deep working on right now", ["now"]),
    ("latest log entry", ["latest"]), ("what did he ship yesterday", ["latest"]), ("show me the most recent posts", ["latest"]),
    ("what is Lake B2B", []), ("what is day 338 about", []),
])
def test_pinned_pages_for_questions_vectors_answer_badly(q, rules):
    assert pinned_rules(q) == rules


# ---------------------------------------------------------------- chat flow
@patch("app.chat.titles.maybe_generate_async")
@patch("app.chat.lang.prepare", side_effect=_no_lang)
@patch("app.chat.log_event")
@patch("app.chat.search")
@patch("app.chat.embed_query")
def test_hello_gets_a_greeting_not_a_refusal(embed, search, log_event, *_):
    client = FakeClient("Hey! What would you like to know?")
    hist = [{"role": "user", "content": "hii"}, {"role": "assistant", "content": "Hi there! What brings you here?"}]
    with patch("app.chat.inbox.log_message", return_value=3) as log_message:
        events = _collect(respond("how r  u", hist, "UTC", "s-st-1", client=client))
    assert not [e for e in events if e["type"] in ("refusal", "handover_offer", "sources", "error")]
    assert {"type": "smalltalk", "kind": "how_are_you"} in events and events[-1] == {"type": "done"}
    assert _text(events) == "Hey! What would you like to know?"
    call = client.calls[0]
    assert call["temperature"] > 0.5 and call["timeout"] <= 10 and call["messages"][1:3] == hist   # it sees what it said before
    search.assert_not_called()
    embed.assert_not_called()
    assert log_event.call_args[0][0] == "smalltalk"
    assert log_message.call_args_list[-1][1]["outcome"] == "answered"


@patch("app.chat.titles.maybe_generate_async")
@patch("app.chat.lang.prepare", side_effect=_spanish)
@patch("app.chat.log_event")
@patch("app.chat.search")
def test_small_talk_in_another_language_is_written_by_the_model(search, *_):
    client = FakeClient("¡Hola! Soy el asistente de Deep.")
    with patch("app.chat.inbox.log_message", return_value=None):
        events = _collect(respond("hola", [], "UTC", "s-st-2", client=client))
    assert _text(events) == "¡Hola! Soy el asistente de Deep."
    assert "Spanish" in client.calls[0]["messages"][0]["content"]
    with patch("app.chat.inbox.log_message", return_value=None):   # the model failing: a fixed reply, never an error
        events = _collect(respond("hola", [], "UTC", "s-st-3", client=FakeClient(exc=RuntimeError("401 User not found"))))
    assert _text(events) in understand.SMALLTALK_REPLIES["greeting"] and not [e for e in events if e["type"] == "error"]
    search.assert_not_called()


@patch("app.chat.titles.maybe_generate_async")
@patch("app.chat.lang.prepare", side_effect=_no_lang)
@patch("app.chat.get_guidance", return_value="")
@patch("app.chat.match_custom_answer", return_value=None)
@patch("app.chat.embed_query", return_value=[0.1])
@patch("app.chat.log_event")
@patch("app.chat.search", return_value=[_hit(0.9)])
def test_yes_after_a_question_goes_to_the_model(search, *_):
    hist = [{"role": "user", "content": "what is Champions Accelerator"},
            {"role": "assistant", "content": "It backs early founders. [1] Want to know which companies it runs?"}]
    fake = FakeStream("It runs twelve companies. [1]")
    with patch("app.chat._create_stream", new=fake), patch("app.chat.inbox.log_message", return_value=None):
        events = _collect(respond("yes", hist, "UTC", "s-st-4", service=_service(),
                                  client=FakeClient("Champions Accelerator companies")))
    assert fake.calls and not [e for e in events if e["type"] == "smalltalk"]
    assert search.call_args[0][0] == "Champions Accelerator companies"   # 'yes' searched as the standalone question


@patch("app.chat.titles.maybe_generate_async")
@patch("app.chat.lang.prepare", side_effect=_no_lang)
@patch("app.chat.get_guidance", return_value="")
@patch("app.chat.match_custom_answer", return_value=None)
@patch("app.chat.embed_query", return_value=[0.1])
@patch("app.chat.log_event")
@patch("app.chat.search", return_value=[_hit(0.9)])
def test_greeting_and_follow_up_are_cleaned_before_search(search, *_):
    fake = FakeStream("Deep is Group CMO at Champions Group. [1]")
    with patch("app.chat._create_stream", new=fake), patch("app.chat.inbox.log_message", return_value=None):
        _collect(respond("Hi there, who is Deep?", [], "UTC", "s-st-5", service=_service(), client=FakeClient(exc=AssertionError())))
        assert search.call_args[0][0] == "who is Deep?"
        hist = [{"role": "user", "content": "what is Lake B2B?"}, {"role": "assistant", "content": "B2B data. [1]"}]
        _collect(respond("tell me more", hist, "UTC", "s-st-6", service=_service(), client=FakeClient("Lake B2B services and data")))
        assert search.call_args[0][0] == "Lake B2B services and data"
    system = fake.calls[0]["messages"][0]["content"]
    assert "deep@championsmail.com" in system or "Contact facts" in system   # how to reach Deep is always known


def test_the_model_knows_todays_date_in_the_visitors_timezone():
    from datetime import datetime, timezone

    from app.chat import _today

    late = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
    assert _today("Asia/Kolkata", late) == "\nToday is Friday, 2026-10-16 in the visitor's timezone."
    assert _today("America/New_York", late) == "\nToday is Thursday, 2026-10-15 in the visitor's timezone."
    assert _today("Not/AZone", late).endswith("2026-10-15 in the visitor's timezone.")


def _weak_turn(reply: str, score: float = 0.55):
    fake = FakeStream(reply)
    with patch("app.chat.search", return_value=[_hit(score), _hit(score - 0.01, "https://deependhq.com/toolkit")]), \
            patch("app.chat.embed_query", return_value=[0.1]), patch("app.chat.match_custom_answer", return_value=None), \
            patch("app.chat.get_guidance", return_value=""), patch("app.chat.titles.maybe_generate_async"), \
            patch("app.chat.lang.prepare", side_effect=_no_lang), patch("app.chat._create_stream", new=fake), \
            patch("app.chat.log_event") as log_event, patch("app.chat.inbox.log_message", return_value=9) as log_message:
        events = _collect(respond("what does he think about remote work", [], "UTC", "s-weak", service=_service()))
    return fake, events, log_event, log_message


def test_loose_sources_go_to_the_model_with_a_caution():
    fake, events, log_event, log_message = _weak_turn("He prefers async work. [1]")
    system = fake.calls[0]["messages"][0]["content"]
    assert prompts.WEAK_SOURCES_NOTE in system and fake.calls[0]["tools"] is None
    assert [e for e in events if e["type"] == "sources"][0]["items"][0]["url"] == "https://deependhq.com/x"
    assert not [e for e in events if e["type"] in ("refusal", "handover_offer", "ui")]
    assert log_message.call_args_list[-1][1]["outcome"] == "answered"


def test_uncited_answer_from_loose_sources_counts_as_a_refusal():
    reply = "I couldn't find that on deependhq.com. I can tell you what Deep is building or book you a call."
    fake, events, log_event, log_message = _weak_turn(reply)
    types = [e["type"] for e in events if e["type"] not in ("status", "lang")]
    assert types[-4:] == ["refusal", "handover_offer", "meta", "done"] and _text(events) == reply
    assert [c for c in log_event.call_args_list if c[0][0] == "refusal"][0][0][2]["answered_by"] == "model"
    assert log_message.call_args_list[-1][1]["outcome"] == "refused"   # still shows up in the unanswered-questions list


def test_below_the_soft_floor_is_still_refused_without_a_model_call():
    fake, events, log_event, _ = _weak_turn("unused", score=0.40)
    assert not fake.calls
    assert [e for e in events if e["type"] == "refusal"] == [{"type": "refusal", "reason": "low_confidence"}]
    assert _text(events) == prompts.REFUSAL_NO_CONTEXT
