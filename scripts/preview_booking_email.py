"""Write every booking-lifecycle email (the Ledger design, app/booking/email_html.py) to local HTML files, no SMTP:

    python scripts/preview_booking_email.py [out_dir]          # default: email_preview/

Runs the real send functions (app/booking/email.py, app/precall.py) with a capturing mailer instead of the queue, the
default templates (not the ones saved in the database) and example settings, so nothing is sent, nothing is read from
or written to the database, and no running app is needed. Every email x audience x state is written, plus a few stress
cases (long names, many guests, missing fields, a long brief), and index.html links them all. The design has no
images. To send the real thing to the host inbox instead: Console -> Emails -> Send test.
"""
from __future__ import annotations

import html
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "preview")

from app import precall, templates  # noqa: E402
from app.booking import email as mail  # noqa: E402
from app.config import settings  # noqa: E402

BASE = "https://assistant.deependhq.com"
SETTINGS = {"host_email": "deep@deependhq.com", "email_from": "Deep <deep@deependhq.com>", "site_base_url": "https://deependhq.com",
            "zoom_booking_base": "https://scheduler.zoom.us/sreedeep", "public_base_url": BASE, "link_secret": "preview",
            "host_timezone": "Asia/Kolkata", "nudge_enabled": True, "nudge_after_hours": 24, "smtp_host": ""}

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
START = (NOW + timedelta(days=1)).replace(hour=13, minute=0)          # tomorrow, 6:30 PM IST / 9:00 AM EDT
GUESTS = [{"name": "Charles Babbage", "email": "charles@babbage.org"}, {"name": "Mary Somerville", "email": "mary@somerville.org"}]
CONFIRMED: dict[str, Any] = {
    "id": 7, "name": "Harsha Rao", "email": "harsha@example.com", "company": "xyz.com", "notes": "Pipeline data for our APAC launch",
    "schedule_slug": "gtm-strategy", "schedule_name": "GTM Strategy Session: Data, AI & Revenue Acceleration", "duration_min": 45,
    "start_utc": START, "end_utc": START + timedelta(minutes=45), "visitor_tz": "America/New_York", "method": "meeting",
    "status": "confirmed", "zoom_meeting_id": "812 3456 7890", "join_url": "https://zoom.us/j/81234567890?pwd=sample",
    "passcode": "742913", "handoff_url": "", "ics_url": f"{BASE}/booking/7/ics?t=sample", "manage_url": f"{BASE}/booking/7/manage?t=sample",
    "company_line": "XYZ (xyz.com) · Growth analytics for retail brands", "manage_token": "tok",
    "origin": "Bengaluru, Karnataka, IN · via linkedin.com (social) · visit 2 · 4 messages", "attendees": GUESTS,
}
PENDING = dict(CONFIRMED, method="handoff", status="pending_zoom", zoom_meeting_id=None, meeting_id=None, join_url="", passcode="",
               handoff_url="https://scheduler.zoom.us/sreedeep/gtm-strategy?firstname=Harsha&lastname=Rao&email=harsha%40example.com")
OLD = {"previous_start_utc": START - timedelta(days=1, hours=3)}
LONG = dict(CONFIRMED, name="Maximiliana Alexandra Fitzgerald-Montgomery",
            email="maximiliana.fitzgerald-montgomery@verylongcompanydomain-analytics.co.uk", company="verylongcompanydomain-analytics.co.uk",
            company_line="Very Long Company Domain Analytics Ltd (verylongcompanydomain-analytics.co.uk) · Enterprise revenue intelligence for regulated industries",
            notes="We are evaluating three vendors for intent data across EMEA and APAC and need coverage numbers for fintech, insurance "
                  "and healthcare before our board meeting at the end of the quarter.",
            attendees=[{"name": f"Guest Number {i} With A Long Name", "email": f"guest.number.{i}@another-very-long-domain-example.com"}
                       for i in range(1, 6)])
BARE = {"id": 9, "name": "Ada", "email": "ada@example.com", "status": "confirmed", "method": "meeting", "schedule_name": "Intro Call",
        "start_utc": START, "end_utc": START + timedelta(minutes=15), "visitor_tz": "Europe/London", "attendees": []}

