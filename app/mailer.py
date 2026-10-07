"""Background email queue with retries: a booking succeeds even when SMTP is slow or down.

enqueue() returns immediately; one worker thread sends each message, retrying up to RETRIES times with backoff
(2 s, 8 s, 30 s). Every outcome is logged and kept in a small ring buffer for the console. The sender is injectable
so tests run synchronously without SMTP.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any, Callable

log = logging.getLogger("mailer")

RETRIES = 3
BACKOFF = (2, 8, 30)

Sender = Callable[..., bool]


class Mailer:
    def __init__(self, sender: Sender | None = None, sleep: Callable[[float], None] = time.sleep, sync: bool = False):
        self._sender = sender
        self._sleep = sleep
        self.sync = sync
        self._q: Queue = Queue()
        self._thread: threading.Thread | None = None
        self.results: deque = deque(maxlen=200)
        self._lock = threading.Lock()

    @property
    def sender(self) -> Sender:
        if self._sender is None:
            from app.booking.email import _send

            self._sender = _send
        return self._sender

    def enqueue(self, to: str, subject: str, body: str, *, html: str | None = None, attachments: list | None = None,
                reply_to: str | None = None, kind: str = "mail", ref: Any = None) -> None:
        job = {"to": to, "subject": subject, "body": body, "html": html, "attachments": attachments or [],
               "reply_to": reply_to, "kind": kind, "ref": ref, "queued_at": datetime.now(timezone.utc).isoformat()}
        if self.sync:
            self._deliver(job)
            return
        self._q.put(job)
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="mailer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                job = self._q.get(timeout=300)
            except Empty:
                return  # idle: let the thread end; the next enqueue restarts it
            try:
                self._deliver(job)
            finally:
                self._q.task_done()

    def _deliver(self, job: dict[str, Any]) -> bool:
        ok, err = False, ""
        for attempt in range(1, RETRIES + 1):
            try:
                ok = bool(self.sender(job["to"], job["subject"], job["body"], reply_to=job.get("reply_to"),
                                      html=job.get("html"), attachments=job.get("attachments")))
            except Exception as e:  # the sender normally returns False instead of raising
                ok, err = False, str(e)[:200]
            if ok:
                log.info("mail %s to %s sent (attempt %d): %s", job["kind"], job["to"], attempt, job["subject"])
                break
            log.warning("mail %s to %s failed (attempt %d/%d)%s", job["kind"], job["to"], attempt, RETRIES, f": {err}" if err else "")
            if attempt < RETRIES:
                self._sleep(BACKOFF[attempt - 1])
        self.results.appendleft({"kind": job["kind"], "to": job["to"], "subject": job["subject"], "ok": ok, "error": err or None,
                                 "ref": job.get("ref"), "at": datetime.now(timezone.utc).isoformat()})
        if not ok:
            log.error("mail %s to %s GAVE UP after %d attempts: %s", job["kind"], job["to"], RETRIES, job["subject"])
        return ok

    def wait(self, timeout: float = 30) -> None:
        """Tests and scripts: block until the queue is drained."""
        deadline = time.time() + timeout
        while not self._q.empty() and time.time() < deadline:
            time.sleep(0.05)

    def stats(self) -> dict[str, Any]:
        return {"pending": self._q.qsize(), "recent": list(self.results)[:20]}


default = Mailer()
enqueue = default.enqueue
