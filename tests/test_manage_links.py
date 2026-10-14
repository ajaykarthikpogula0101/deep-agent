"""The visitor's manage links (/booking/{id}/manage, /ics, /cancel) against Postgres. A second _booking_or_404 in
app/main.py once shadowed the token-checked one and every one of these returned 500. Cancel now takes two steps: the
link opens "Cancel this booking?" and only its button POSTs. TestClient(app) without `with`, so startup never runs."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from tests.test_reminders import _db_up


def _client():
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app), main


def _insert(sid: str, **over) -> int:
    from app import store_bookings

    start = datetime(2020, 1, 6, 10, 0, tzinfo=timezone.utc)  # long past: never blocks a real slot
    b = {"session_id": sid, "name": "Ada Test", "email": "ada@example.test", "schedule_slug": "discovery-call",
         "schedule_name": "Data & <AI> Call", "duration_min": 30, "start_utc": start, "end_utc": start + timedelta(minutes=30),
         "visitor_tz": "Asia/Kolkata", "method": "handoff", "status": "confirmed", "manage_token": "t" + sid}
    b.update(over)
    return store_bookings.insert(b)


def _cleanup(sid: str, *ids: int) -> None:
    from app.db import conn

    with conn() as c:
        for bid in ids:
            c.execute("DELETE FROM bookings WHERE id = %s", (bid,))
        for t in ("bookings", "messages", "events", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
        c.commit()


def _messages(sid: str) -> int:
    from app.db import conn

    with conn() as c:
        return int(c.execute("SELECT count(*) FROM messages WHERE session_id = %s", (sid,)).fetchone()[0])


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_manage_ics_and_two_step_cancel(monkeypatch):
    from app import store_bookings

    client, main = _client()
    sid = f"test-{uuid.uuid4()}"
    tok = "t" + sid
    bid = None
    try:
        bid = _insert(sid)
        r = client.get(f"/booking/{bid}/manage", params={"t": tok})
        assert r.status_code == 200
        assert "Data &amp; &lt;AI&gt; Call" in r.text and "<AI>" not in r.text
        assert f"/booking/{bid}/cancel?t=" in r.text and "<form method='post'" not in r.text
        assert "no-store" in r.headers["cache-control"] and r.headers["x-frame-options"] == "DENY"
        assert f"/booking/{bid}/ics?t=" in r.text and "href='None'" not in r.text
        assert client.get(f"/booking/{bid}/manage", params={"t": "bad"}).status_code == 404
        assert client.get(f"/booking/{bid}/manage", params={"t": "é"}).status_code == 404       # not a 500
        assert client.get(f"/booking/{bid}/manage", params={"t": tok + "x" * 200}).status_code == 404

        r = client.get(f"/booking/{bid}/ics", params={"t": tok})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
        assert "BEGIN:VCALENDAR" in r.text and f"UID:booking-{bid}@" in r.text
        assert client.get(f"/booking/{bid}/ics", params={"t": "é"}).status_code == 404

        r = client.get(f"/booking/{bid}/cancel", params={"t": tok})   # a mail scanner or a mis-tap: nothing happens
        assert r.status_code == 200 and "Cancel this booking?" in r.text
        assert f"<form method='post' action='/booking/{bid}/cancel?t=" in r.text and "Keep it" in r.text
        assert store_bookings.get(bid)["status"] == "confirmed"
        assert client.get(f"/booking/{bid}/cancel", params={"t": "é"}).status_code == 404

        calls = []
        monkeypatch.setattr(main.flow, "cancel", lambda b, service=None: calls.append(b["id"]) or {"ok": True})
        r = client.post(f"/booking/{bid}/cancel", params={"t": tok})
        assert r.status_code == 200 and "Booking cancelled" in r.text and calls == [bid]
        n = _messages(sid)
        assert n == 1
        monkeypatch.setattr(main.flow, "cancel", lambda b, service=None: calls.append(b["id"]) or {"ok": True, "already": True})
        r = client.post(f"/booking/{bid}/cancel", params={"t": tok})
        assert r.status_code == 200 and "already cancelled" in r.text and _messages(sid) == n   # no second system row

        monkeypatch.setattr(settings, "admin_token", "x")
        r = client.post(f"/admin/bookings/{bid}/followup/draft", headers={"X-Admin-Token": "x"})
        assert r.status_code == 400                                  # unrated: the admin helper works too
        assert client.post("/admin/bookings/999999999/followup/draft", headers={"X-Admin-Token": "x"}).status_code == 404
        assert client.get(f"/outcome/{bid}", params={"t": "é"}).status_code == 404
    finally:
        _cleanup(sid, *([bid] if bid else []))
