"""One runner for the scheduled jobs, however many copies of the app run.

Reminders, nudges, digests, backups and the rest run inside the web process (APScheduler). With two workers or two
servers every email would go out twice. So the scheduler starts paused and only the process holding a Postgres
advisory lock runs it:

  * at start-up each process tries `pg_try_advisory_lock(LOCK_KEY)` on its own dedicated connection (not the pool);
    the winner resumes the scheduler and keeps that connection open: the lock lives exactly as long as it does;
  * the others retry every RETRY_SECONDS; when the leader stops or crashes its connection closes, the lock is freed
    and the next process to try takes over;
  * the leader checks its connection every RETRY_SECONDS; if it was lost (database restart) it pauses the scheduler
    and competes again, so two runners never overlap.

SCHEDULER_LOCK=false (or a database that cannot be reached for the lock) runs the jobs as before, in this process.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from app.config import settings

log = logging.getLogger("leader")

LOCK_KEY = 0x6465657061_01   # "deepa" + 1: this app's scheduler
RETRY_SECONDS = 60


class Leader:
    def __init__(self, connect: Callable | None = None, retry_seconds: float = RETRY_SECONDS, key: int = LOCK_KEY):
        self._connect = connect
        self.key = key
        self._retry = retry_seconds
        self._conn = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.is_leader = False

    def _open(self):
        if self._connect:
            return self._connect()
        import psycopg

        return psycopg.connect(settings.database_url, autocommit=True, connect_timeout=10,
                               application_name="deependhq-scheduler-lock")

    def try_acquire(self) -> bool:
        """True when this process now holds the lock (keeps the connection open)."""
        c = self._open()
        try:
            got = bool(c.execute("SELECT pg_try_advisory_lock(%s)", (self.key,)).fetchone()[0])
        except Exception:
            c.close()
            raise
        if got:
            self._conn = c
        else:
            c.close()
        return got

    def alive(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            return False

    def start(self, on_lead: Callable[[], None], on_lose: Callable[[], None]) -> None:
        """Compete for the lock now and keep competing (or guarding it) in the background. Never raises."""
        if not settings.scheduler_lock:
            self.is_leader = True
            on_lead()
            return

        def step() -> None:
            if self.is_leader:
                if not self.alive():
                    log.warning("scheduler lock lost (database connection closed): pausing the jobs")
                    self.is_leader = False
                    on_lose()
                return
            try:
                if self.try_acquire():
                    self.is_leader = True
                    log.info("this process runs the scheduled jobs (scheduler lock acquired)")
                    on_lead()
            except Exception as e:
                if self._thread is None:   # first attempt and the database cannot even be asked: behave as before
                    log.warning("scheduler lock unavailable (%s): running the jobs in this process", e)
                    self.is_leader = True
                    on_lead()
                else:
                    log.warning("scheduler lock check failed: %s", e)

        step()
        if self._stop.is_set():
            return

        def loop() -> None:
            while not self._stop.wait(self._retry):
                step()

        self._thread = threading.Thread(target=loop, name="scheduler-lock", daemon=True)
        self._thread.start()
        if not self.is_leader:
            log.info("another process runs the scheduled jobs; this one waits (retry every %ss)", int(self._retry))

    def stop(self) -> None:
        self._stop.set()
        if self._conn is not None:
            try:
                self._conn.close()   # frees the lock for the next process
            except Exception:
                pass
            self._conn = None
        self.is_leader = False
