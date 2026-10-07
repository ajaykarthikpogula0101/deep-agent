"""Send one sample host brief to HOST_EMAIL using the SMTP settings in .env.

    python scripts/test_email.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.booking.email import render_brief, send_host_brief  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> int:
    if not settings.smtp_host or settings.smtp_password in ("", "FILL_ME"):
        print("SMTP_HOST / SMTP_PASSWORD not set in .env")
        return 2
    start = datetime.now(timezone.utc) + timedelta(days=1)
    lead = {
        "name": "Test Visitor", "email": "visitor@example.com", "reason": "sample brief from the assistant",
        "slot_start": start, "visitor_tz": "America/New_York", "status": "handoff", "note": "",
        "schedule": "Sample call", "schedule_slug": "sample",
        "slot_label_host": start.astimezone().strftime("%a %d %b, %H:%M") + f" ({settings.host_timezone})",
        "slot_label_visitor": start.strftime("%a %d %b, %H:%M") + " (UTC)",
    }
    subject, body = render_brief(lead)
    print("Subject:", subject)
    print(body)
    ok = send_host_brief(lead)
    print("SENT to", settings.host_email if ok else "NOBODY (see error above)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
