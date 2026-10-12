"""Zoom Scheduler browser worker: book, reschedule or cancel on the public booking page, no Zoom API credentials.

Runs in the separate jev-ultrafast environment (Python 3.12: `D:\\jev\\venv` on the dev machine, see docs/BROWSER_BOOKING.md)
and is called by the app as a subprocess (app/booking/browser_booking.py). One JSON payload in, one JSON line out.

    python scripts/zoom_browser_worker.py --task book --payload-file p.json
    python scripts/zoom_browser_worker.py --task book --payload '{"url": "...", "start_iso": "...", ...}'

Pipeline (docs/BROWSER_BOOKING.md)
  1. a dedicated headless Chrome/Edge is launched (or JEV_CDP_URL is used) and browser-harness is pointed at it (BU_CDP_URL)
  2. jev's Browser opens the page with the host's timezone and an en-GB locale emulated, and a tall viewport so the
     Book button below the fold is observable
  3. the slot is selected deterministically: the scheduler labels every open time "Select slot on 15/10/2026, 4:30:00 pm",
     so the wanted start is matched exactly, with the month calendar used to reach other weeks. No model guesses a time.
  4. the form is driven by the chosen driver
        jev     TypeSafe's Jev picks operations and elements from jev's element table; a small text model types values
        script  the fields are filled by label and the Book button clicked by code (no model; used when no key is set)
  5. the outcome is verified independently from the page text (date, time, email), and the links Zoom offers
     (reschedule, cancel, join) are captured for later reschedule/cancel runs
  dry_run=true fills the form and stops before the final button: nothing is ever booked, moved or cancelled.

Output: {"ok": bool, "status": "booked|rescheduled|cancelled|dry_run_ok|slot_unavailable|verify_failed|blocked|error",
         "message", "driver", "steps", "elapsed_ms", "page_url", "page_text", "links": {...}, "screenshot"}
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

VIEWPORT = (1120, 1240)
MAX_FORM_STEPS = 18
SLOT_RE = re.compile(r"select slot on\s+(\d{1,2})/(\d{1,2})/(\d{4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]m)?", re.I)  # 12 h or 24 h clock
BOOKED_RE = re.compile(r"\b(booked|confirmed|scheduled|you'?re all set|all set|has been (?:scheduled|booked)|see you)\b", re.I)
RESCHEDULED_RE = re.compile(r"\b(rescheduled|moved|updated|confirmed|all set|has been (?:rescheduled|updated|changed))\b", re.I)
CANCELLED_RE = re.compile(r"\b(cancel(?:l)?ed|has been cancel(?:l)?ed|successfully cancel)", re.I)
ERROR_RE = re.compile(r"\b(no longer available|not available|already booked|try again|something went wrong|captcha|verify you are human)\b", re.I)
BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


# ---------------------------------------------------------------- pure helpers (unit-tested from the app's test suite)
def parse_start(start_iso: str, tz: str) -> datetime:
    """The wanted start as an aware datetime in the page's timezone."""
    s = (start_iso or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz)) if ZoneInfo else dt


def slot_label_matches(label: str, start: datetime) -> bool:
    """True when a 'Select slot on dd/mm/yyyy, h:mm:ss am' label is the wanted start (mm/dd order also accepted)."""
    m = SLOT_RE.search(label or "")
    if not m:
        return False
    a, b, y, hh, mm, ap = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), (m.group(6) or "").lower()
    h24 = (hh % 12) + (12 if ap == "pm" else 0) if ap else hh
    if y != start.year or (h24, mm) != (start.hour, start.minute):
        return False
    return (a, b) == (start.day, start.month) or (a, b) == (start.month, start.day)


def date_option_matches(label: str, start: datetime) -> bool:
    """'Choose Thursday, October 15th, 2026' (the month calendar) for the wanted day."""
    t = (label or "").lower()
    if not t.startswith("choose"):
        return False
    month = start.strftime("%B").lower()
    return month in t and str(start.year) in t and re.search(rf"\b{start.day}(st|nd|rd|th)?\b", t) is not None


def expected_phrases(start: datetime) -> list[str]:
    """Pieces of the confirmation we expect to read back: 'October 15', then the time as '4:30' and as '16:30'."""
    return [f"{start.strftime('%B')} {start.day}", f"{start.hour % 12 or 12}:{start.minute:02d}", f"{start.hour:02d}:{start.minute:02d}"]


