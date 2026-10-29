"""Saved email queue (app/mailer.py outbox) and the one-runner lock for scheduled jobs (app/leader.py).
Database tests use their own addresses (outbox-test-…@example.invalid) and their own lock key, and clean up."""
from __future__ import annotations

import uuid

import pytest

from app import mailer as M
from app.config import settings
from app.leader import Leader


def test_attachments_survive_the_round_trip():
    packed = M._pack([("invite.ics", "BEGIN:VCALENDAR", "text/calendar"), ("logo.png", b"\x89PNG\x00\x01", "image/png")])
    assert M._unpack(packed) == [("invite.ics", "BEGIN:VCALENDAR", "text/calendar"), ("logo.png", b"\x89PNG\x00\x01", "image/png")]
    assert M._unpack("[]") == [] and M._pack(None) == "[]"


def test_sync_and_unsaved_mailers_never_touch_the_outbox(monkeypatch):
    saved = []
    monkeypatch.setattr(M, "_save", lambda job: saved.append(job) or 1)
    monkeypatch.setattr(settings, "mail_outbox", True)
    M.Mailer(sender=lambda *a, **k: True, sync=True).enqueue("a@example.invalid", "s", "b")
    m = M.Mailer(sender=lambda *a, **k: True, durable=False)
    m.enqueue("a@example.invalid", "s", "b"); m.wait()
    assert saved == []
    monkeypatch.setattr(settings, "mail_outbox", False)
    m2 = M.Mailer(sender=lambda *a, **k: True)   # the app's mailer follows MAIL_OUTBOX
    m2.enqueue("a@example.invalid", "s", "b"); m2.wait()
    assert saved == []


def test_a_database_outage_never_stops_an_email(monkeypatch):
    sent = []
    monkeypatch.setattr(M, "_save", lambda job: None)          # the database is down: _save gives no id
    m = M.Mailer(sender=lambda to, subject, body, **k: sent.append(to) or True, durable=True)
    m.enqueue("b@example.invalid", "s", "b"); m.wait()
    import time
    for _ in range(50):
        if sent:
            break
        time.sleep(0.05)
    assert sent == ["b@example.invalid"]


# ---------------------------------------------------------------- database
def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


db = pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")


@pytest.fixture
def addr():
    tag = uuid.uuid4().hex[:10]
    yield f"outbox-test-{tag}@example.invalid"
    from app.db import conn

    with conn() as c:
        c.execute("DELETE FROM outbox WHERE to_addr LIKE %s", (f"outbox-test-{tag}%",))
        c.commit()


def _rows(to: str):
    from app.db import conn

    with conn() as c:
        return c.execute("SELECT status, attempts, recovered, last_error, sent_at IS NOT NULL FROM outbox WHERE to_addr = %s ORDER BY id",
                         (to,)).fetchall()


def _wait_for(pred, seconds=10):
    import time

    t0 = time.time()
    while time.time() - t0 < seconds:
        if pred():
            return True
        time.sleep(0.1)
    return False


@db
def test_every_email_is_saved_then_marked_sent_or_failed(addr):
    sent = []
    m = M.Mailer(sender=lambda to, subject, body, **k: sent.append((to, k.get("attachments"))) or True, durable=True)
    m.enqueue(addr, "Your call is booked", "body", attachments=[("invite.ics", "BEGIN:VCALENDAR", "text/calendar")], kind="t")
    assert _wait_for(lambda: _rows(addr) and _rows(addr)[0][0] == "sent")
    status, attempts, recovered, err, has_sent_at = _rows(addr)[0]
    assert attempts == 1 and recovered == 0 and err is None and has_sent_at and sent[0][0] == addr

    bad = addr.replace("@", "+bad@")
    f = M.Mailer(sender=lambda *a, **k: (_ for _ in ()).throw(OSError("smtp down")), sleep=lambda s: None, durable=True)
    import app.db as dbmod
    orig = dbmod.log_event
    dbmod.log_event = lambda *a, **k: None    # the give-up event never reaches the real events table
    try:
        f.enqueue(bad, "s", "b")
        assert _wait_for(lambda: _rows(bad) and _rows(bad)[0][0] == "failed")
    finally:
        dbmod.log_event = orig
    assert _rows(bad)[0][3] == "smtp down"


