"""Rich weekly digest (app/digest_rich.py): fake model client and fake Node subprocess; every fallback reason;
send() keeps the plain text as the text part and the 3-arg send_plain when there is no HTML."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from html import escape
from types import SimpleNamespace

import pytest

from app import digest, digest_rich
from app.config import settings
from app.templates import DEFAULTS

METRICS = {
    "days": 7, "conversations": 42, "questions": 97, "resolved": 70, "refused": 12, "handovers": 3, "custom": 5, "errors": 1,
    "resolution_rate": 0.814, "bookings": 5, "handover_leads": 2, "enquiries": 1,
    "csat": {"up": 23, "down": 2, "score": 0.92}, "median_latency_ms": 2140, "daily": [],
    "top_questions": [{"question": "what does lake b2b do?", "count": 9}, {"question": "who is deep?", "count": 6}],
}
PREV = {"conversations": 30, "questions": 80, "resolution_rate": 0.75}
GAPS = {"unanswered": [{"question": "what is the pricing?", "count": 3, "last": "x", "reason": "low_confidence"}],
        "thumbs_down": [{"id": 1}]}
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)
LEADS = [
    {"ts": NOW - timedelta(days=2), "name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "EU fintech data",
     "status": "handoff", "slot_start": NOW + timedelta(days=1), "schedule_slug": "discovery-call",
     "company": "Lovelace Analytical Engines (lovelace.org) · Computation", "confirmed_at": None, "nudged_at": NOW},
    {"ts": NOW - timedelta(days=3), "name": "Bob", "email": "bob@gmail.com", "reason": "", "status": "handover",
     "slot_start": None, "schedule_slug": None, "company": None, "confirmed_at": None, "nudged_at": None},
]
PERIOD = "29 Sep – 06 Oct 2026"
PROGRAM = """root = EmailTemplate("[Champions Group] Weekly digest: 42 conversations, 5 bookings · 29 Sep – 06 Oct 2026", "29 Sep – 06 Oct 2026", [h, b])
h = EmailHeading("Weekly digest")
b = EmailButton("Open the console", "https://deependhq.com/admin", "#F28C28")"""


def _d() -> dict:
    subject, body = digest.render(METRICS, PREV, GAPS, LEADS, PERIOD, DEFAULTS)
    return {"days": 7, "subject": subject, "body": body, "to": "owner@example.com", "metrics": METRICS,
            "data": digest.data_for_model(METRICS, PREV, GAPS, LEADS, PERIOD, DEFAULTS), "html": None}


def _needed(data: dict) -> list[str]:
    m = data["metrics"]
    return ([str(m["conversations"]), str(m["questions"]), m["resolution_rate"], m["satisfaction"], str(m["bookings"]), data["period"], data["console_url"]]
            + [q["question"] for q in data["most_asked"]] + [q["question"] for q in data["unanswered"]]
            + [lead["email"] or lead["name"] for lead in data["leads"]])


def _html(data: dict, drop: str | None = None) -> str:
    return "<!DOCTYPE html><html><body>" + "".join(f"<p>{escape(s)}</p>" for s in _needed(data) if s != drop) + "</body></html>"


class FakeClient:
    """Minimal OpenAI-compatible client: returns `content` or raises `exc`; records the request."""

    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content, self._exc = content, exc

    def _create(self, **kw):
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class FakeRun:
    """Stands in for subprocess.run: records the call, returns `stdout` or raises `exc`."""

    def __init__(self, stdout: str = "", exc: Exception | None = None):
        self.calls: list[dict] = []
        self.stdout, self.exc = stdout, exc

    def __call__(self, cmd, **kw):
        self.calls.append({"cmd": cmd, **kw})
        if self.exc:
            raise self.exc
        return SimpleNamespace(stdout=self.stdout, stderr="", returncode=0)


def _ok_stdout(html: str, **over) -> str:
    r = {"ok": True, "html": html, "root": "EmailTemplate", "statements": 3, "errors": [], "unresolved": [], "orphaned": [],
         "links": ["https://deependhq.com/admin"], "html_chars": len(html), "ms": 12}
    r.update(over)
    return "node noise line\n" + json.dumps(r) + "\n"


@pytest.fixture
def rich_on(monkeypatch):
    from app.security import limits

    monkeypatch.setattr(settings, "digest_rich_email", True)
    monkeypatch.setattr(digest_rich, "available", lambda: True)
    monkeypatch.setattr(limits, "record_spend", lambda *a, **k: 0.0)


# ---------------------------------------------------------------- 1. data_for_model
def test_data_for_model_has_the_frozen_keys():
    data = digest.data_for_model(METRICS, PREV, GAPS, LEADS, PERIOD, DEFAULTS)
    assert list(data) == ["subject", "period", "brand", "host", "site", "console_url", "footer", "metrics", "most_asked", "unanswered",
                          "thumbs_down", "leads", "results"]
    assert data["results"] == []   # calls and the knowledge-gap loop; empty when the week has nothing to report
    assert list(data["metrics"]) == ["conversations", "conversations_delta", "questions", "questions_delta", "resolution_rate", "resolution_delta",
                                     "satisfaction", "csat_up", "csat_down", "bookings", "handovers", "enquiries", "median_answer", "errors"]
    assert data["subject"] == "[Champions Group] Weekly digest: 42 conversations, 5 bookings · 29 Sep – 06 Oct 2026"
    assert data["period"] == PERIOD and data["brand"] == "Champions Group" and data["host"] == "Deep" and data["site"] == "deependhq.com"
    assert data["console_url"] == "https://deependhq.com/admin" and data["footer"] == "Sent by the deependhq.com assistant to Deep."
    m = data["metrics"]
    assert m["conversations"] == 42 and m["conversations_delta"] == "(up 12 vs the week before)" and m["questions_delta"] == "(up 17 vs the week before)"
    assert m["resolution_rate"] == "81%" and m["resolution_delta"] == "(up 6 pts vs the week before)" and m["satisfaction"] == "92%"
    assert (m["csat_up"], m["csat_down"], m["bookings"], m["handovers"], m["enquiries"], m["median_answer"], m["errors"]) == (23, 2, 5, 2, 1, "2.1 s", 1)
    assert data["most_asked"] == [{"question": "what does lake b2b do?", "count": 9}, {"question": "who is deep?", "count": 6}]
    assert data["unanswered"] == [{"question": "what is the pricing?", "count": 3}] and data["thumbs_down"] == 1
    assert list(data["leads"][0]) == ["when", "name", "email", "company", "call_type", "wanted", "state", "reason"]
    ada, bob = data["leads"]
    assert ada["email"] == "ada@lovelace.org" and ada["call_type"] == "discovery call" and ada["wanted"] and ada["reason"] == "EU fintech data"
    assert ada["state"] == "sent to Zoom, not confirmed, reminded" and ada["company"].startswith("Lovelace Analytical Engines")
    assert bob == {"when": bob["when"], "name": "Bob", "email": "bob@gmail.com", "company": "", "call_type": "", "wanted": "",
                   "state": "asked for a human reply", "reason": ""}
    json.dumps(data)  # serialisable as sent


def test_data_for_model_caps_like_the_text():
    m = dict(METRICS, top_questions=[{"question": f"q{i}", "count": 1} for i in range(20)])
    g = {"unanswered": [{"question": f"u{i}", "count": 1} for i in range(20)], "thumbs_down": []}
    data = digest.data_for_model(m, None, g, [dict(LEADS[0], reason="x" * 500)] * 40, PERIOD, DEFAULTS)
    assert len(data["most_asked"]) == digest.MAX_TOP and len(data["unanswered"]) == digest.MAX_GAPS
    assert len(data["leads"]) == 40 and len(data["leads"][0]["reason"]) == 140   # leads_recent() already caps rows at MAX_LEADS


# ---------------------------------------------------------------- 2. compose happy path
def test_compose_happy_path_returns_the_html_and_calls_node_with_the_frozen_contract(rich_on, monkeypatch):
    d = _d()
    html = _html(d["data"])
    run = FakeRun(_ok_stdout(html))
    monkeypatch.setattr(digest_rich.subprocess, "run", run)
    client = FakeClient("Here you go:\n```openui-lang\n" + PROGRAM + "\n```\n")
    assert digest_rich.compose(d, client) == html
    st = digest_rich.last_stats()
    assert st["fallback_reason"] is None and st["html_chars"] == len(html) and st["program_chars"] == len(PROGRAM)
    assert st["model_ms"] is not None and st["render_ms"] is not None
    # the model call: committed prompt as system message, DATA as the user message, spend recorded
    req = client.calls[0]
    assert req["model"] == settings.chat_model and req["messages"][0]["content"] == digest_rich.prompt_text()
    assert req["messages"][1]["content"].startswith(digest_rich.USER_TEMPLATE) and '"ada@lovelace.org"' in req["messages"][1]["content"]
    # the Node call: env, cwd, timeout, payload
    call = run.calls[0]
    assert call["cmd"][1] == str(digest_rich.RENDERER) and call["cwd"] == str(digest_rich.TOOLS) and call["timeout"] == settings.digest_render_timeout
    env = call["env"]
    assert env["OPENUI_TELEMETRY_DISABLED"] == "1" and env["NODE_ENV"] == "production" and env["DO_NOT_TRACK"] == "1"
    assert env.get("PATH") == os.environ.get("PATH")
    for k in ("SYSTEMROOT", "TEMP", "APPDATA", "HOME"):          # what Node needs to start, when the host has it
        assert env.get(k) == os.environ.get(k)
    for k in ("CHAT_API_KEY", "ADMIN_TOKEN", "SMTP_PASSWORD", "ZOOM_CLIENT_SECRET", "DATABASE_URL", "NODE_OPTIONS"):
        assert k not in env                                        # the app's secrets never reach the child (test_node_env_is_minimal sets them)
    payload = json.loads(call["input"])
    assert payload["task"] == "render" and payload["program"] == PROGRAM and "```" not in payload["program"]
    assert payload["subject"] == d["subject"] and payload["preview_text"] == PERIOD and payload["lang"] == "en"
    assert {"deependhq.com", "www.deependhq.com", "scheduler.zoom.us"} <= set(payload["allowed_hosts"]) and payload["max_chars"] == 150000


# ---------------------------------------------------------------- 3. every fallback reason
class FakeTimeoutError(Exception):
    pass


_RUN_OK = "ok"
CASES = [
    ("disabled", dict(enabled=False)),
    ("unavailable", dict(available=False)),
    ("model_error", dict(client=lambda: FakeClient(exc=RuntimeError("boom")))),
    ("model_timeout", dict(client=lambda: FakeClient(exc=FakeTimeoutError("Request timed out")))),
    ("empty", dict(client=lambda: FakeClient(""))),
    ("bad_program", dict(client=lambda: FakeClient("hello = EmailHeading(\"x\")"))),
    ("forbidden_component", dict(client=lambda: FakeClient(PROGRAM + '\ni = EmailImage("https://deependhq.com/x.png", "a")'))),
    ("forbidden_component", dict(client=lambda: FakeClient(PROGRAM + '\nm = EmailMarkdown("<img src=x>")'))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace("https://deependhq.com/admin", "https://evil.example/x")))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace("https://deependhq.com/admin", "//evil.example/x")))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace("https://deependhq.com/admin", "http://deependhq.com/admin")))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace("https://deependhq.com/admin", "https://deependhq.com@evil.example/")))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM + '\nt = EmailText("mailto:x@y.z")'))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace('"#F28C28"', '"#fff;background-image:url(https:evil.com/p.gif)"')))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace('"#F28C28"', '"red"')))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace("https://deependhq.com/admin", "https:evil.com/admin")))),
    ("unsafe_link", dict(client=lambda: FakeClient(PROGRAM.replace("https://deependhq.com/admin", "https:\\\\evil.com/admin")))),
    ("forbidden_component", dict(client=lambda: FakeClient(PROGRAM + '\ni = EmailImage ("https://deependhq.com/x.png", "a")'))),
    ("too_long", dict(client=lambda: FakeClient(PROGRAM + "\n" + 'x = EmailText("' + "a" * 20000 + '")'))),
    ("unsafe", dict(run=lambda html: FakeRun(json.dumps({"ok": False, "status": "unsafe", "message": "link not allowed"})))),
    ("bad_program", dict(run=lambda html: FakeRun(json.dumps({"ok": False, "status": "bad_program", "message": "root is null"})))),
    ("too_large", dict(run=lambda html: FakeRun(json.dumps({"ok": False, "status": "too_large", "message": "200000"})))),
    ("render_errors", dict(run=lambda html: FakeRun(_ok_stdout(html, errors=[{"code": "unknown-component", "statementId": "s1"}])))),
    ("render_errors", dict(run=lambda html: FakeRun(_ok_stdout(html, errors=[{"code": "missing-required", "statementId": "x16", "path": "/description"}])))),
    ("render_errors", dict(run=lambda html: FakeRun(_ok_stdout(html, root="EmailHeading")))),
    ("timeout", dict(run=lambda html: FakeRun(exc=subprocess.TimeoutExpired("node", 60)))),
    ("render_error", dict(run=lambda html: FakeRun("no json here\n"))),
    ("render_error", dict(run=lambda html: FakeRun(exc=FileNotFoundError("node")))),
    ("sanity_failed", dict(html=lambda data: _html(data, drop="42"))),
    ("sanity_failed", dict(html=lambda data: _html(data, drop="bob@gmail.com"))),
    ("sanity_failed", dict(html=lambda data: _html(data, drop="what is the pricing?"))),
    ("sanity_failed", dict(html=lambda data: _html(data, drop="https://deependhq.com/admin"))),
    ("sanity_failed", dict(html=lambda data: _html(data, drop="81%"), run=lambda html: FakeRun(_ok_stdout(html, unresolved=["s2"])))),   # a dropped stat tile
    ("sanity_failed", dict(html=lambda data: _html(data, drop="92%"))),
    ("sanity_failed", dict(html=lambda data: _html(data, drop="97"))),
    ("sanity_failed", dict(html=lambda data: _html(data) + "x" * 150_001)),
]


@pytest.mark.parametrize("reason,case", CASES, ids=[f"{i}-{r}" for i, (r, _) in enumerate(CASES)])
def test_compose_falls_back_with_the_reason(rich_on, monkeypatch, reason, case):
    d = _d()
    monkeypatch.setattr(settings, "digest_rich_email", case.get("enabled", True))
    monkeypatch.setattr(digest_rich, "available", lambda: case.get("available", True))
    html = case["html"](d["data"]) if "html" in case else _html(d["data"])
    run = case["run"](html) if "run" in case else FakeRun(_ok_stdout(html))
    monkeypatch.setattr(digest_rich.subprocess, "run", run)
    client = case["client"]() if "client" in case else FakeClient(PROGRAM)
    assert digest_rich.compose(d, client) is None
    assert digest_rich.last_stats()["fallback_reason"] == reason


def test_a_visitor_question_that_looks_like_a_url_scheme_is_not_a_link(rich_on, monkeypatch):
    d = _d()
    d["data"]["most_asked"][0]["question"] = "do you sell intent data: yes or no? metadata: too"
    html = _html(d["data"])
    monkeypatch.setattr(digest_rich.subprocess, "run", FakeRun(_ok_stdout(html)))
    program = PROGRAM + '\nq = EmailText("do you sell intent data: yes or no? metadata: too")'
    assert digest_rich.check_program(program) is None
    assert digest_rich.compose(d, FakeClient(program)) == html
    assert digest_rich.check_program(PROGRAM + '\nq = EmailText("data:text/html,x")') == "unsafe_link"


def test_node_env_is_minimal(monkeypatch):
    monkeypatch.setenv("CHAT_API_KEY", "sk-secret")
    monkeypatch.setenv("ADMIN_TOKEN", "t0ken")
    monkeypatch.setenv("NODE_OPTIONS", "--require evil.js")
    env = digest_rich.node_env()
    assert "CHAT_API_KEY" not in env and "ADMIN_TOKEN" not in env and "NODE_OPTIONS" not in env
    assert env["PATH"] == os.environ["PATH"] and env["NODE_ENV"] == "production" and env["OPENUI_TELEMETRY_DISABLED"] == "1"
    assert set(env) <= set(digest_rich.ENV_KEYS) | set(digest_rich.ENV_EXTRA)


def test_unresolved_references_are_tolerated_when_the_content_survives(rich_on, monkeypatch):
    """The parser drops a dangling reference (the model counted leads wrongly); sane_html is the guard, not the ref list:
    it requires every headline number (incl. the resolution rate and satisfaction tiles), question and lead."""
    d = _d()
    html = _html(d["data"])
    monkeypatch.setattr(digest_rich.subprocess, "run", FakeRun(_ok_stdout(html, unresolved=["x26", "x27"])))
    assert digest_rich.compose(d, FakeClient(PROGRAM)) == html
    st = digest_rich.last_stats()
    assert st["fallback_reason"] is None and st["unresolved"] == 2
    monkeypatch.setattr(digest_rich.subprocess, "run", FakeRun(_ok_stdout(_html(d["data"], drop="bob@gmail.com"), unresolved=["x2"])))
    assert digest_rich.compose(d, FakeClient(PROGRAM)) is None and digest_rich.last_stats()["fallback_reason"] == "sanity_failed"


def test_compose_never_raises(rich_on, monkeypatch):
    monkeypatch.setattr(digest_rich, "check_program", lambda p: 1 / 0)
    assert digest_rich.compose(_d(), FakeClient(PROGRAM)) is None
    assert digest_rich.last_stats()["fallback_reason"] == "error"


# ---------------------------------------------------------------- 4. send(): html alternative vs. plain text
def test_send_uses_the_html_alternative_or_the_plain_call(monkeypatch):
    import app.booking.email as email
    from app import db

    d = _d()
    sent: list[tuple] = []
    monkeypatch.setattr(digest, "build", lambda days=7, rich=False: dict(d))
    monkeypatch.setattr(email, "_send", lambda to, s, b, **kw: sent.append(("_send", to, s, b, kw)) or True)
    monkeypatch.setattr(email, "send_plain", lambda to, s, b: sent.append(("send_plain", to, s, b)) or True)
    events: list[dict] = []
    monkeypatch.setattr(db, "log_event", lambda kind, sid, data: events.append(data))
    monkeypatch.setattr(db, "set_setting", lambda k, v: None)

    monkeypatch.setattr(digest_rich, "compose", lambda dd, client=None: "<html>")
    r = digest.send(7, to="owner@example.com")
    assert r["ok"] and sent[-1] == ("_send", "owner@example.com", d["subject"], d["body"], {"html": "<html>"})
    assert events[-1]["rich"] is True and "fallback_reason" in events[-1]

    monkeypatch.setattr(digest_rich, "compose", lambda dd, client=None: None)
    r = digest.send(7, to="owner@example.com")
    assert r["ok"] and sent[-1] == ("send_plain", "owner@example.com", d["subject"], d["body"])
    assert events[-1]["rich"] is False


def test_build_rich_adds_html_and_stats(monkeypatch):
    monkeypatch.setattr(digest.inbox, "metrics", lambda days: dict(METRICS))
    monkeypatch.setattr(digest.inbox, "gaps", lambda days, n: GAPS)
    monkeypatch.setattr(digest, "leads_recent", lambda days: LEADS)
    monkeypatch.setattr(digest.templates, "get_templates", lambda: dict(DEFAULTS))
    d = digest.build(7)
    assert d["html"] is None and "rich" not in d and d["data"]["metrics"]["conversations"] == 42
    d = digest.build(7, rich=True)   # autouse fixture: disabled -> fallback_reason "disabled"
    assert d["html"] is None and d["rich"]["fallback_reason"] == "disabled"


# ---------------------------------------------------------------- 5-8. the small parts
def test_render_html_parses_the_last_json_line_and_handles_garbage(monkeypatch):
    run = FakeRun("warning: something\n{\"ok\": false, \"status\": \"old\"}\ntrailing\n{\"ok\": true, \"html\": \"<p>x</p>\", \"root\": \"EmailTemplate\"}\n")
    monkeypatch.setattr(digest_rich.subprocess, "run", run)
    r = digest_rich.render_html(PROGRAM, "s", PERIOD)
    assert r["ok"] and r["html"] == "<p>x</p>"
    monkeypatch.setattr(digest_rich.subprocess, "run", FakeRun("not json at all\n"))
    r = digest_rich.render_html(PROGRAM, "s", PERIOD)
    assert r["ok"] is False and r["status"] == "render_error"
    monkeypatch.setattr(digest_rich.subprocess, "run", FakeRun(exc=subprocess.TimeoutExpired("node", 1)))
    assert digest_rich.render_html(PROGRAM, "s", PERIOD)["status"] == "timeout"


def test_render_html_without_node_is_render_error_not_an_exception(monkeypatch):
    monkeypatch.setattr(settings, "digest_node", r"C:\definitely\missing\node.exe")
    r = digest_rich.render_html(PROGRAM, "s", PERIOD)
    assert r["ok"] is False and r["status"] == "render_error"


def test_available_needs_node_and_the_npm_install(monkeypatch):
    monkeypatch.undo()   # the autouse fixture replaced available(); this test wants the real one
    monkeypatch.setattr(settings, "digest_node", "")
    monkeypatch.setattr(digest_rich.shutil, "which", lambda name: None)
    assert digest_rich.available() is False
    monkeypatch.setattr(digest_rich.shutil, "which", lambda name: "node")
    installed = (digest_rich.TOOLS / "node_modules" / "@openuidev" / "react-email" / "package.json").exists()
    assert digest_rich.available() is installed


def test_strip_fences():
    assert digest_rich.strip_fences("```openui-lang\n" + PROGRAM + "\n```") == PROGRAM
    assert digest_rich.strip_fences(PROGRAM + "\n") == PROGRAM
    assert digest_rich.strip_fences("Sure, here it is:\n\n```openui-lang\r\n" + PROGRAM.replace("\n", "\r\n") + "\r\n```\n\nLet me know!") == PROGRAM
    assert digest_rich.strip_fences("```\n" + PROGRAM) == PROGRAM   # unclosed fence at stream end
    assert digest_rich.strip_fences("") == ""


def test_check_program_contract():
    assert digest_rich.check_program(PROGRAM) is None
    assert digest_rich.check_program(PROGRAM.replace("https://deependhq.com/admin", "https://scheduler.zoom.us/sreedeep")) is None
    assert digest_rich.check_program(PROGRAM.replace("https://deependhq.com/admin", "https://www.deependhq.com/admin?x=1")) is None
    assert digest_rich.check_program("x = EmailText(\"hi\")") == "bad_program"
    assert digest_rich.check_program(PROGRAM + '\nl = EmailLink("x", "https://deependhq.com/x")') == "forbidden_component"
    assert digest_rich.check_program(PROGRAM + '\nt = EmailText("javascript:alert(1)")') == "unsafe_link"
    assert digest_rich.check_program(PROGRAM + '\nt = EmailText("data:text/html,x")') == "unsafe_link"
    assert digest_rich.check_program(PROGRAM + '\nt = EmailText("the ratio is 3:1 and https: is a scheme")') is None
    assert digest_rich.check_program(PROGRAM.replace('"#F28C28"', '"#f28c28"')) is None
    assert digest_rich.check_program(PROGRAM.replace('"#F28C28"', '"#F28C28; background:url(https://deependhq.com/x.png)"')) == "unsafe_link"
    assert digest_rich.check_program(PROGRAM + '\nt = EmailText("Use EmailLink here")') == "forbidden_component"   # word match: broad on purpose
    assert digest_rich.check_program(PROGRAM.replace("https://deependhq.com/admin", "https://deependhq.com:8443/admin")) == "unsafe_link"
    assert digest_rich.check_program(PROGRAM.replace("https://deependhq.com/admin", "HTTPS://DEEPENDHQ.COM/admin")) is None
    assert digest_rich.check_program("a" * 20001) == "too_long"


def test_sane_html_unescapes_entities_and_ignores_tags():
    d = _d()
    html = _html(d["data"]).replace("what does lake b2b do?", "what&#x27;s lake b2b?").replace("who is deep?", "&quot;who is deep?&quot;")
    d["data"]["most_asked"][0]["question"] = "what's lake b2b?"
    assert digest_rich.sane_html(html, d)
    assert digest_rich.sane_html(html.replace("<p>", "<p style=\"x\">\n  "), d)   # whitespace and tags collapse
    assert not digest_rich.sane_html("", d)
    assert not digest_rich.sane_html(html.replace("ada@lovelace.org", "ada@other.org"), d)
    # the addresses in the mail are exactly those in DATA: a duplicated or an invented lead fails too
    assert not digest_rich.sane_html(html.replace("</body>", "<p>bob@gmail.com</p></body>"), d)
    assert not digest_rich.sane_html(html.replace("</body>", "<p>Mon 13 Oct · Eve &lt;eve@evil.example&gt;</p></body>"), d)


def test_allowed_hosts_include_the_site_host(monkeypatch):
    monkeypatch.setattr(settings, "site_base_url", "https://assistant.example.org")
    assert "assistant.example.org" in digest_rich.allowed_hosts() and "deependhq.com" in digest_rich.allowed_hosts()
