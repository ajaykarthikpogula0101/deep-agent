"""Follow-up nudges for unconfirmed Zoom hand-offs: template + link building hermetically, the run loop with Postgres."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import nudge, templates
from app.booking.zoom import Schedule

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)
ROW = {"id": 1, "ts": NOW - timedelta(hours=30), "name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "demo",
       "slot_start": datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc), "visitor_tz": "America/New_York",
       "schedule_slug": "discovery-call", "company": None, "session_id": None}
SCHEDULES = [Schedule(slug="discovery-call", id="x", name="LakeB2B Discovery Call", duration_min=15,
                      booking_link="https://scheduler.zoom.us/sreedeep/discovery-call")]


def test_nudge_email_has_the_prefilled_link_and_both_time_labels():
    lead = nudge.lead_for_email(ROW, SCHEDULES)
    assert lead["status"] == "nudge" and lead["schedule"] == "LakeB2B Discovery Call" and lead["duration_min"] == 15
    assert lead["handoff_url"].startswith("https://scheduler.zoom.us/sreedeep/discovery-call?firstname=Ada&lastname=Lovelace&email=ada%40lovelace.org&month=2026-10")
    assert "(America/New_York)" in lead["slot_label_visitor"] and "(Asia/Kolkata)" in lead["slot_label_host"]
    r = templates.render_visitor(lead)
    assert r is not None
    subject, body = r
    assert subject == f"Still want to talk with Deep? LakeB2B Discovery Call on {lead['slot_label_visitor']}"
    assert "Confirm it here, your details are already filled in: https://scheduler.zoom.us/sreedeep/discovery-call?firstname=Ada" in body
    assert "wasn't completed" in body and body.startswith("Hi Ada,")


def test_nudge_without_live_call_types_falls_back_to_the_slug():
    lead = nudge.lead_for_email(ROW, [])
    assert lead["schedule"] == "Discovery Call" and lead["handoff_url"].startswith("https://scheduler.zoom.us/sreedeep/discovery-call?")


def test_nudge_can_be_disabled_like_the_other_visitor_emails():
    lead = nudge.lead_for_email(ROW, SCHEDULES)
    tpl = dict(templates.DEFAULTS, visitor_nudge_enabled="false")
    assert templates.render_visitor(lead, tpl) is None
    assert templates.preview("visitor_nudge")["subject"].startswith("Still want to talk with Deep?")
    assert "visitor_nudge" in templates.previews()


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_run_sends_once_and_respects_confirmations():
    from app.db import conn

    tag = f"nudge-test-{uuid.uuid4()}"
    sent: list[dict] = []
    ids = []
    try:
        with conn() as c:
            for email, hours, confirmed in ((f"{tag}-a@lovelace.org", 30, False), (f"{tag}-b@lovelace.org", 30, True), (f"{tag}-c@lovelace.org", 2, False)):
                row = c.execute(
                    """INSERT INTO leads(ts, name, email, reason, slot_start, visitor_tz, status, schedule_slug, confirmed_at)
                       VALUES (now() - make_interval(hours => %s), 'Ada', %s, 'demo', now() + interval '3 days', 'UTC', 'handoff', 'discovery-call',
                               CASE WHEN %s THEN now() ELSE NULL END) RETURNING id""", (hours, email, confirmed)).fetchone()
                ids.append(int(row[0]))
            c.commit()
        r = nudge.run(send=lambda lead: sent.append(lead) or True, after_hours=24, since_iso="2000-01-01T00:00:00+00:00")
        mine = [l for l in sent if str(l["email"]).startswith(tag)]
        assert len(mine) == 1 and mine[0]["email"] == f"{tag}-a@lovelace.org"  # b is confirmed, c is too fresh
        assert r["sent"] >= 1
        r2 = nudge.run(send=lambda lead: sent.append(lead) or True, after_hours=24, since_iso="2000-01-01T00:00:00+00:00")
        assert nudge.run(send=lambda lead: sent.append(lead) or True, after_hours=24)["sent"] == 0  # default: nothing older than go-live
        assert not [l for l in sent[len(sent) - r2["sent"]:] if str(l["email"]).startswith(tag)]  # never twice
        with conn() as c:
            flags = c.execute("SELECT nudged_at IS NOT NULL FROM leads WHERE id = %s", (ids[0],)).fetchone()
        assert flags[0] is True
        assert nudge.confirm(ids[2]) is True and nudge.confirm(ids[2]) is False
    finally:
        with conn() as c:
            c.execute("DELETE FROM leads WHERE email LIKE %s", (tag + "%",))
            c.execute("DELETE FROM events WHERE kind IN ('nudge', 'lead_confirmed') AND detail->>'lead_id' = ANY(%s)", ([str(i) for i in ids],))
            c.commit()
