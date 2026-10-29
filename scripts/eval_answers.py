"""Answer-quality check: ask the real bot a fixed set of questions and grade every answer.

    python scripts/eval_answers.py                  # all cases in tests/eval/questions.json
    python scripts/eval_answers.py who_is_deep hello # only these ids
    python scripts/eval_answers.py --out report.json

Runs app.chat.respond in-process against the real index (Postgres) and the real model (LLM_API_KEY), so it costs a few
cents per run. Nothing is written: inbox, events, titles and memory are switched off for the run. Exit code 1 when any
case fails, so it can gate a deploy or run after a recrawl or a prompt change. Each case's checks are described in the
questions file.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASES = ROOT / "tests" / "eval" / "questions.json"
_CITE = re.compile(r"\[\d{1,2}(\s*,\s*\d{1,2})*\]")


def grade(expect: dict, events: list[dict], text: str) -> list[str]:
    """The failed checks for one answer (empty = pass). Pure: tests/test_eval_answers.py covers it."""
    low, fails = text.lower(), []
    types = [e.get("type") for e in events]
    refusal = next((e for e in events if e.get("type") == "refusal"), None)
    sources = [s.get("url", "") for e in events if e.get("type") == "sources" for s in e.get("items", [])]
    if "smalltalk" in expect and ("smalltalk" in types) != expect["smalltalk"]:
        fails.append(f"smalltalk should be {expect['smalltalk']}")
    if "refused" in expect and bool(refusal) != expect["refused"]:
        fails.append("should be refused" if expect["refused"] else f"refused ({refusal and refusal.get('reason')})")
    if expect.get("refusal_reason") and (not refusal or refusal.get("reason") != expect["refusal_reason"]):
        fails.append(f"refusal reason should be {expect['refusal_reason']}")
    if expect.get("cited") and not _CITE.search(text):
        fails.append("no [n] citation")
    if expect.get("contains_any") and not any(w.lower() in low for w in expect["contains_any"]):
        fails.append(f"none of {expect['contains_any']}")
    for w in expect.get("contains_all", []):
        if w.lower() not in low:
            fails.append(f"missing {w!r}")
    for w in expect.get("not_contains", []):
        if w.lower() in low:
            fails.append(f"contains {w!r}")
    if expect.get("source_contains") and not any(expect["source_contains"] in u for u in sources):
        fails.append(f"no source with {expect['source_contains']!r}")
    if expect.get("event") and expect["event"] not in types:
        fails.append(f"no {expect['event']!r} event")
    if expect.get("max_words") and len(text.split()) > expect["max_words"]:
        fails.append(f"{len(text.split())} words > {expect['max_words']}")
    if "error" in types:
        fails.append("model error")
    return fails


def run(ids: list[str] | None = None, out: str | None = None) -> int:
    from app.chat import respond

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    svc = SimpleNamespace(session_id=None, list_schedules=lambda: [
        SimpleNamespace(slug="discovery-call", name="Discovery Call", duration_min=15)])
    results, t_all = [], time.monotonic()
    with patch("app.chat.inbox.log_message", return_value=None), patch("app.chat.log_event"), \
            patch("app.chat.titles.maybe_generate_async"), patch("app.chat.session_memory.update_async"), \
            patch("app.chat.team.visitor_wrote"):
        for c in cases:
            history = [{"role": r, "content": t} for r, t in c.get("history", [])]
            t0 = time.monotonic()
            try:
                events = [json.loads(x[6:]) for x in respond(c["q"], history, "Asia/Kolkata", None, service=svc) if x.startswith("data: ")]
            except Exception as e:   # a crash is a failure of this case, not of the run
                events = [{"type": "error", "error": str(e)}]
            text = "".join(e.get("text", "") for e in events if e.get("type") == "token")
            fails = grade(c.get("expect", {}), events, text)
            results.append({"id": c["id"], "q": c["q"], "ok": not fails, "fails": fails, "seconds": round(time.monotonic() - t0, 1),
                            "answer": text[:600]})
            print(f"{'PASS' if not fails else 'FAIL'}  {c['id']:<20} {results[-1]['seconds']:>5}s  {'; '.join(fails)}")
    passed = sum(r["ok"] for r in results)
    print(f"\n{passed}/{len(results)} passed in {time.monotonic() - t_all:.0f}s")
    for r in results:
        if not r["ok"]:
            print(f"\n--- {r['id']}: {r['q']}\n{r['answer']}")
    if out:
        Path(out).write_text(json.dumps({"passed": passed, "total": len(results), "results": results}, indent=1), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        args = args[:i] + args[i + 2:]
    sys.exit(run(args or None, out))