def verify_text(text: str, start: datetime | None, email: str | None, kind: str) -> tuple[bool, str]:
    """Independent outcome check on the page text. A DONE from the model is never taken as proof."""
    t = text or ""
    if ERROR_RE.search(t) and not (BOOKED_RE.search(t) or CANCELLED_RE.search(t)):
        return False, "the page reports a problem: " + ERROR_RE.search(t).group(0)
    word = {"book": BOOKED_RE, "reschedule": RESCHEDULED_RE, "cancel": CANCELLED_RE}[kind]
    if not word.search(t):
        return False, "no confirmation wording on the page"
    if kind in ("book", "reschedule") and start is not None:
        day, clock12, clock24 = expected_phrases(start)
        if day.lower() not in t.lower():
            return False, f"the page does not mention {day}"
        if not re.search(rf"(?<![\d:]){re.escape(clock12)}(?!\d)|(?<![\d:]){re.escape(clock24)}(?!\d)", t):
            return False, f"the page does not mention {clock12}"
    if kind == "book" and email and email.lower() not in t.lower():
        return True, "confirmed (email not echoed on the page)"
    return True, "confirmed"


def pick_links(anchors: list[dict[str, str]]) -> dict[str, str]:
    """reschedule / cancel / join links from the confirmation page, by href or text."""
    out: dict[str, str] = {}
    for a in anchors or []:
        href, text = (a.get("href") or "").strip(), (a.get("text") or "").strip().lower()
        if not href.startswith("http"):
            continue
        if "reschedule" not in out and ("reschedule" in href.lower() or "reschedule" in text):
            out["reschedule"] = href
        elif "cancel" not in out and ("cancel" in href.lower() or text.startswith("cancel")):
            out["cancel"] = href
        elif "join" not in out and re.search(r"zoom\.us/(j|w|s)/", href):
            out["join"] = href
        elif "ics" not in out and (".ics" in href.lower() or "calendar" in text):
            out["ics"] = href
    return out


def build_goal(task: str, p: dict[str, Any], start: datetime | None, dry_run: bool) -> str:
    """The one natural-language goal handed to jev once the slot is selected by code."""
    when = f"{start.strftime('%A, %B')} {start.day}, {start.year} at {start.hour % 12 or 12}:{start.minute:02d} {start.strftime('%p')}" if start else ""
    if task == "book":
        fields = (f"first name '{p.get('first_name', '')}', last name '{p.get('last_name', '')}', email address '{p.get('email', '')}'"
                  + (f", and in the notes field: '{p.get('notes')}'" if p.get("notes") else ""))
        if dry_run:
            return (f"Fill the booking form for the meeting on {when}: {fields}. Do NOT click Book, Back, Add Attendees or any link. "
                    "Stop (DONE) as soon as the first name, last name and email fields contain those values.")
        return (f"Book the meeting on {when}. Fill the form: {fields}. Then click the Book button once. "
                "Do not click Back, Add Attendees, Learn More, Try it free or any other link. Stop (DONE) only when the page shows that "
                "the meeting is booked or confirmed. If the page says the time is no longer available, choose BLOCKED.")
    if task == "reschedule":
        if dry_run:
            return (f"The booking is being moved to {when}; that time is already selected. Do NOT click any confirm, reschedule or submit "
                    "button. Stop (DONE) immediately.")
        return (f"Move this booking to {when}. The new time is already selected. If a reason field is shown, type 'Requested from the "
                "website chat'. Click the button that confirms the reschedule (Reschedule, Confirm or Book). Do not click Back or Cancel. "
                "Stop (DONE) only when the page shows the booking was rescheduled or confirmed for the new time.")
    if dry_run:
        return "Do not click anything. Stop (DONE) immediately."
    return ("Cancel this booking. Click the button that cancels the booking (Cancel booking, Cancel event or Cancel meeting) and confirm "
            "when asked (Yes, Confirm, Cancel). Do not click Back, Keep or Reschedule. Stop (DONE) only when the page says the booking "
            "is cancelled. If no cancel control exists, choose BLOCKED.")