BRIEF = {"label": "hot", "score": 83, "verdict": "hot", "summary": "Harsha runs growth at XYZ and wants APAC pipeline data before a Q1 launch.",
         "activity": {"visits": 3, "questions": 6, "channel": "social", "referrer_host": "linkedin.com", "pages": ["/", "/lakeb2b", "/pricing"]},
         "groups": {"fit": 20, "intent": 30, "engagement": 10, "risk": -4}, "flags": [{"text": "x"}],
         "reasons": [{"points": 15, "text": "company email (xyz.com)", "cls": "verified", "proof": "web"},
                     {"points": 12, "text": "asked about pricing twice", "cls": "observed"},
                     {"points": -4, "text": "domain registered this year", "cls": "risk"},
                     {"points": 0, "text": "says they have a budget of 50k for the first quarter", "cls": "claimed"}],
         "evidence": {"verified": 15, "observed": 12, "claims": 1, "missing": ["IP network lookup"]},
         "asked": ["What is the pricing for intent data?", "Do you cover Singapore and Indonesia?"],
         "talking_points": ["Show APAC coverage for retail and fintech", "Offer a 500-record sample before the launch"],
         "questions_to_ask": ["When is the launch, and who signs off?"], "watch_outs": ["New domain: confirm the company is real"]}
LONG_BRIEF = dict(BRIEF, asked=[f"A long question number {i} about coverage, freshness, pricing tiers and how the data is verified before every delivery?"
                                for i in range(1, 7)],
                  talking_points=[f"Talking point {i}: walk through the sample, the refresh cadence and the compliance notes for regulated industries"
                                  for i in range(1, 6)])