@db
def test_a_restart_cannot_lose_an_email(addr):
    """An email saved by a process that died before sending it is sent by the next recovery run, once."""
    from app.db import conn

    with conn() as c:   # what a crash leaves behind: saved, never sent, 20 minutes old
        c.execute("""INSERT INTO outbox(kind, to_addr, subject, body, attachments, status, updated_at)
                     VALUES ('visitor_confirmed', %s, 'Booked', 'body', %s::jsonb, 'queued', now() - interval '20 minutes')""",
                  (addr, M._pack([("invite.ics", "BEGIN:VCALENDAR", "text/calendar")])))
        c.execute("""INSERT INTO outbox(kind, to_addr, subject, body, status, updated_at)
                     VALUES ('fresh', %s, 'Just queued', 'body', 'queued', now())""", (addr.replace("@", "+fresh@"),))
        c.commit()
    sent = []
    m = M.Mailer(sender=lambda to, subject, body, **k: sent.append((to, subject, k.get("attachments"))) or True, durable=True)
    assert m.recover(match="outbox-test-%") >= 1
    assert _wait_for(lambda: _rows(addr)[0][0] == "sent")
    assert sent[0] == (addr, "Booked", [("invite.ics", "BEGIN:VCALENDAR", "text/calendar")])
    assert _rows(addr)[0][2] == 1                                   # recovered once
    assert _rows(addr.replace("@", "+fresh@"))[0][0] == "queued"     # a fresh email belongs to its own worker: left alone
    sent.clear()
    m.recover(match="outbox-test-%"); m.wait()
    assert not [s for s in sent if s[0] == addr]                    # never sent twice


# ---------------------------------------------------------------- one runner for scheduled jobs
TEST_KEY = 0x7465737401   # not the app's key: the live server's lock is never touched


@db
def test_only_one_process_holds_the_scheduler_lock():
    a, b = Leader(key=TEST_KEY), Leader(key=TEST_KEY)
    try:
        assert a.try_acquire() is True
        assert b.try_acquire() is False                 # a second process waits
        assert a.alive()
        a.stop()                                        # the leader stops: its connection closes, the lock is free
        assert b.try_acquire() is True                  # the next process takes over
    finally:
        a.stop(); b.stop()


def test_leader_runs_jobs_once_and_pauses_when_it_loses_the_lock(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_lock", True)
    events = []

    class FakeConn:
        def __init__(self, got): self.got, self.closed = got, False
        def execute(self, sql, params=None):
            if self.closed:
                raise OSError("connection closed")
            return type("R", (), {"fetchone": lambda s: (self.got,)})()
        def close(self): self.closed = True

    conns = [FakeConn(True)]
    lead = Leader(connect=lambda: conns[-1], retry_seconds=0.05)
    lead.start(on_lead=lambda: events.append("lead"), on_lose=lambda: events.append("lose"))
    assert lead.is_leader and events[0] == "lead"
    conns.append(FakeConn(False))                       # once lost, someone else holds the lock
    conns[0].closed = True                              # the database restarted under us
    import time
    for _ in range(100):
        if "lose" in events:
            break
        time.sleep(0.02)
    lead.stop()
    assert events[:2] == ["lead", "lose"] and events.count("lead") == 1   # jobs paused, not resumed by a second runner

    waiting = Leader(connect=lambda: FakeConn(False), retry_seconds=3600)
    waiting.start(on_lead=lambda: events.append("second"), on_lose=lambda: None)
    assert not waiting.is_leader and "second" not in events      # another process holds it: no jobs here
    waiting.stop()

    def down():
        raise OSError("database unreachable")
    fallback = Leader(connect=down, retry_seconds=3600)
    fallback.start(on_lead=lambda: events.append("fallback"), on_lose=lambda: None)
    assert fallback.is_leader and events[-1] == "fallback"         # cannot even ask: run the jobs as before
    fallback.stop()

    monkeypatch.setattr(settings, "scheduler_lock", False)
    off = Leader(connect=down)
    off.start(on_lead=lambda: events.append("off"), on_lose=lambda: None)
    assert off.is_leader and events[-1] == "off"
