"""The answer-quality checker (scripts/eval_answers.py) itself: the questions file is valid and the grading is right.
The live run (real model) is the script, not this test."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("eval_answers", ROOT / "scripts" / "eval_answers.py")
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

KNOWN = {"smalltalk", "refused", "refusal_reason", "cited", "contains_any", "contains_all", "not_contains", "source_contains", "event",
         "max_words"}


def test_questions_file_is_valid():
    cases = json.loads((ROOT / "tests" / "eval" / "questions.json").read_text(encoding="utf-8"))["cases"]
    ids = [c["id"] for c in cases]
    assert len(cases) >= 35 and len(ids) == len(set(ids))
    for c in cases:
        assert c["q"].strip() and set(c["expect"]) <= KNOWN, c["id"]
        for role, text in c.get("history", []):
            assert role in ("user", "assistant") and text


def test_grading():
    ev = [{"type": "sources", "items": [{"url": "https://deependhq.com/toolkit"}]}, {"type": "token", "text": "x"}]
    assert E.grade({"cited": True, "source_contains": "toolkit"}, ev, "Deep uses ChampBeam. [1]") == []
    assert E.grade({"cited": True}, ev, "Deep uses ChampBeam.") == ["no [n] citation"]
    assert E.grade({"refused": True}, [{"type": "refusal", "reason": "low_confidence"}], "no") == []
    assert E.grade({"refused": False}, [{"type": "refusal", "reason": "low_confidence"}], "no") == ["refused (low_confidence)"]
    assert E.grade({"refusal_reason": "injection"}, [{"type": "refusal", "reason": "low_confidence"}], "") == ["refusal reason should be injection"]
    assert E.grade({"contains_all": ["12", "Ampliz"], "not_contains": ["15 companies"]}, [], "12 companies incl. Ampliz") == []
    assert E.grade({"contains_all": ["12"]}, [], "15 companies") == ["missing '12'"]
    assert E.grade({"smalltalk": True}, [{"type": "smalltalk"}], "hi") == []
    assert E.grade({"event": "schedules"}, [], "") == ["no 'schedules' event"]
    assert E.grade({"max_words": 3}, [], "one two three four") == ["4 words > 3"]
    assert E.grade({}, [{"type": "error"}], "") == ["model error"]
