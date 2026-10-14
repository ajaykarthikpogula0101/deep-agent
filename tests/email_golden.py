"""Golden snapshot of every booking-lifecycle send path: what goes out, apart from the HTML part.

capture() runs each send path with stub mailers, pinned settings, the default templates and fixed sample bookings and
"now", and returns, in send order, every message's recipient, subject, text part, reply_to, mailer kind/ref and
attachments (the .ics DTSTAMP, the only clock-dependent line, is normalised). The HTML part is left out on purpose:
it is the only thing the email redesign may change. tests/test_email_golden.py compares capture() with
tests/fixtures/email_golden.json, which was written from the code before the redesign touched the send paths:

    python -m tests.email_golden --write
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "email_golden.json"
FIXED_NOW = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)

SETTINGS = {
    "host_email": "deep@example.com", "email_from": "Deep <deep@example.com>", "site_base_url": "https://www.example.com",
    "zoom_booking_base": "https://scheduler.zoom.us/sreedeep", "public_base_url": "https://assistant.example.com",
    "link_secret": "golden-secret", "host_timezone": "Asia/Kolkata", "nudge_enabled": True, "nudge_after_hours": 24,
    "smtp_host": "",
}

GUESTS = [{"name": "Charles Babbage", "email": "charles@babbage.org"}, {"name": "Mary Somerville", "email": "mary@somerville.org"}]
HANDOFF = "https://scheduler.zoom.us/sreedeep/discovery-call?firstname=Ada&lastname=Lovelace&email=ada%40lovelace.org"

BRIEF = {
    "label": "hot", "score": 83, "verdict": "hot", "summary": "Ada wants EU fintech data for a launch in Q1.",
    "activity": {"visits": 2, "questions": 5, "channel": "search", "referrer_host": "google.com", "pages": ["/", "/lakeb2b"]},
    "groups": {"fit": 20, "intent": 30, "engagement": 10, "risk": 0},
    "reasons": [{"points": 15, "text": "company email (lovelace.org)", "cls": "verified", "proof": "website"},
                {"points": 12, "text": "asked about pricing", "cls": "observed"},
                {"points": 0, "text": "says they have a budget of 50k", "cls": "claimed"}],
    "evidence": {"verified": 15, "observed": 12, "claims": 1, "missing": []},
    "asked": ["What is the pricing for intent data?"], "talking_points": ["Show EU fintech coverage"],
    "questions_to_ask": ["When is the launch?"], "watch_outs": ["New domain"],
}


class _Patcher:
    """monkeypatch.setattr for scripts: remembers the old values and puts them back."""

    def __init__(self) -> None:
        self.saved: list[tuple[Any, str, Any]] = []

    def __call__(self, obj: Any, name: str, value: Any) -> None:
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self) -> None:
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)
        self.saved.clear()


def _norm(data: Any) -> str:
    text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
    return re.sub(r"DTSTAMP:\d{8}T\d{6}Z", "DTSTAMP:<now>", text)


def _att(attachments: list | None) -> list[list[str]]:
    return [[name, mime, _norm(data)] for name, data, mime in (attachments or [])]


class _Mailer:
    def __init__(self, out: list[dict[str, Any]], case: str, html_sink: list | None = None) -> None:
        self.out, self.case, self.html_sink = out, case, html_sink

    def enqueue(self, to, subject, body, *, html=None, attachments=None, reply_to=None, kind="mail", ref=None):
        if self.html_sink is not None:
            self.html_sink.append({"case": self.case, "to": to, "kind": kind, "html": html})
        self.out.append({"case": self.case, "via": "mailer", "to": to, "subject": subject, "body": body, "reply_to": reply_to,
                         "kind": kind, "ref": ref, "attachments": _att(attachments)})


def bookings() -> dict[str, dict[str, Any]]:
    from app import templates

    conf = dict(templates.SAMPLE_BOOKING, manage_token="Tok", attendees=GUESTS)
    pend = dict(conf, method="handoff", status="pending_zoom", zoom_meeting_id=None, meeting_id=None, join_url="", passcode="",
                handoff_url=HANDOFF)
    return {
        "confirmed": conf,
        "pending": pend,
        "confirmed_bare": dict(templates.SAMPLE_BOOKING, attendees=[], company="", company_line="", notes="", origin=""),
        "pending_bare": dict(pend, manage_token=None, attendees=[], handoff_url=""),
        "scheduler_no_join": dict(conf, method="scheduler", join_url="", zoom_meeting_id=None, passcode=""),
    }


def capture(setattr_: Callable[[Any, str, Any], None], html_sink: list | None = None) -> list[dict[str, Any]]:
    """Every send path, in order; `setattr_` is pytest's monkeypatch.setattr (or _Patcher). `html_sink`, when given,
    collects each message's HTML part (never part of the snapshot)."""
    from app import nudge, precall, templates
    from app.booking import email as mail
    from app.config import settings

    for k, v in SETTINGS.items():
        setattr_(settings, k, v)
    setattr_(templates, "get_templates", lambda: dict(templates.DEFAULTS))

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)

    setattr_(precall, "datetime", _Frozen)
    setattr_(precall, "build_for_booking", lambda booking, refresh=False, ask=None, save=True, **k: dict(BRIEF))
    setattr_(precall, "host_booking_email_async", lambda booking, send: send(dict(BRIEF)))
    out: list[dict[str, Any]] = []
    case = {"name": ""}

    def fake_send(to, subject, body, reply_to=None, html=None, attachments=None):
        if html_sink is not None:
            html_sink.append({"case": case["name"], "to": to, "kind": None, "html": html})
        out.append({"case": case["name"], "via": "_send", "to": to, "subject": subject, "body": body, "reply_to": reply_to,
                    "kind": None, "ref": None, "attachments": _att(attachments)})
        return True

    setattr_(mail, "_send", fake_send)
    B = bookings()

    def run(name: str, fn: Callable[[Any], Any]) -> None:
        case["name"] = name
        result = fn(_Mailer(out, name, html_sink))
        out.append({"case": name, "via": "return", "value": result if isinstance(result, (bool, dict, int, type(None))) else str(result)})

    # 1, 2, 10: the booking confirmation, the host's "New booking", one invitation per guest
    for key in ("confirmed", "pending", "confirmed_bare", "pending_bare", "scheduler_no_join"):
        run(f"booking:{key}", lambda m, b=B[key]: mail.send_booking_emails(dict(b), mailer=m))
    setattr_(mail, "_current", lambda b: None)
    run("booking:with_brief", lambda m: mail.send_booking_emails(dict(B["confirmed"]), mailer=m, with_brief=True))
    setattr_(mail, "_current", lambda b: dict(b, status="cancelled"))
    run("booking:with_brief_since_cancelled", lambda m: mail.send_booking_emails(dict(B["pending"]), mailer=m, with_brief=True))
    setattr_(mail, "_current", lambda b: dict(b, rescheduled_at=FIXED_NOW))
    run("booking:with_brief_since_moved", lambda m: mail.send_booking_emails(dict(B["confirmed"]), mailer=m, with_brief=True))
    setattr_(mail, "_current", lambda b: None)
    # 3, 4, 12: cancelled
    run("cancel:confirmed", lambda m: mail.send_cancel_emails(dict(B["confirmed"], status="cancelled",
                                                                   zoom_note="Cancelled here; please also cancel the event in Zoom Scheduler."), mailer=m))
    run("cancel:pending_bare", lambda m: mail.send_cancel_emails(dict(B["pending_bare"], status="cancelled"), mailer=m))
    # 5, 6, 11: moved
    old = {"old_label_visitor": "Tue 06 Oct, 10:00 (America/New_York)", "old_label_host": "Tue 06 Oct, 19:30 (Asia/Kolkata)"}
    run("move:confirmed", lambda m: mail.send_reschedule_emails(dict(B["confirmed"], **old), mailer=m))
    run("move:pending", lambda m: mail.send_reschedule_emails(dict(B["pending"], **old), mailer=m))
    run("move:no_old_label", lambda m: mail.send_reschedule_emails(dict(B["confirmed_bare"]), mailer=m))
    run("move:pending_bare", lambda m: mail.send_reschedule_emails(dict(B["pending_bare"], **old), mailer=m))
    # 7, 13: the day-before reminder
    for key in ("confirmed", "pending", "pending_bare", "scheduler_no_join"):
        run(f"reminder:{key}", lambda m, b=B[key]: mail.send_reminder_email(dict(b), mailer=m))
    setattr_(templates, "get_templates", lambda: dict(templates.DEFAULTS, visitor_reminder_enabled="false"))
    run("reminder:disabled", lambda m: mail.send_reminder_email(dict(B["confirmed"]), mailer=m))
    setattr_(templates, "get_templates", lambda: dict(templates.DEFAULTS))
    # 8: the host's day-before brief (tomorrow / today)
    run("precall:tomorrow", lambda m: precall.send_host_reminder(dict(B["confirmed"], start_utc=FIXED_NOW + timedelta(hours=22),
                                                                       end_utc=FIXED_NOW + timedelta(hours=22, minutes=15)), mailer=m))
    run("precall:today", lambda m: precall.send_host_reminder(dict(B["confirmed"], start_utc=FIXED_NOW + timedelta(hours=3),
                                                                    end_utc=FIXED_NOW + timedelta(hours=3, minutes=15)), mailer=m))
    run("precall:pending_bare", lambda m: precall.send_host_reminder(dict(B["pending_bare"]), mailer=m))
    # 9 and the other callers of send_visitor_confirmation (hand-off, booked, enquiry, hand-over)
    for status in ("handoff", "booked", "enquiry", "handover", "nudge"):
        run(f"visitor_confirmation:{status}", lambda m, s=status: mail.send_visitor_confirmation(dict(templates.SAMPLE_LEAD, status=s)))
    from app.booking.zoom import Schedule

    row = {"id": 1, "ts": FIXED_NOW - timedelta(hours=30), "name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "demo",
           "slot_start": datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc), "visitor_tz": "America/New_York",
           "schedule_slug": "discovery-call", "company": None, "session_id": None}
    sched = [Schedule(slug="discovery-call", id="x", name="LakeB2B Discovery Call", duration_min=15,
                      booking_link="https://scheduler.zoom.us/sreedeep/discovery-call")]
    run("nudge:lead", lambda m: mail.send_visitor_confirmation(nudge.lead_for_email(row, sched)))
    run("nudge:no_slot", lambda m: mail.send_visitor_confirmation(nudge.lead_for_email(dict(row, slot_start=None), [])))
    # Console -> Emails -> Send test
    for kind in ("host", "visitor_booking", "visitor_handover", "visitor_nudge", "visitor_confirmed", "host_booking",
                 "visitor_rescheduled", "visitor_cancelled", "visitor_reminder", "visitor_gap"):
        run(f"send_test:{kind}", lambda m, k=kind: mail.send_test(k))
    return out


def main() -> None:
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault("OPENAI_API_KEY", "test")                    # as tests/conftest.py
    os.environ.setdefault("DATABASE_URL", "postgresql://assistant:assistant@localhost:5432/assistant")
    p = _Patcher()
    try:
        data = capture(p)
    finally:
        p.undo()
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    if "--write" in sys.argv:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {FIXTURE} ({len(data)} entries)")
    else:
        print(text)


if __name__ == "__main__":
    main()
