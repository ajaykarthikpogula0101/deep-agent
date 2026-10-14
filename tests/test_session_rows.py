"""Every chat and booking has a sessions row: /booking/confirm and /chat create it (with the beacon fields while the
widget is untracked) before anything reads it. TestClient(app) without `with`, so startup (and its backfill) never runs."""
from __future__ import annotations

import uuid

import pytest

from app import tracking


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


HEADERS = {"Origin": "http://localhost"}


def _client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    monkeypatch.setattr(main.limiter, "allow", lambda key: True)
    return TestClient(main.app), main


def _session(sid):
    from app.db import conn

    with conn() as c:
        r = c.execute("SELECT visitor_id, page, referrer, messages, client_tz FROM sessions WHERE session_id = %s", (sid,)).fetchone()
    return dict(zip(["visitor_id", "page", "referrer", "messages", "client_tz"], r)) if r else None


def _cleanup(*sids):
    from app.db import conn

    with conn() as c:
        for t in ("messages", "events", "sessions"):
            c.execute(f"DELETE FROM {t} WHERE session_id = ANY(%s)", (list(sids),))
        c.commit()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_booking_confirm_creates_the_session_row_before_the_flow_reads_it(monkeypatch):
    from app.booking import flow
    from app.db import conn

    client, _ = _client(monkeypatch)
    sid, vid = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}"
    seen = {}

    def fake_confirm(service, req):
        seen.update(_session(req.session_id) or {})
        return {"status": "confirmed", "booking": {"schedule_name": "Discovery Call", "label_visitor": "Tue 06 Oct, 10:00",
                                                    "schedule_slug": "discovery-call", "start_iso": "2026-10-06T10:00:00+05:30"}}

    monkeypatch.setattr(flow, "confirm", fake_confirm)
    try:
        r = client.post("/booking/confirm", headers={**HEADERS, "X-Session-Id": sid, "X-Visitor-Id": vid},
                        json={"schedule_slug": "discovery-call", "start": "2026-10-06T10:00:00+05:30", "name": "Ada Lovelace",
                              "email": "ada@example.test", "timezone": "Asia/Kolkata",
                              "beacon": {"page": "https://deependhq.com/contact", "referrer": None, "lang": "en", "screen": "1440x900"}})
        assert r.status_code == 200 and r.json()["status"] == "confirmed"
        assert seen["visitor_id"] == vid and seen["page"] == "https://deependhq.com/contact"
        assert seen["client_tz"] == "Asia/Kolkata"  # trusted because a beacon came with it
        with conn() as c:
            text, = c.execute("SELECT text FROM messages WHERE session_id = %s", (sid,)).fetchone()
            orphans, = c.execute("""SELECT count(*) FROM (SELECT DISTINCT session_id FROM messages WHERE session_id = %s) m
                                    LEFT JOIN sessions s USING (session_id) WHERE s.session_id IS NULL""", (sid,)).fetchone()
        assert text.startswith("Booking confirmed: Discovery Call") and orphans == 0
    finally:
        _cleanup(sid)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_chat_creates_one_row_and_keeps_first_beacon(monkeypatch):
    from app.chat import sse
    from app.db import conn

    client, main = _client(monkeypatch)

    def fake_respond(*a, **k):
        yield sse({"type": "done"})

    monkeypatch.setattr(main, "respond", fake_respond)
    sid, vid = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}"
    with conn() as c:
        s1_before = c.execute("SELECT count(*) FROM sessions WHERE session_id = 's1'").fetchone()[0]
    try:
        r = client.post("/chat", headers={**HEADERS, "X-Session-Id": sid, "X-Visitor-Id": vid},
                        json={"message": "hi", "timezone": "Europe/London",
                              "beacon": {"page": "https://deependhq.com/pricing", "referrer": "https://www.google.com/"}})
        assert r.status_code == 200 and r.headers["x-session-id"] == sid
        s = _session(sid)
        assert (s["messages"], s["visitor_id"], s["page"], s["client_tz"]) == (1, vid, "https://deependhq.com/pricing", "Europe/London")
        r = client.post("/chat", headers={**HEADERS, "X-Session-Id": sid, "X-Visitor-Id": vid},
                        json={"message": "again", "beacon": {"page": "https://deependhq.com/other"}})
        assert r.status_code == 200
        r = client.post("/chat", headers={**HEADERS, "X-Session-Id": sid}, json={"message": "no beacon"})
        s = _session(sid)
        assert (s["messages"], s["page"]) == (3, "https://deependhq.com/pricing")  # first values win
        r = client.post("/chat", headers={**HEADERS, "X-Session-Id": "s1"}, json={"message": "api caller"})
        assert r.status_code == 200 and r.headers["x-session-id"] == "s1"  # never rewritten
        with conn() as c:
            assert c.execute("SELECT count(*) FROM sessions WHERE session_id = 's1'").fetchone()[0] == s1_before
    finally:
        _cleanup(sid)


