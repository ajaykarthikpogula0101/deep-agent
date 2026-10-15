"""Send every visitor and guest booking email, plus the host's, to inboxes you choose, to see them in real mail apps
(Gmail, Outlook, iCloud Mail, Apple Mail on a phone):

    python scripts/send_test_emails.py you@outlook.com you@icloud.com
    python scripts/send_test_emails.py you@outlook.com --only confirmed,cancelled

Uses the SMTP settings in .env (the real From address), sample bookings (Ada Lovelace, LakeB2B Discovery Call) and the
templates saved in the console. Nothing is booked, nothing is written to the database and no real visitor or guest is
emailed: every message, including the guest and host copies, goes only to the addresses on the command line, with
"[test]" in front of the subject. The Ask Deep questions open the assistant with the question filled in (sample
links, so they never act on a booking).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import email_ask, mailer, templates  # noqa: E402
from app.booking import email as mail  # noqa: E402
from app.config import settings  # noqa: E402

KINDS = ("confirmed", "pending", "rescheduled", "cancelled", "reminder", "nudge")
_EMAIL = re.compile(r"[^\s@<>\"']+@[^\s@<>\"']+\.[A-Za-z]{2,}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("to", nargs="+", help="inboxes that receive the whole set")
    ap.add_argument("--only", default=",".join(KINDS), help=f"comma list from: {', '.join(KINDS)}")
    ap.add_argument("--no-host", action="store_true", help="leave out Deep's copies")
    a = ap.parse_args()
    to = [x.strip() for x in a.to if _EMAIL.fullmatch(x.strip())]
    if not to or len(to) != len(a.to):
        ap.error("every recipient must be a plain email address")
    if not settings.smtp_host:
        ap.error("SMTP_HOST is not set in .env: nothing can be sent")
    only = {k.strip() for k in a.only.split(",") if k.strip()}

    # the panel gets sample links: they prefill a question and never act on a real booking
    email_ask.panel = lambda *, kind, pending, **k: email_ask.sample_panel(kind, pending)
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=2, hours=1)
    sent = 0
    for addr in to:
        guest = {"name": "Grace Hopper", "email": addr}
        base = dict(templates.SAMPLE_BOOKING, email=addr, attendees=[guest], start_utc=start, end_utc=start + timedelta(minutes=30))
        out: list[tuple] = []
        m = mailer.Mailer(sender=lambda t, s, b, **k: out.append((t, s, b, k)) or True, sync=True)
        if "confirmed" in only:
            mail.send_booking_emails(dict(base, status="confirmed"), mailer=m)
        if "pending" in only:
            mail.send_booking_emails(dict(base, status="pending_zoom", method="handoff", join_url="", zoom_meeting_id=None, passcode=""),
                                     mailer=m)
        if "rescheduled" in only:
            mail.send_reschedule_emails(dict(base, previous_start_utc=start - timedelta(days=1),
                                             old_label_visitor="the earlier time"), mailer=m)
        if "cancelled" in only:
            mail.send_cancel_emails(dict(base, status="cancelled"), mailer=m)
        if "reminder" in only:
            mail.send_reminder_email(dict(base, status="confirmed"), mailer=m)
        msgs = [(addr, s, b, k) for t, s, b, k in out if t in (addr, settings.host_email) and not (a.no_host and t == settings.host_email)]
        if "nudge" in only:
            lead = dict(templates.SAMPLE_LEAD, status="nudge", email=addr, slot_start=start)
            r = mail.render_visitor(lead)
            if r:
                msgs.append((addr, r[0], r[1], {"html": mail._nudge_html(lead, r[0], r[1], sample=True), "reply_to": settings.host_email}))
        for t, s, b, k in msgs:          # every copy goes to the test inbox, never to the host or a guest address
            ok = mail._send(addr, "[test] " + s, b, reply_to=k.get("reply_to"), html=k.get("html"), attachments=k.get("attachments"))
            sent += ok
            print(("sent  " if ok else "FAILED") + f"  {addr:<32} {s[:80]}")
    print(f"{sent} sent from {settings.email_from}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
