"""History → "Your bookings": an upcoming call is never hidden behind older, moved or cancelled bookings dated later."""
from __future__ import annotations

import uuid

import pytest

from app import store_bookings


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture
def visitor():
    if not _db_up():
        pytest.skip("Postgres not reachable")
    from app import tracking
    from app.db import conn

    sid, vid = f"test-bkord-{uuid.uuid4().hex[:16]}", f"test-vid-{uuid.uuid4().hex[:12]}"
    tracking.ensure_session(sid, visitor_id=vid, ip="127.0.0.1", user_agent="pytest")
    yield sid, vid
    with conn() as c:
        c.execute("DELETE FROM bookings WHERE session_id = %s", (sid,))
        c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        c.commit()


def test_the_upcoming_call_comes_first_even_behind_25_later_cancelled_ones(visitor):
    from app.db import conn

    sid, vid = visitor
    with conn() as c:
        for i in range(25):    # moved and then cancelled, dated later than the real call
            c.execute("""INSERT INTO bookings(session_id, name, email, schedule_slug, schedule_name, duration_min, start_utc, end_utc,
                                              visitor_tz, method, status, manage_token)
                         VALUES (%s, 'Ada', 'ajaykarthik.ldn+bk@gmail.com', 'discovery-call', 'LakeB2B Discovery Call', 15,
                                 now() + make_interval(days => %s), now() + make_interval(days => %s) + interval '15 minutes',
                                 'Asia/Calcutta', 'handoff', 'cancelled', 'tok')""", (sid, 8 + i, 8 + i))
        c.execute("""INSERT INTO bookings(session_id, name, email, schedule_slug, schedule_name, duration_min, start_utc, end_utc,
                                          visitor_tz, method, status, manage_token)
                     VALUES (%s, 'Ada', 'ajaykarthik.ldn+bk@gmail.com', 'discovery-call', 'LakeB2B Discovery Call', 15,
                             now() + interval '2 days', now() + interval '2 days 15 minutes', 'Asia/Calcutta', 'handoff', 'confirmed', 'tok')""", (sid,))
        c.execute("""INSERT INTO bookings(session_id, name, email, schedule_slug, schedule_name, duration_min, start_utc, end_utc,
                                          visitor_tz, method, status, manage_token)
                     VALUES (%s, 'Ada', 'ajaykarthik.ldn+bk@gmail.com', 'discovery-call', 'LakeB2B Discovery Call', 15,
                             now() - interval '3 days', now() - interval '3 days' + interval '15 minutes', 'Asia/Calcutta', 'handoff', 'confirmed', 'tok')""", (sid,))
        c.commit()
    items = store_bookings.list_for_visitor(vid)
    assert len(items) == 20
    assert items[0]["status"] == "confirmed" and items[0]["start_utc"] < items[1]["start_utc"]   # the upcoming call, though dated earlier
    assert [b["status"] for b in items[1:]] == ["cancelled"] * 19          # then the rest, newest start first
    starts = [b["start_utc"] for b in items[1:]]
    assert starts == sorted(starts, reverse=True)
