"""Multilingual answers: detection, conversation language, translation call shape, localized refusals."""
from __future__ import annotations

from types import SimpleNamespace

from app import lang
from app.rag import prompts


def test_detects_common_languages_and_leaves_english_alone():
    assert lang.detect("¿Qué hace Lake B2B y cómo puedo reservar una llamada?") == "es"
    assert lang.detect("Qu'est-ce que fait Lake B2B ? Je veux réserver un appel.") == "fr"
    assert lang.detect("Was macht Lake B2B und wie kann ich einen Termin buchen?") == "de"
    assert lang.detect("O que a Lake B2B faz? Quero agendar uma chamada.") == "pt"
    assert lang.detect("Cosa fa Lake B2B? Voglio prenotare una chiamata.") == "it"
    assert lang.detect("डीप किस पर काम कर रहे हैं?") == "hi"
    assert lang.detect("Что делает Lake B2B?") == "ru"
    for en in ("What does Lake B2B do?", "book a call with Deep", "Tell me about the companies", "what did Deep ship on day 338?",
               "ada@lovelace.org", "", None):
        assert lang.detect(en) is None, en
    assert lang.looks_english("Ada Lovelace, ada@lovelace.org, about EU fintech data")


def test_short_follow_ups_keep_the_conversation_language():
    history = [{"role": "user", "content": "Quiero reservar una llamada con Deep"}, {"role": "assistant", "content": "Claro."}]
    assert lang.conversation_language("Ada Lovelace, ada@lovelace.org", history) == "es"
    assert lang.conversation_language("Ada Lovelace, ada@lovelace.org", []) is None
    long_english = "I would like to know more about what Deep is building this quarter and the companies"
    assert lang.conversation_language(long_english, history) is None  # a real English sentence switches back


class FakeClient:
    def __init__(self, reply="What does Lake B2B do?"):
        self.calls = []
        self.reply = reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


def test_prepare_translates_for_retrieval_and_notes_the_language(monkeypatch):
    monkeypatch.setattr(lang.settings, "multilingual", True)
    c = FakeClient()
    li = lang.prepare("¿Qué hace Lake B2B?", [], c)
    assert li.code == "es" and li.english == "What does Lake B2B do?" and "Spanish" in li.note and li.name == "Spanish"
    assert c.calls[0]["temperature"] == 0 and c.calls[0]["messages"][1]["content"] == "¿Qué hace Lake B2B?"
    # a bare email in a Spanish conversation: language kept, no translation call
    c2 = FakeClient()
    li2 = lang.prepare("ada@lovelace.org", [{"role": "user", "content": "Quiero reservar una llamada con Deep"}], c2)
    assert li2.code == "es" and li2.english is None and c2.calls == []
    # English: nothing happens, no call
    c3 = FakeClient()
    assert lang.prepare("What does Lake B2B do?", [], c3) is lang.NONE and c3.calls == []
    monkeypatch.setattr(lang.settings, "multilingual", False)
    assert lang.prepare("¿Qué hace Lake B2B?", [], FakeClient()) is lang.NONE


def test_translation_failure_falls_back_to_the_original_text():
    class Broken:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))))

    assert lang.translate_to_english("¿Qué hace Lake B2B?", Broken()) == "¿Qué hace Lake B2B?"


def test_refusals_are_localized_with_an_english_fallback():
    assert lang.refusal("es").startswith("No encontré") and "scheduler.zoom.us/sreedeep" in lang.refusal("es")
    assert lang.refusal("hi").endswith("।")
    assert lang.refusal("xx") == prompts.REFUSAL_NO_CONTEXT and lang.refusal(None) == prompts.REFUSAL_NO_CONTEXT
    assert "11. Language:" in prompts.SYSTEM_PROMPT
