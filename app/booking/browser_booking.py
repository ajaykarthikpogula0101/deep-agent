"""Bookings on Zoom's public scheduler page through a browser worker (no Zoom API credentials needed).

The worker (scripts/zoom_browser_worker.py) runs in its own Python 3.12 environment with jev-ultrafast and a headless
browser, so the app only starts a subprocess and reads one JSON line back. Three tasks:

    book        select the slot, fill the visitor's details, press Book, read the confirmation and its links
    reschedule  open the booking's reschedule link, select the new slot, confirm
    cancel      open the booking's cancel link, confirm

Settings (docs/BROWSER_BOOKING.md): BROWSER_BOOKING_ENABLED, BROWSER_BOOKING_DRIVER (auto|jev|script), TYPESAFE_API_KEY,
TEXT_MODEL_* (the small model that types values for jev; defaults to the chat model key), JEV_PYTHON, JEV_BROWSER_PATH,
JEV_CDP_URL, BROWSER_BOOKING_TIMEOUT, BROWSER_BOOKING_DRY_RUN. `run` is the only side effect and is patched in tests.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings

log = logging.getLogger("booking.browser")

ROOT = Path(__file__).resolve().parent.parent.parent
WORKER = ROOT / "scripts" / "zoom_browser_worker.py"
STATUSES = ("booked", "rescheduled", "cancelled", "dry_run_ok", "slot_unavailable", "link_expired", "verify_failed", "blocked", "error", "timeout")


def driver() -> str:
    d = (settings.browser_booking_driver or "auto").lower()
    if d == "auto":
        return "jev" if settings.typesafe_api_key else "script"
    return d


def python_path() -> str:
    """The jev environment's interpreter: JEV_PYTHON, else the dev-machine default, else this interpreter."""
    for cand in (settings.jev_python, r"D:\jev\venv\Scripts\python.exe", "/opt/jev/venv/bin/python"):
        if cand and os.path.exists(cand):
            return cand
    return sys.executable


def available() -> bool:
    """Enabled, worker present, and (for the jev driver) a TypeSafe key."""
    if not settings.browser_booking_enabled or not WORKER.exists():
        return False
    if driver() == "jev" and not settings.typesafe_api_key:
        return False
    return True


def mode() -> str:
    """What the widget should expect: 'api' (Zoom API), 'browser' (this worker) or 'handoff' (prefilled link)."""
    if settings.zoom_api_configured and (settings.zoom_enable_api_booking or settings.zoom_host_user_id):
        return "api"
    return "browser" if available() else "handoff"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "TYPESAFE_API_KEY": settings.typesafe_api_key or "",
        "TYPESAFE_MODEL": settings.typesafe_model or "jev-latest",
        "TEXT_MODEL_API_KEY": settings.text_model_api_key or settings.chat_api_key or "",
        "TEXT_MODEL_BASE_URL": settings.text_model_base_url or settings.llm_base_url or "https://api.openai.com/v1",
        "TEXT_MODEL": settings.text_model or settings.chat_model,
        "TEXT_MODEL_REASONING": settings.text_model_reasoning or "none",
        "BROWSER_BOOKING_DRIVER": driver(),
        "BH_TELEMETRY": "0", "BH_UPDATE_CHECK": "0", "BU_NAME": "deep-zoom",
        "PYTHONIOENCODING": "utf-8",
    })
    if settings.jev_browser_path:
        env["JEV_BROWSER_PATH"] = settings.jev_browser_path
    if settings.jev_cdp_url:
        env["JEV_CDP_URL"] = settings.jev_cdp_url
    for k in ("TYPESAFE_API_KEY", "JEV_BROWSER_PATH", "JEV_CDP_URL"):
        if not env.get(k):
            env.pop(k, None)
    return env


def run(task: str, payload: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
    """Start the worker and return its JSON result. Never raises; failures come back as {"ok": False, "status": ...}."""
    timeout = timeout or settings.browser_booking_timeout
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(payload, f, default=str)
            tmp = f.name
        cmd = [python_path(), str(WORKER), "--task", task, "--payload-file", tmp]
        log.info("browser booking %s via %s driver (timeout %ss)", task, driver(), timeout)
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=_env(), cwd=str(ROOT))
        line = next((ln for ln in reversed((proc.stdout or "").splitlines()) if ln.strip().startswith("{")), "")
        if not line:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            return {"ok": False, "status": "error", "message": "worker produced no result: " + " | ".join(tail)[:300], "driver": driver()}
        res = json.loads(line)
        if res.get("status") not in STATUSES:
            res["status"] = "error" if not res.get("ok") else res.get("status")
        if not res.get("ok"):
            log.warning("browser booking %s failed: %s (%s)", task, res.get("status"), res.get("message"))
        return res
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "message": f"the browser worker did not finish within {timeout}s", "driver": driver()}
    except Exception as e:
        return {"ok": False, "status": "error", "message": f"{type(e).__name__}: {e}"[:300], "driver": driver()}
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _shot_path(tag: str) -> str:
    d = Path(settings.upload_dir)
    if not d.is_absolute():
        d = ROOT / d
    return str(d / "zoom-runs" / f"{tag}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.png")


def book(url: str, start_utc: datetime, name: str, email: str, notes: str, dry_run: bool | None = None) -> dict[str, Any]:
    first, _, last = (name or "").strip().partition(" ")
    payload = {"url": url, "start_iso": start_utc.isoformat(), "timezone": settings.host_timezone, "first_name": first or name,
               "last_name": last.strip() or "-", "email": email, "notes": (notes or "")[:500],
               "dry_run": settings.browser_booking_dry_run if dry_run is None else dry_run, "screenshot": _shot_path("book")}
    return run("book", payload)


def reschedule(reschedule_url: str, start_utc: datetime, dry_run: bool | None = None) -> dict[str, Any]:
    payload = {"url": reschedule_url, "start_iso": start_utc.isoformat(), "timezone": settings.host_timezone,
               "dry_run": settings.browser_booking_dry_run if dry_run is None else dry_run, "screenshot": _shot_path("reschedule")}
    return run("reschedule", payload)


def cancel(cancel_url: str, dry_run: bool | None = None) -> dict[str, Any]:
    payload = {"url": cancel_url, "timezone": settings.host_timezone,
               "dry_run": settings.browser_booking_dry_run if dry_run is None else dry_run, "screenshot": _shot_path("cancel")}
    return run("cancel", payload)


def summary(res: dict[str, Any]) -> dict[str, Any]:
    """What is stored on the booking row (bookings.zoom_run): small, no page text."""
    return {k: res.get(k) for k in ("ok", "status", "driver", "elapsed_ms", "message", "screenshot", "dry_run") if k in res} | {
        "steps": (res.get("steps") or [])[:30]}
