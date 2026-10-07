"""Weekly digest: rendering is pure (no database); build/send are exercised when Postgres is up."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import digest
from app.templates import DEFAULTS

METRICS = {
    "days": 7, "conversations": 42, "questions": 97, "resolved": 70, "refused": 12, "handovers": 3, "custom": 5, "errors": 1,
    "resolution_rate": 0.814, "bookings": 5, "handover_leads": 2, "enquiries": 1,
    "csat": {"up": 23, "down": 2, "score": 0.92}, "median_latency_ms": 2140, "daily": [],
    "top_questions": [{"question": "what does lake b2b do?", "count": 9}, {"question": "who is deep?", "count": 6}],
}
PREV = {"conversations": 30, "questions": 80, "resolution_rate": 0.75}
GAPS = {"unanswered": [{"question": "what is the pricing?", "count": 3, "last": "x", "reason": "low_confidence"}],
        "thumbs_down": [{"id": 1}]}
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)
LEADS = [
    {"ts": NOW - timedelta(days=2), "name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "EU fintech data",
     "status": "handoff", "slot_start": NOW + timedelta(days=1), "schedule_slug": "discovery-call",
     "company": "Lovelace Analytical Engines (lovelace.org) · Computation", "confirmed_at": None, "nudged_at": NOW},
    {"ts": NOW - timedelta(days=3), "name": "Bob", "email": "bob@gmail.com", "reason": "", "status": "handover",
     "slot_start": None, "schedule_slug": None, "company": None, "confirmed_at": None, "nudged_at": None},
]


def test_digest_renders_numbers_trends_gaps_and_leads():
    subject, body = digest.render(METRICS, PREV, GAPS, LEADS, "29 Sep – 06 Oct 2026", DEFAULTS)
    assert subject == "[Champions Group] Weekly digest: 42 conversations, 5 bookings · 29 Sep – 06 Oct 2026"
    assert "Conversations     42   (up 12 vs the week before)" in body
    assert "Resolution rate   81%   (up 6 pts vs the week before)" in body
    assert "Satisfaction      92%   (23 up · 2 down)" in body
    assert "Bookings          5   · hand-overs 2 · enquiries 1" in body and "Median answer     2.1 s" in body
    assert "  1. what does lake b2b do?  ×9" in body and "  - what is the pricing?  ×3" in body
    assert "1 answer(s) were marked not helpful" in body
    assert "Ada Lovelace <ada@lovelace.org> · Lovelace Analytical Engines (lovelace.org) · discovery call · wanted" in body
    assert "sent to Zoom, not confirmed, reminded" in body and '"EU fintech data"' in body
    assert "Bob <bob@gmail.com> · asked for a human reply" in body
    assert body.rstrip().endswith("assistant to Deep.")


def test_digest_copes_with_an_empty_week():
    empty = dict(METRICS, conversations=0, questions=0, resolution_rate=None, csat={"up": 0, "down": 0, "score": None},
                 median_latency_ms=None, errors=0, top_questions=[], bookings=0, handover_leads=0, enquiries=0)
    subject, body = digest.render(empty, None, {"unanswered": [], "thumbs_down": []}, [], "period", DEFAULTS)
    assert "0 conversations, 0 bookings" in subject
    assert "Resolution rate   –" in body and "(nothing yet)" in body and "(none, good)" in body and "(none this week)" in body
    assert "vs the week before" not in body  # no previous week given


def test_lead_state_words():
    assert digest._lead_state({"status": "booked"}) == "booked"
    assert digest._lead_state({"status": "handoff", "confirmed_at": NOW}) == "booked"
    assert digest._lead_state({"status": "handoff"}) == "sent to Zoom, not confirmed"
    assert digest._lead_state({"status": "enquiry"}).startswith("enquiry")


def test_period_label_in_host_timezone():
    label = digest.period_label(7, NOW)
    assert label.endswith("06 Oct 2026") and label.startswith("29 Sep")


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
def test_build_and_send_with_the_database(monkeypatch):
    sent = {}
    import app.booking.email as email

    monkeypatch.setattr(email, "send_plain", lambda to, s, b: sent.update(to=to, subject=s, body=b) or True)
    d = digest.build(7)
    assert d["subject"].startswith("[") and "Weekly digest" in d["body"] and d["to"]
    r = digest.send(7, to="owner@example.com")
    assert r["ok"] and sent["to"] == "owner@example.com" and sent["subject"] == r["subject"]
