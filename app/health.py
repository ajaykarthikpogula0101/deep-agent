"""Health checks and alerts: someone hears about a dead model key before a visitor does.

On 2026-10-16 the OpenRouter key stopped working; every answer failed with "I'm having trouble answering right now" and
nobody was told. Now, every HEALTH_CRON (10 min) the app checks:

  model        the chat key is accepted (OpenRouter: GET /key; other providers: list models)
  credit       what the key has left (OpenRouter limit_remaining) against CREDIT_ALERT_USD
  backup       the CHAT_FALLBACK_MODEL key, when one is set
  answers      model failures in the chat in the last 15 minutes (events kind 'error', where 'llm')
  database     SELECT 1
  email        emails that gave up after their retries in the last 6 hours (events 'mail_failed')
  booking      the booking robot falling back to the hand-off link in the last 24 hours (events 'booking_pending'
               with a 'browser booking' error), when browser booking is on
  backup       the newest nightly database backup (app/backup.py) is less than 36 hours old

Each check is ok, warn or fail. An alert email goes to ALERT_EMAIL (default HOST_EMAIL) when a check turns warn or fail,
again every 6 hours while it stays that way, and once when it recovers. The state lives in settings key 'health:state'.
GET /admin/health shows the latest report (run=true runs the checks now); /healthz carries the overall status only.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from app.config import settings

log = logging.getLogger("health")

REALERT_HOURS = 6
LEVELS = {"ok": 0, "warn": 1, "fail": 2}
_last: dict[str, Any] = {}


def _check(level: str, detail: str, **extra) -> dict[str, Any]:
    return {"level": level, "detail": detail, **extra}


def _key_check(api_key: str, base_url: str, label: str, get: Callable = httpx.get) -> dict[str, Any]:
    """The key is accepted; on OpenRouter also how much credit it has left."""
    if not api_key:
        return _check("fail", f"no API key set for the {label}")
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    openrouter = "openrouter.ai" in base
    try:
        r = get(f"{base}/key" if openrouter else f"{base}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
    except Exception as e:
        return _check("fail", f"{label}: provider unreachable ({type(e).__name__})")
    if r.status_code in (401, 403):
        return _check("fail", f"{label}: the API key is rejected ({r.status_code}); create a new key and put it in .env")
    if r.status_code >= 400:
        return _check("warn", f"{label}: provider answered {r.status_code}")
    if not openrouter:
        return _check("ok", f"{label}: key accepted")
    data = (r.json() or {}).get("data") or {}
    remaining = data.get("limit_remaining")
    return _check("ok", f"{label}: key accepted", credit_usd=None if remaining is None else round(float(remaining), 2),
                  limit_usd=data.get("limit"))


def _count(sql: str, params: tuple) -> int:
    from app.db import conn

    with conn() as c:
        return int(c.execute(sql, params).fetchone()[0])


def run_checks(get: Callable = httpx.get, count: Callable[[str, tuple], int] = _count) -> dict[str, Any]:
    """Every check, never raising. {"level": worst, "checks": {name: {"level", "detail", ...}}, "at": iso}."""
    checks: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)

    model = _key_check(settings.chat_api_key, settings.llm_base_url, f"chat model ({settings.chat_model})", get)
    checks["model"] = model
    credit = model.get("credit_usd")
    if credit is None:
        checks["credit"] = _check("ok", "no spending limit reported" if model["level"] == "ok" else "unknown (key check failed)")
    elif credit < settings.credit_alert_usd:
        checks["credit"] = _check("warn" if credit > 0 else "fail",
                                  f"${credit:.2f} left on the model key (alert below ${settings.credit_alert_usd:.2f}); "
                                  "top up or raise the key's limit on openrouter.ai", credit_usd=credit)
    else:
        checks["credit"] = _check("ok", f"${credit:.2f} left on the model key", credit_usd=credit)
    if settings.chat_fallback_model:
        checks["backup"] = _key_check(settings.chat_fallback_api_key or settings.chat_api_key,
                                      settings.chat_fallback_base_url or settings.llm_base_url,
                                      f"backup model ({settings.chat_fallback_model})", get)

    def counted(name: str, sql: str, params: tuple, ok: str, bad: Callable[[int], dict[str, Any]]) -> None:
        try:
            n = count(sql, params)
            checks[name] = _check("ok", ok, count=0) if n == 0 else {**bad(n), "count": n}
        except Exception as e:
            checks[name] = _check("fail", f"could not read the event log ({type(e).__name__})")

    counted("answers", "SELECT count(*) FROM events WHERE kind = 'error' AND detail->>'where' = 'llm' AND ts > %s",
            (now - timedelta(minutes=15),), "no failed answers in the last 15 minutes",
            lambda n: _check("fail" if n >= 3 else "warn", f"{n} answer(s) failed at the model in the last 15 minutes"))
    try:
        count("SELECT 1", ())
        checks["database"] = _check("ok", "reachable")
    except Exception as e:
        checks["database"] = _check("fail", f"unreachable ({type(e).__name__})")
    counted("email", "SELECT count(*) FROM events WHERE kind = 'mail_failed' AND ts > %s", (now - timedelta(hours=6),),
            "no email gave up in the last 6 hours",
            lambda n: _check("fail", f"{n} email(s) gave up after 3 attempts in the last 6 hours; check SMTP_USER / SMTP_PASSWORD"))
    if settings.browser_booking_enabled:
        counted("booking", "SELECT count(*) FROM events WHERE kind = 'booking_pending' AND detail->>'zoom_error' LIKE %s "
                           "AND ts > %s", ("browser booking%", now - timedelta(hours=24)),
                "the booking robot completed every booking in the last 24 hours",
                lambda n: _check("warn", f"the booking robot fell back to the Zoom hand-off link {n} time(s) in the last "
                                         "24 hours; see Console → Bookings (zoom_run) and uploads/zoom-runs/"))

    if settings.backup_enabled:
        try:
            from app import backup

            hours = backup.age_hours()
            where = str(backup.backup_dir())
            if hours is None:
                checks["backup"] = _check("warn", f"no database backup yet in {where}")
            elif hours > 36:
                checks["backup"] = _check("fail", f"the newest database backup is {hours:.0f} hours old ({where}); the nightly "
                                                  "backup is failing, see the server log", hours=round(hours, 1))
            else:
                checks["backup"] = _check("ok", f"newest database backup {hours:.0f} h old in {where}", hours=round(hours, 1))
        except Exception as e:
            checks["backup"] = _check("warn", f"could not read the backup folder ({type(e).__name__})")

    worst = max((c["level"] for c in checks.values()), key=LEVELS.__getitem__, default="ok")
    report = {"level": worst, "checks": checks, "at": now.isoformat(timespec="seconds")}
    _last.clear()
    _last.update(report)
    return report


def last() -> dict[str, Any]:
    return dict(_last)


def _load_state() -> dict[str, Any]:
    from app.db import get_setting

    try:
        return json.loads(get_setting("health:state") or "{}")
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    from app.db import set_setting

    set_setting("health:state", json.dumps(state))


def alerts(report: dict[str, Any], state: dict[str, Any], now: float) -> tuple[list[tuple[str, dict]], list[str], dict]:
    """(problems to alert on now, checks that recovered, the new state). Pure, unit-tested."""
    new_state, problems, recovered = {}, [], []
    for name, c in report["checks"].items():
        prev = state.get(name) or {}
        if c["level"] == "ok":
            if prev.get("level") in ("warn", "fail") and prev.get("alerted_at"):
                recovered.append(name)
            new_state[name] = {"level": "ok"}
            continue
        alerted = prev.get("alerted_at") or 0
        worse = LEVELS[c["level"]] > LEVELS.get(prev.get("level", "ok"), 0)
        if worse or now - alerted >= REALERT_HOURS * 3600:
            problems.append((name, c))
            alerted = now
        new_state[name] = {"level": c["level"], "alerted_at": alerted}
    return problems, recovered, new_state


def alert_email(problems: list[tuple[str, dict]], recovered: list[str]) -> tuple[str, str]:
    if problems:
        worst = "fail" if any(c["level"] == "fail" for _, c in problems) else "warn"
        subject = ("Action needed: " if worst == "fail" else "Heads-up: ") + ", ".join(n for n, _ in problems) + " (ask deep)"
    else:
        subject = "Resolved: " + ", ".join(recovered) + " (ask deep)"
    lines = ["The ask deep assistant checked itself.", ""]
    for name, c in problems:
        lines.append(f"{'PROBLEM' if c['level'] == 'fail' else 'WARNING'}  {name}: {c['detail']}")
    for name in recovered:
        lines.append(f"OK again  {name}")
    lines += ["", f"Full report: {settings.public_base_url.rstrip('/')}/admin/health" if getattr(settings, "public_base_url", "") else "",
              "You get this email when something breaks, every 6 hours while it stays broken, and once when it recovers."]
    return subject, "\n".join(x for x in lines if x is not None)


def run(send: Callable[..., Any] | None = None, checks: Callable[[], dict[str, Any]] = run_checks) -> dict[str, Any]:
    """The scheduled job: check, alert on changes, remember. Never raises."""
    try:
        report = checks()
        problems, recovered, state = alerts(report, _load_state(), time.time())
        to = settings.alert_email or settings.host_email
        if (problems or recovered) and to:
            subject, body = alert_email(problems, recovered)
            if send is None:
                from app import mailer

                send = mailer.default.enqueue
            send(to, subject, body, kind="health_alert")
            log.warning("health alert sent to %s: %s", to, subject)
        _save_state(state)
        return {**report, "alerted": [n for n, _ in problems], "recovered": recovered}
    except Exception as e:
        log.error("health run failed: %s", e)
        return {"level": "fail", "checks": {}, "error": str(e)[:200]}
