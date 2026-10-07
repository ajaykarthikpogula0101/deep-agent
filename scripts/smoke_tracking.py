"""Session origin tracking through the running API: beacon -> chat -> admin view -> host brief origin line.

    python scripts/smoke_tracking.py            # expects the API on http://127.0.0.1:8080
    python scripts/smoke_tracking.py --boot     # starts its own server on port 8089 and stops it afterwards

Uses a spoofed X-Forwarded-For so the local run geolocates a public address (TRUST_PROXY=true in dev).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BOOT = "--boot" in sys.argv
PORT = 8089 if BOOT else 8080
BASE = f"http://127.0.0.1:{PORT}"
SPOOF_IP = os.environ.get("SMOKE_IP", "49.207.200.10")  # a public address; change to test another location
SESSION, VISITOR = str(uuid.uuid4()), str(uuid.uuid4())
HEADERS = {"Origin": "http://localhost:8080", "X-Forwarded-For": SPOOF_IP,
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}


def chat(message: str) -> str:
    text = ""
    with httpx.stream("POST", f"{BASE}/chat", json={"message": message, "history": [], "timezone": "Asia/Kolkata"},
                      headers={**HEADERS, "X-Session-Id": SESSION, "X-Visitor-Id": VISITOR}, timeout=90) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                if ev["type"] == "token":
                    text += ev["text"]
    return text


def main() -> int:
    proc = None
    if BOOT:
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
                                cwd=ROOT, env=env)
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{BASE}/healthz", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            print("API not reachable at", BASE); return 1

        print("=== beacon (chat opened on /pillars, came from LinkedIn, spoofed IP", SPOOF_IP + ")")
        r = httpx.post(f"{BASE}/track", headers=HEADERS, timeout=10, json={
            "session_id": SESSION, "visitor_id": VISITOR, "page": "https://deependhq.com/pillars?utm_source=linkedin&utm_medium=social",
            "referrer": "https://www.linkedin.com/feed/", "timezone": "Asia/Kolkata", "lang": "en-IN", "screen": "1920x1080"})
        print(r.status_code, r.json())

        print("\n=== two chat messages on that session")
        print("  >", chat("What is ChampGraph?")[:90].replace("\n", " "), "...")
        print("  >", chat("What does Lake B2B do?")[:90].replace("\n", " "), "...")
        time.sleep(3)  # background geo lookup

        print("\n=== origin line (what the host brief will say)")
        from app.tracking import describe_session
        print("  ", describe_session(SESSION) or "(nothing recorded)")

        print("\n=== session row")
        from app.db import conn
        with conn() as c:
            row = c.execute("""SELECT ip, city, region, country_code, isp, geo_status, channel, referrer_host, page, utm, messages,
                                      client_tz, lang, screen FROM sessions WHERE session_id = %s""", (SESSION,)).fetchone()
        for k, v in zip(["ip", "city", "region", "country_code", "isp", "geo_status", "channel", "referrer_host", "page", "utm",
                         "messages", "client_tz", "lang", "screen"], row or []):
            print(f"   {k:14} {v}")

        token = os.environ.get("ADMIN_TOKEN", "")
        print("\n=== admin summary (GET /admin/sessions)")
        r = httpx.get(f"{BASE}/admin/sessions?days=1&limit=5", headers={"X-Admin-Token": token}, timeout=10)
        if r.status_code == 200:
            s = r.json()["summary"]
            print("  ", {k: s[k] for k in ("sessions", "visitors", "messages", "leads")})
            print("   countries:", [(c["country"], c["sessions"]) for c in s["countries"]])
            print("   channels: ", [(c["channel"], c["sessions"]) for c in s["channels"]])
        else:
            print("  ", r.status_code, "(set ADMIN_TOKEN in .env to enable /admin)")
        print("\n=== wrong token is refused:", httpx.get(f"{BASE}/admin/sessions", headers={"X-Admin-Token": "nope"}, timeout=10).status_code)
        return 0
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