LONG = "https://deependhq.com/?q=" + "a" * 2100   # a long tracking or redirect URL


def test_long_page_context_is_clipped_never_rejected():
    from app import main

    beacon = {"page": LONG, "referrer": LONG, "lang": "en-US-u-ca-gregory-nu-latn", "screen": "1440x900"}
    c = main.ChatIn(message="hi", beacon=beacon)
    assert len(c.beacon.page) == 2000 and c.beacon.page == LONG[:2000] and len(c.beacon.referrer) == 2000 and len(c.beacon.lang) == 16
    b = main.ConfirmIn(schedule_slug="discovery-call", start="2026-10-06T10:00:00+05:30", name="Ada", email="ada@example.test", beacon=beacon)
    assert len(b.beacon.page) == 2000
    t = main.TrackIn(session_id=f"test-{uuid.uuid4()}", **beacon)
    assert len(t.page) == 2000 and len(t.referrer) == 2000
    o = main.OutreachCheckIn(page=LONG, first_page=LONG, referrer=LONG, path="/" + "p" * 600, title="T" * 300)
    assert (len(o.page), len(o.first_page), len(o.referrer), len(o.path), len(o.title)) == (2000, 2000, 2000, 500, 200)
    assert len(main.OutreachTryIn(path="/" + "p" * 600, referrer=LONG).path) == 500
    assert main.BeaconIn().page is None and main.BeaconIn(page="https://deependhq.com/").page == "https://deependhq.com/"


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_chat_track_and_booking_accept_a_long_landing_url(monkeypatch):
    from app.booking import flow
    from app.chat import sse

    client, main = _client(monkeypatch)

    def fake_respond(*a, **k):
        yield sse({"type": "done"})

    monkeypatch.setattr(main, "respond", fake_respond)
    monkeypatch.setattr(flow, "confirm", lambda service, req: {"status": "invalid", "message": "stubbed"})
    s1, s2, s3 = (f"test-{uuid.uuid4()}" for _ in range(3))
    beacon = {"page": LONG, "referrer": LONG}
    try:
        r = client.post("/chat", headers={**HEADERS, "X-Session-Id": s1}, json={"message": "hi", "beacon": beacon})
        assert r.status_code == 200 and _session(s1)["page"] == LONG[:500]
        r = client.post("/track", headers=HEADERS, json={"session_id": s2, **beacon})
        assert r.status_code == 200 and r.json()["ok"]
        r = client.post("/booking/confirm", headers={**HEADERS, "X-Session-Id": s3},
                        json={"schedule_slug": "discovery-call", "start": "2026-10-06T10:00:00+05:30", "name": "Ada Lovelace",
                              "email": "ada@example.test", "beacon": beacon})
        assert r.status_code == 200 and r.json()["status"] == "invalid"
    finally:
        _cleanup(s1, s2, s3)
