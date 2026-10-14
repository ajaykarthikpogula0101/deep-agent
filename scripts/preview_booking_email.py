"""Render the booking email (app/booking/email_html.py) to local HTML files for a look in a browser, no SMTP:

    python scripts/preview_booking_email.py [out_dir]          # default: email_preview/

Writes visitor/host x confirmed/pending, using the real renderer and the editable text templates. Real emails carry
their images inline; the preview loads them from PUBLIC_BASE_URL or http://localhost:8080 (run the app to see them).
To send the real thing to the host inbox instead: Console → Emails → Send test.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import templates  # noqa: E402
from app.booking import email_html  # noqa: E402

BASE = "http://localhost:8080"
CONFIRMED = {
    "id": 7, "name": "Harsha", "email": "harsha@example.com", "company": "xyz.com", "notes": "Pipeline data for our APAC launch",
    "schedule_slug": "gtm-strategy", "schedule_name": "GTM Strategy Session: Data, AI & Revenue Acceleration", "duration_min": 45,
    "start_utc": datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc), "end_utc": datetime(2026, 10, 9, 13, 45, tzinfo=timezone.utc),
    "visitor_tz": "Asia/Kolkata", "method": "meeting", "status": "confirmed", "zoom_meeting_id": "812 3456 7890", "meeting_id": "812 3456 7890",
    "join_url": "https://zoom.us/j/81234567890?pwd=sample", "passcode": "742913", "handoff_url": "",
    "ics_url": f"{BASE}/booking/7/ics?t=sample", "manage_url": f"{BASE}/booking/7/manage?t=sample",
    "company_line": "XYZ (xyz.com) · Growth analytics for retail brands",
}
PENDING = dict(CONFIRMED, method="handoff", status="pending_zoom", zoom_meeting_id=None, meeting_id=None, join_url="", passcode="",
               handoff_url="https://scheduler.zoom.us/sreedeep/gtm-strategy?firstname=Harsha&email=harsha%40example.com")


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "email_preview")
    out.mkdir(parents=True, exist_ok=True)
    tpl = dict(templates.DEFAULTS)
    now = datetime(2026, 10, 9, 12, 42, tzinfo=timezone.utc)
    for state, booking in (("confirmed", CONFIRMED), ("pending", PENDING)):
        for audience in ("visitor", "host"):
            path = out / f"{audience}_{state}.html"
            path.write_text(email_html.render(booking, audience, tpl, now=now, images="url"), encoding="utf-8")
            print(path)


if __name__ == "__main__":
    main()