# ---------------------------------------------------------------- browser plumbing
def find_browser() -> str | None:
    p = (os.environ.get("JEV_BROWSER_PATH") or "").strip()
    if p and os.path.exists(p):
        return p
    for c in BROWSER_CANDIDATES:
        if os.path.exists(c):
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "msedge", "chrome"):
        w = shutil.which(name)
        if w:
            return w
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OwnedBrowser:
    """A headless browser launched for this run on its own profile, torn down afterwards."""

    def __init__(self) -> None:
        self.proc = None
        self.profile = None
        self.url = os.environ.get("JEV_CDP_URL", "").strip()

    def __enter__(self) -> "OwnedBrowser":
        if self.url:
            os.environ["BU_CDP_URL"] = self.url
            return self
        exe = find_browser()
        if not exe:
            raise RuntimeError("no Chrome/Edge found; set JEV_BROWSER_PATH or JEV_CDP_URL")
        port = free_port()
        self.profile = tempfile.mkdtemp(prefix="deep-zoom-")
        args = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}", "--window-size=1120,1240", "--lang=en-GB", "about:blank"]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.url = f"http://127.0.0.1:{port}"
        import urllib.request

        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url + "/json/version", timeout=2).read()
                break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("the headless browser did not start")
        os.environ["BU_CDP_URL"] = self.url
        return self

    def __exit__(self, *_a) -> None:
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)


def open_page(url: str, tz: str):
    """jev's Browser on about:blank, then timezone/locale/viewport emulation, then the real navigation."""
    from jev_ultrafast import Browser

    b = Browser("about:blank")
    try:
        b.call("Emulation.setTimezoneOverride", timezoneId=tz)
    except Exception:
        pass
    try:
        b.call("Emulation.setLocaleOverride", locale="en-GB")
    except Exception:
        pass
    b.call("Emulation.setDeviceMetricsOverride", width=VIEWPORT[0], height=VIEWPORT[1], deviceScaleFactor=1, mobile=False)
    b.call("Page.navigate", url=url)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if b.evaluate("document.readyState") == "complete":
                break
        except Exception:
            pass
        time.sleep(0.05)
    return b


def observe(b, want=None, timeout=15.0):
    """Observe until `want(page)` holds (the React app draws its controls after load)."""
    deadline = time.monotonic() + timeout
    page = b.observe(screenshot=False)
    while want and not want(page) and time.monotonic() < deadline:
        time.sleep(0.3)
        page = b.observe(screenshot=False)
    return page


def clicks(page) -> list[dict]:
    return [a for a in page["actions"] if a["kind"] == "click"]


def fills(page) -> list[dict]:
    return [a for a in page["actions"] if a["kind"] == "fill"]


def has_slots(page) -> bool:
    return any("select slot" in a["label"].lower() for a in clicks(page))


def page_text(b) -> str:
    try:
        return b.evaluate("document.body ? document.body.innerText : ''") or ""
    except Exception:
        return ""


def anchors(b) -> list[dict[str, str]]:
    try:
        return b.evaluate("[...document.querySelectorAll('a[href]')].map(a => ({ href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 80) }))") or []
    except Exception:
        return []


def screenshot(b, path: str | None) -> str | None:
    if not path:
        return None
    for _ in range(2):  # a capture can fail while the page repaints; one retry
        try:
            r = b.call("Page.captureScreenshot", format="png")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "wb") as f:
                f.write(base64.b64decode(r["data"]))
            return path
        except Exception:
            time.sleep(0.4)
    return None


def select_slot(b, start: datetime, log: list[str]) -> tuple[Any, str | None]:
    """Click the wanted slot. Uses the month calendar (and next month) to reach other weeks. Returns (page, error)."""
    page = observe(b, has_slots, timeout=15)
    for attempt in range(4):
        hit = next((a for a in clicks(page) if slot_label_matches(a["label"], start)), None)
        if hit:
            log.append(f"slot: {hit['label']}")
            b.act(hit, page)
            time.sleep(0.8)
            return observe(b, lambda p: bool(fills(p)) or not has_slots(p), timeout=10), None
        day = next((a for a in clicks(page) if date_option_matches(a["label"], start)), None)
        if day:
            log.append(f"day: {day['label']}")
            b.act(day, page)
            time.sleep(0.8)
            page = observe(b, has_slots, timeout=10)
            if not any(slot_label_matches(a["label"], start) for a in clicks(page)):
                return page, "slot_unavailable"
            continue
        nxt = next((a for a in clicks(page) if "nextmonth" in a["label"].lower().replace(" ", "") or a["label"].lower() in ("next month", "next")), None)
        if nxt and attempt < 3:
            log.append("calendar: next month")
            b.act(nxt, page)
            time.sleep(0.8)
            page = observe(b, lambda p: bool(clicks(p)), timeout=10)
            continue
        return page, "slot_unavailable"
    return page, "slot_unavailable"