class Capture:
    """Stands in for the mailer queue and for SMTP (_send): keeps every message, sends nothing."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.case = ""

    def enqueue(self, to, subject, body, *, html=None, attachments=None, reply_to=None, kind="mail", ref=None):
        self.items.append({"case": self.case, "to": to, "subject": subject, "html": html, "kind": kind})

    def send(self, to, subject, body, reply_to=None, html=None, attachments=None):
        self.items.append({"case": self.case, "to": to, "subject": subject, "html": html, "kind": "_send"})
        return True


def cases(cap: Capture) -> list[tuple[str, str, str, str, dict[str, Any]]]:
    """(file stem, email number, label, audience, the captured message) for every preview."""
    def run(name, fn):
        cap.case = name
        fn()

    def pick(case, kind=None, to=None):
        return next(i for i in cap.items if i["case"] == case and (kind is None or i["kind"] == kind) and (to is None or i["to"] == to))

    brief = {"b": BRIEF}
    precall.build_for_booking = lambda booking, refresh=False, ask=None, save=True, **k: dict(brief["b"])
    precall.host_booking_email_async = lambda booking, send: send(dict(brief["b"]))
    mail._send = cap.send
    run("conf", lambda: mail.send_booking_emails(dict(CONFIRMED), mailer=cap))
    run("pend", lambda: mail.send_booking_emails(dict(PENDING), mailer=cap))
    mail._current = lambda b: dict(b, rescheduled_at=NOW)
    run("conf_brief", lambda: mail.send_booking_emails(dict(CONFIRMED), mailer=cap, with_brief=True))
    mail._current = lambda b: dict(b, status="cancelled")
    run("pend_brief", lambda: mail.send_booking_emails(dict(PENDING), mailer=cap, with_brief=True))
    mail._current = lambda b: None
    brief["b"] = LONG_BRIEF
    run("long", lambda: mail.send_booking_emails(dict(LONG), mailer=cap, with_brief=True))
    brief["b"] = BRIEF
    run("bare", lambda: mail.send_booking_emails(dict(BARE), mailer=cap))
    run("cancel", lambda: mail.send_cancel_emails(dict(CONFIRMED, status="cancelled",
                                                       zoom_note="Cancelled here; please also cancel the event in Zoom Scheduler."), mailer=cap))
    run("cancel_bare", lambda: mail.send_cancel_emails(dict(BARE, status="cancelled"), mailer=cap))
    run("move", lambda: mail.send_reschedule_emails(dict(CONFIRMED, **OLD), mailer=cap))
    run("move_pend", lambda: mail.send_reschedule_emails(dict(PENDING, **OLD), mailer=cap))
    run("move_label", lambda: mail.send_reschedule_emails(dict(CONFIRMED, old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)"), mailer=cap))
    run("rem", lambda: mail.send_reminder_email(dict(CONFIRMED), mailer=cap))
    soon = NOW + timedelta(hours=3)
    run("rem_pend_today", lambda: mail.send_reminder_email(dict(PENDING, start_utc=soon, end_utc=soon + timedelta(minutes=45)), mailer=cap))
    run("brief_tomorrow", lambda: precall.send_host_reminder(dict(CONFIRMED, start_utc=NOW + timedelta(hours=22)), mailer=cap))
    run("brief_today", lambda: precall.send_host_reminder(dict(PENDING, start_utc=soon), mailer=cap))
    brief["b"] = LONG_BRIEF
    run("brief_long", lambda: precall.send_host_reminder(dict(LONG, start_utc=NOW + timedelta(hours=22)), mailer=cap))
    brief["b"] = BRIEF
    from app import nudge
    from app.booking.zoom import Schedule

    row = {"id": 1, "ts": NOW - timedelta(hours=30), "name": "Harsha Rao", "email": "harsha@example.com", "reason": "demo",
           "slot_start": START + timedelta(days=1), "visitor_tz": "America/New_York", "schedule_slug": "gtm-strategy", "company": None,
           "session_id": None}
    sched = [Schedule(slug="gtm-strategy", id="x", name=CONFIRMED["schedule_name"], duration_min=45,
                      booking_link="https://scheduler.zoom.us/sreedeep/gtm-strategy")]
    run("nudge", lambda: mail.send_visitor_confirmation(nudge.lead_for_email(row, sched)))
    run("nudge_noslot", lambda: mail.send_visitor_confirmation(nudge.lead_for_email(dict(row, slot_start=None), [])))
    tests = ("host_booking", "visitor_confirmed", "visitor_cancelled", "visitor_rescheduled", "visitor_reminder", "visitor_nudge")
    for k in tests:
        run(f"test_{k}", lambda k=k: mail.send_test(k))

    g = GUESTS[0]["email"]
    return [
        ("01-visitor-confirmed", "1", "Booking confirmed", "visitor", pick("conf", "booking_visitor")),
        ("01-visitor-pending", "1", "Booking request (awaiting Zoom)", "visitor", pick("pend", "booking_visitor")),
        ("01-visitor-bare", "1", "Booking confirmed, missing optional fields", "visitor", pick("bare", "booking_visitor")),
        ("01-visitor-long", "1", "Stress: long name and email, 5 guests", "visitor", pick("long", "booking_visitor")),
        ("02-host-confirmed", "2", "New booking confirmed", "host", pick("conf", "booking_host")),
        ("02-host-pending", "2", "New booking request", "host", pick("pend", "booking_host")),
        ("02-host-confirmed-brief-since-moved", "2", "New booking + brief, visitor has since moved", "host", pick("conf_brief", "booking_host")),
        ("02-host-pending-brief-since-cancelled", "2", "New booking request + brief, since cancelled", "host", pick("pend_brief", "booking_host")),
        ("02-host-long", "2", "Stress: long name and email, 5 guests, long notes, long brief", "host", pick("long", "booking_host")),
        ("02-host-bare", "2", "New booking, missing optional fields", "host", pick("bare", "booking_host")),
        ("03-visitor-cancelled", "3", "Booking cancelled", "visitor", pick("cancel", "cancel_visitor")),
        ("04-host-cancelled", "4", "Booking cancelled (with Zoom note)", "host", pick("cancel", "cancel_host")),
        ("04-host-cancelled-no-link", "4", "Booking cancelled, no booking page", "host", pick("cancel_bare", "cancel_host")),
        ("05-visitor-moved", "5", "Booking rescheduled", "visitor", pick("move", "reschedule_visitor")),
        ("05-visitor-moved-pending", "5", "Rescheduled, awaiting Zoom", "visitor", pick("move_pend", "reschedule_visitor")),
        ("05-visitor-moved-old-label", "5", "Rescheduled, old time known only as a label", "visitor", pick("move_label", "reschedule_visitor")),
        ("06-host-moved", "6", "Booking rescheduled", "host", pick("move", "reschedule_host")),
        ("06-host-moved-pending", "6", "Rescheduled, awaiting Zoom", "host", pick("move_pend", "reschedule_host")),
        ("07-visitor-reminder-tomorrow", "7", "Day-before reminder", "visitor", pick("rem", "reminder_visitor")),
        ("07-visitor-reminder-today-pending", "7", "Reminder (today), awaiting Zoom", "visitor", pick("rem_pend_today", "reminder_visitor")),
        ("08-host-brief-tomorrow", "8", "Brief for tomorrow", "host", pick("brief_tomorrow", "precall_host")),
        ("08-host-brief-today-pending", "8", "Brief for your call today, awaiting Zoom", "host", pick("brief_today", "precall_host")),
        ("08-host-brief-long", "8", "Stress: long brief, 5 guests", "host", pick("brief_long", "precall_host")),
        ("09-visitor-nudge", "9", "Unconfirmed-hold reminder", "visitor", pick("nudge")),
        ("09-visitor-nudge-no-slot", "9", "Unconfirmed-hold reminder, no time known", "visitor", pick("nudge_noslot")),
        ("10-guest-invited", "10", "Guest invited", "guest", pick("conf", "attendee_booked", g)),
        ("10-guest-invited-pending", "10", "Guest invited, awaiting Zoom", "guest", pick("pend", "attendee_booked", g)),
        ("11-guest-moved", "11", "Guest: call moved", "guest", pick("move", "attendee_moved", g)),
        ("11-guest-moved-pending", "11", "Guest: call moved, awaiting Zoom", "guest", pick("move_pend", "attendee_moved", g)),
        ("12-guest-cancelled", "12", "Guest: call cancelled", "guest", pick("cancel", "attendee_cancelled", g)),
        ("13-guest-reminder", "13", "Guest: day-before reminder", "guest", pick("rem", "attendee_reminder", g)),
        ("13-guest-reminder-today-pending", "13", "Guest: reminder (today), awaiting Zoom", "guest", pick("rem_pend_today", "attendee_reminder", g)),
        *[(f"test-{k.replace('_', '-')}", "test", f"Send test: {k}", "host inbox", pick(f"test_{k}")) for k in tests],
    ]


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "email_preview")
    out.mkdir(parents=True, exist_ok=True)
    for k, val in SETTINGS.items():
        setattr(settings, k, val)
    templates.get_templates = lambda: dict(templates.DEFAULTS)
    rows = []
    for stem, num, label, audience, item in cases(Capture()):
        (out / f"{stem}.html").write_text(item["html"] or "", encoding="utf-8")
        kb = len((item["html"] or "").encode()) / 1024
        rows.append(f'<tr><td>{html.escape(num)}</td><td><a href="{stem}.html">{html.escape(label)}</a></td><td>{html.escape(audience)}</td>'
                    f'<td>{html.escape(item["to"])}</td><td>{html.escape(item["subject"])}</td><td>{kb:.0f} KB</td></tr>')
    (out / "index.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Booking emails: Ledger previews</title><style>body{font:14px/1.5 -apple-system,'Segoe UI',Roboto,Arial,sans-serif;margin:24px;"
        "color:#151B32;background:#F6F7FC}table{border-collapse:collapse;background:#fff}td,th{border:1px solid #E4E7F2;padding:6px 10px;"
        "text-align:left;vertical-align:top}a{color:#4537E8}</style></head><body><h1>Booking emails (Ledger)</h1>"
        f"<p>Rendered by the real send functions with example data and the default templates: {len(rows)} emails. "
        'Screenshots: <a href="shots/">shots/</a>.</p>'
        "<table><tr><th>#</th><th>Email</th><th>Audience</th><th>To</th><th>Subject</th><th>Size</th></tr>"
        + "".join(rows) + "</table></body></html>", encoding="utf-8")
    print(f"{len(rows)} emails written to {out.resolve()} (index.html)")


if __name__ == "__main__":
    main()
