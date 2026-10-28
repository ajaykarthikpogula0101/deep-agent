"""Health checks, alert emails, the chat timeout and the backup model (app/health.py, app/chat.py). No network, no DB."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from app import health
from app.chat import respond
from app.config import settings


class Resp:
    def __init__(self, status: int, data: dict | None = None):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def _get(status=200, data=None, raise_exc=None):
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append((url, headers))
        if raise_exc:
            raise raise_exc
        return Resp(status, data)
    get.calls = calls
    return get


def _count(n_llm=0, n_mail=0, n_booking=0, db_down=False):
    def count(sql, params):
        if db_down:
            raise RuntimeError("connection refused")
        if "where' = 'llm'" in sql:
            return n_llm
        if "mail_failed" in sql:
            return n_mail
        if "booking_pending" in sql:
            return n_booking
        return 1
    return count


def test_dead_key_is_a_failure_with_what_to_do(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "sk-or-v1-dead")
    monkeypatch.setattr(settings, "llm_base_url", "https://openrouter.ai/api/v1")
    get = _get(401, {"error": {"message": "User not found."}})
    r = health.run_checks(get=get, count=_count())
    assert get.calls[0][0] == "https://openrouter.ai/api/v1/key" and get.calls[0][1]["Authorization"] == "Bearer sk-or-v1-dead"
    assert r["level"] == "fail" and r["checks"]["model"]["level"] == "fail"
    assert "rejected (401)" in r["checks"]["model"]["detail"] and "new key" in r["checks"]["model"]["detail"]
    assert health.last()["level"] == "fail"


def test_low_credit_warns_and_empty_credit_fails(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "credit_alert_usd", 2.0)
    ok = health.run_checks(get=_get(200, {"data": {"limit": 10, "limit_remaining": 9.37}}), count=_count())
    assert ok["level"] == "ok" and ok["checks"]["credit"]["detail"] == "$9.37 left on the model key"
    low = health.run_checks(get=_get(200, {"data": {"limit": 10, "limit_remaining": 1.2}}), count=_count())
    assert low["level"] == "warn" and "$1.20 left" in low["checks"]["credit"]["detail"]
    empty = health.run_checks(get=_get(200, {"data": {"limit": 10, "limit_remaining": 0}}), count=_count())
    assert empty["checks"]["credit"]["level"] == "fail"
    unlimited = health.run_checks(get=_get(200, {"data": {"limit": None, "limit_remaining": None}}), count=_count())
    assert unlimited["checks"]["credit"]["level"] == "ok"


def test_event_based_checks_and_a_database_outage(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "browser_booking_enabled", True)
    r = health.run_checks(get=_get(200, {"data": []}), count=_count(n_llm=3, n_mail=1, n_booking=2))
    assert r["checks"]["model"]["detail"].endswith("key accepted")          # non-OpenRouter: GET /models
    assert r["checks"]["answers"]["level"] == "fail" and r["checks"]["answers"]["count"] == 3
    assert r["checks"]["email"]["level"] == "fail" and r["checks"]["booking"]["level"] == "warn"
    assert health.run_checks(get=_get(200, {}), count=_count(n_llm=1))["checks"]["answers"]["level"] == "warn"
    down = health.run_checks(get=_get(raise_exc=TimeoutError()), count=_count(db_down=True))
    assert down["checks"]["database"]["level"] == "fail" and down["checks"]["model"]["level"] == "fail"
    assert "unreachable" in down["checks"]["model"]["detail"]
    monkeypatch.setattr(settings, "browser_booking_enabled", False)
    assert "booking" not in health.run_checks(get=_get(200, {}), count=_count())["checks"]


def test_backup_key_is_checked_when_a_backup_model_is_set(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "main")
    monkeypatch.setattr(settings, "llm_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "chat_fallback_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "chat_fallback_api_key", "gsk_x")
    monkeypatch.setattr(settings, "chat_fallback_base_url", "https://api.groq.com/openai/v1")
    get = _get(200, {"data": {}})
    r = health.run_checks(get=get, count=_count())
    assert r["checks"]["backup"]["level"] == "ok" and get.calls[1] == ("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer gsk_x"})


def _report(**levels):
    return {"level": "x", "checks": {k: {"level": v, "detail": f"{k} is {v}"} for k, v in levels.items()}}


def test_alerts_on_change_then_every_6_hours_then_on_recovery():
    p, rec, st = health.alerts(_report(model="fail", email="ok"), {}, now=1000)
    assert [n for n, _ in p] == ["model"] and rec == [] and st["model"] == {"level": "fail", "alerted_at": 1000}
    p, rec, st = health.alerts(_report(model="fail", email="ok"), st, now=1000 + 600)          # 10 min later: quiet
    assert p == [] and st["model"]["alerted_at"] == 1000
    p, rec, st = health.alerts(_report(model="fail", email="ok"), st, now=1000 + 6 * 3600)     # still broken 6 h later
    assert [n for n, _ in p] == ["model"]
    p, rec, st = health.alerts(_report(model="ok", email="ok"), st, now=1000 + 7 * 3600)
    assert p == [] and rec == ["model"] and st["model"] == {"level": "ok"}
    p, _, st = health.alerts(_report(credit="warn"), {}, now=0)
    p2, _, _ = health.alerts(_report(credit="fail"), st, now=60)                                 # worse: alert at once
    assert [n for n, _ in p2] == ["credit"]


def test_alert_email_names_the_problem(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://ask.example.com")
    subject, body = health.alert_email([("model", {"level": "fail", "detail": "the API key is rejected (401)"})], [])
    assert subject == "Action needed: model (ask deep)"
    assert "PROBLEM  model: the API key is rejected (401)" in body and "https://ask.example.com/admin/health" in body
    subject, body = health.alert_email([], ["model"])
    assert subject == "Resolved: model (ask deep)" and "OK again  model" in body


def test_run_sends_one_email_and_saves_state(monkeypatch):
    monkeypatch.setattr(settings, "alert_email", "alerts@example.com")
    saved, sent = {}, []
    monkeypatch.setattr(health, "_load_state", lambda: {})
    monkeypatch.setattr(health, "_save_state", lambda s: saved.update(s))
    out = health.run(send=lambda *a, **k: sent.append((a, k)), checks=lambda: _report(model="fail", database="ok"))
    assert out["alerted"] == ["model"] and saved["model"]["level"] == "fail"
    assert sent[0][0][0] == "alerts@example.com" and sent[0][0][1].startswith("Action needed") and sent[0][1]["kind"] == "health_alert"
    sent.clear()
    monkeypatch.setattr(health, "_load_state", lambda: saved)
    health.run(send=lambda *a, **k: sent.append(a), checks=lambda: _report(model="fail", database="ok"))
    assert sent == []                                                                            # no repeat within 6 hours
    assert health.run(checks=lambda: (_ for _ in ()).throw(RuntimeError("boom")))["level"] == "fail"   # never raises


# ---------------------------------------------------------------- backup model in the chat
def _piece(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))], usage=None)


def _hit():
    from app.rag.retrieve import Hit

    return Hit(url="https://deependhq.com/x", title="x", section=None, text="t", score=0.9, metadata={})


def _chat(fake_stream, **settings_over):
    patches = [patch("app.chat.search", return_value=[_hit()]), patch("app.chat.embed_query", return_value=[0.1]),
               patch("app.chat.match_custom_answer", return_value=None), patch("app.chat.get_guidance", return_value=""),
               patch("app.chat.titles.maybe_generate_async"),
               patch("app.chat.lang.prepare", side_effect=lambda m, h, c: SimpleNamespace(english=None, code=None, name=None, note="")),
               patch("app.chat._create_stream", new=fake_stream), patch("app.chat.log_event"),
               patch("app.chat.inbox.log_message", return_value=5), patch("app.chat._fallback_client", return_value="backup-client")]
    for k, v in settings_over.items():
        patches.append(patch.object(settings, k, v))
    for p in patches:
        p.start()
    try:
        from app.chat import inbox, log_event

        events = [json.loads(c[6:]) for c in respond("What is Lake B2B?", [], "UTC", "s-h", service=SimpleNamespace(session_id=None, list_schedules=lambda: []),
                                                     client="main-client") if c.startswith("data: ")]
        return events, log_event, inbox.log_message
    finally:
        for p in reversed(patches):
            p.stop()


def test_backup_model_answers_when_the_main_one_fails_before_any_text():
    calls = []

    def stream(client, messages, tools, max_tokens=500, model=None):
        calls.append((client, model))
        if client == "main-client":
            raise RuntimeError("Error code: 401 - User not found.")
        return iter([_piece("Lake B2B sells B2B data. [1]")])

    events, log_event, log_message = _chat(stream, chat_model="openai/gpt-4.1-mini", chat_fallback_model="openai/gpt-oss-120b")
    assert calls == [("main-client", "openai/gpt-4.1-mini"), ("backup-client", "openai/gpt-oss-120b")]
    assert "".join(e.get("text", "") for e in events if e["type"] == "token") == "Lake B2B sells B2B data. [1]"
    assert not [e for e in events if e["type"] in ("error", "model")]                  # the switch is invisible to the page
    kinds = [c[0][0] for c in log_event.call_args_list]
    assert "error" in kinds and "model_fallback" in kinds                              # health alerts still see the failure
    assert log_message.call_args_list[-1][1]["model"] == "openai/gpt-oss-120b"         # the inbox records who answered


def test_no_backup_after_text_was_shown_and_no_backup_configured():
    def half(client, messages, tools, max_tokens=500, model=None):
        def gen():
            yield _piece("Lake B2B ")
            raise RuntimeError("connection reset")
        return gen()

    events, _, _ = _chat(half, chat_fallback_model="openai/gpt-oss-120b")
    assert [e["error"] for e in events if e["type"] == "error"] == ["model_unavailable"]   # never a second, doubled answer

    def dead(client, messages, tools, max_tokens=500, model=None):
        raise RuntimeError("401")

    events, _, _ = _chat(dead, chat_fallback_model="")
    assert [e["error"] for e in events if e["type"] == "error"] == ["model_unavailable"]
    assert "trouble answering" in "".join(e.get("text", "") for e in events if e["type"] == "token")


def test_every_model_call_has_the_chat_timeout(monkeypatch):
    from app.chat import _create_stream

    seen = {}

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: seen.update(kw) or iter([])))

    monkeypatch.setattr(settings, "chat_timeout", 30)
    _create_stream(Client(), [], None, model="x/y")
    assert seen["timeout"] == 30 and seen["model"] == "x/y"