# ---------------------------------------------------------------- drivers
class AttachedAgent:
    """jev's Agent loop on a Browser we already hold (the Agent class always opens its own tab)."""

    def __init__(self, browser, goal: str):
        from jev_ultrafast.agent import Agent

        self.agent = Agent.__new__(Agent)
        a = self.agent
        a.pending_text = None
        a.browser = browser
        a.record_dir = None
        a.screenshots = False
        page = browser.observe(screenshot=False)
        a.state = dict(browser=browser, goal=goal, page=page, decision=None, history=[], status="ready", plan=[goal], plan_index=0,
                       decisions=[], text_calls=[], elapsed_ms=0, started_at=None, record=False)

    def run(self, max_steps: int = MAX_FORM_STEPS):
        for state in self.agent.run():
            yield state
            if len(state["history"]) >= max_steps:
                self.agent.state["status"] = "blocked"
                break


def drive_jev(b, task: str, p: dict[str, Any], start, dry_run: bool, log: list[str]) -> str:
    goal = build_goal(task, p, start, dry_run)
    log.append("jev goal: " + goal[:160])
    ag = AttachedAgent(b, goal)
    status = "ready"
    for state in ag.run():
        status = state["status"]
        if state["history"]:
            h = state["history"][-1]
            log.append(f"jev: {h['operation']} {h['action'][:60]}" + (f" = {h['text'][:40]!r}" if h.get("text") else ""))
    return status


def _fill_by_label(b, page, pattern: str, value: str, log: list[str]):
    a = next((x for x in fills(page) if re.search(pattern, x["label"], re.I)), None)
    if not a:
        return page, False
    b.act(a, page, text=value)
    log.append(f"typed {a['label'][:30]!r}")
    time.sleep(0.3)
    return b.observe(screenshot=False), True


def drive_script(b, task: str, p: dict[str, Any], dry_run: bool, log: list[str]) -> str:
    """No model: known labels on the Zoom Scheduler page."""
    page = observe(b, lambda pg: bool(fills(pg)) or bool(clicks(pg)), timeout=10)
    if task == "book":
        for pat, val in (("first\\s*name", p.get("first_name", "")), ("last\\s*name", p.get("last_name", "") or "-"),
                         ("e-?mail", p.get("email", "")), ("share anything|notes|message|prepare", p.get("notes", ""))):
            if val:
                page, ok = _fill_by_label(b, page, pat, val, log)
                if not ok and pat.startswith(("first", "last", "e-")):
                    return "blocked"
        if dry_run:
            return "done"
        btn = next((a for a in clicks(page) if re.fullmatch(r"\s*(book|schedule|confirm|submit)\s*(meeting|booking|appointment)?\s*", a["label"], re.I)), None)
        if not btn:
            page = b.observe(screenshot=False)
            btn = next((a for a in clicks(page) if re.fullmatch(r"\s*(book|schedule|confirm|submit)\s*(meeting|booking|appointment)?\s*", a["label"], re.I)), None)
        if not btn:
            return "blocked"
        log.append(f"click {btn['label']!r}")
        b.act(btn, page)
        return "done"
    if task == "reschedule":
        if dry_run:
            return "done"
        for pat in (r"^(reschedule|confirm|book|save|update)\b", r"(reschedule|confirm)"):
            btn = next((a for a in clicks(page) if re.search(pat, a["label"], re.I) and not re.search(r"back|cancel", a["label"], re.I)), None)
            if btn:
                log.append(f"click {btn['label']!r}")
                b.act(btn, page)
                return "done"
        return "blocked"
    if dry_run:
        return "done"
    for _ in range(2):  # cancel, then a confirmation dialog if one appears
        btn = next((a for a in clicks(page) if re.search(r"cancel|yes|confirm", a["label"], re.I)
                    and not re.search(r"back|keep|no,|close|reschedule|don.t", a["label"], re.I)), None)
        if not btn:
            break
        log.append(f"click {btn['label']!r}")
        b.act(btn, page)
        time.sleep(1.0)
        page = b.observe(screenshot=False)
        if CANCELLED_RE.search(page_text(b)):
            return "done"
    return "done"


# ---------------------------------------------------------------- the run
def run(task: str, p: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    log: list[str] = []
    driver = (p.get("driver") or os.environ.get("BROWSER_BOOKING_DRIVER") or "auto").lower()
    if driver == "auto":
        driver = "jev" if os.environ.get("TYPESAFE_API_KEY") else "script"
    if driver == "jev" and not os.environ.get("TYPESAFE_API_KEY"):
        return {"ok": False, "status": "error", "message": "TYPESAFE_API_KEY is not set", "driver": driver}
    dry_run = bool(p.get("dry_run"))
    tz = p.get("timezone") or "UTC"
    start = parse_start(p["start_iso"], tz) if p.get("start_iso") else None
    out: dict[str, Any] = {"ok": False, "status": "error", "driver": driver, "dry_run": dry_run, "steps": log}
    os.environ.setdefault("BH_TELEMETRY", "0")
    os.environ.setdefault("BH_UPDATE_CHECK", "0")
    os.environ.setdefault("BU_NAME", "deep-zoom")
    try:
        with OwnedBrowser():
            b = open_page(p["url"], tz)
            try:
                if task in ("book", "reschedule"):
                    page, err = select_slot(b, start, log)
                    if err:
                        out.update(status="slot_unavailable", message=f"{expected_phrases(start)[0]} {expected_phrases(start)[2]} is not offered on the page",
                                   page_url=page["url"], screenshot=screenshot(b, p.get("screenshot")))
                        return out
                status = drive_jev(b, task, p, start, dry_run, log) if driver == "jev" else drive_script(b, task, p, dry_run, log)
                # settle, then verify independently
                time.sleep(1.2)
                text = ""
                for _ in range(25):
                    text = page_text(b)
                    if dry_run or verify_text(text, start, p.get("email"), task)[0] or ERROR_RE.search(text):
                        break
                    time.sleep(0.8)
                out.update(page_url=b.evaluate("location.href"), page_text=re.sub(r"\s+", " ", text)[:700],
                           screenshot=screenshot(b, p.get("screenshot")), links=pick_links(anchors(b)))
                if dry_run:
                    vals = {a["label"]: a.get("current_value", a.get("value", "")) for a in fills(b.observe(screenshot=False))}
                    want = [p.get("first_name"), p.get("last_name"), p.get("email")] if task == "book" else []
                    filled = all(any(v and w and w in str(v) for v in vals.values()) for w in want if w)
                    out.update(ok=filled or task != "book", status="dry_run_ok" if (filled or task != "book") else "verify_failed",
                               message="form filled, nothing submitted" if task == "book" else "page reached, nothing submitted",
                               fields=vals, agent_status=status)
                    return out
                ok, why = verify_text(text, start, p.get("email"), task)
                if ok:
                    out.update(ok=True, status={"book": "booked", "reschedule": "rescheduled", "cancel": "cancelled"}[task], message=why)
                elif ERROR_RE.search(text) and re.search(r"no longer available|not available|already booked", text, re.I):
                    out.update(status="slot_unavailable", message=why)
                else:
                    out.update(status="blocked" if status == "blocked" else "verify_failed", message=why, agent_status=status)
                return out
            finally:
                try:
                    b.close()
                except Exception:
                    pass
    except Exception as e:  # never a traceback on stdout: the app reads one JSON line
        out.update(status="error", message=f"{type(e).__name__}: {e}"[:300])
        return out
    finally:
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task", required=True, choices=["book", "reschedule", "cancel"])
    ap.add_argument("--payload", help="JSON payload")
    ap.add_argument("--payload-file", help="file with the JSON payload")
    args = ap.parse_args()
    if args.payload_file:
        with open(args.payload_file, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.loads(args.payload or "{}")
    result = run(args.task, payload)
    sys.stdout.write(json.dumps(result, default=str) + "\n")
    sys.stdout.flush()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
