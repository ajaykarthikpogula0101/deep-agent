"""Background email queue with retries: a booking succeeds even when SMTP is slow or down.

enqueue() returns immediately; one worker thread sends each message, retrying up to RETRIES times with backoff
(2 s, 8 s, 30 s). Every outcome is logged and kept in a small ring buffer for the console. The sender is injectable
so tests run synchronously without SMTP.

Saved queue (MAIL_OUTBOX, default on for the app's own mailer): every email is written to the `outbox` table before
it is handed to the worker, and marked sent or failed afterwards. A restart or crash between the two used to lose the
email; now `recover()` (every 5 minutes, run by the scheduler leader) sends any email still 'queued' or 'sending' after
RECOVER_AFTER_MINUTES, at most RECOVER_TIMES times. Sent rows are deleted after OUTBOX_KEEP_DAYS.
"""
from __future__ import annotations

import base64
import json
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
RECOVER_AFTER_MINUTES = 10   # a worker finishes all its attempts within a minute; older 'queued' rows were orphaned
RECOVER_TIMES = 3            # never loop on an email that keeps getting stuck
OUTBOX_KEEP_DAYS = 30

Sender = Callable[..., bool]


class Mailer:
    def __init__(self, sender: Sender | None = None, sleep: Callable[[float], None] = time.sleep, sync: bool = False,
                 durable: bool | None = None):
        self._sender = sender
        self._sleep = sleep
        self.sync = sync
        self.durable = durable   # None: follow MAIL_OUTBOX (the app's default mailer); sync mailers never save
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
        if self._saving():
            job["outbox_id"] = _save(job)   # None when the database is down: the email still goes out from memory
        self._q.put(job)
        self._ensure_worker()

    def _saving(self) -> bool:
        if self.sync:
            return False
        if self.durable is not None:
            return self.durable
        from app.config import settings

        return bool(settings.mail_outbox)

    def recover(self, match: str | None = None) -> int:
        """Send again the saved emails a restart or crash left behind. Run by the scheduler leader; never raises.
        `match` (a LIKE pattern on the address) limits it to some rows; tests use it to touch only their own."""
        try:
            jobs = _claim_orphans(match=match)
        except Exception as e:
            log.warning("outbox recovery skipped: %s", e)
            return 0
        for job in jobs:
            log.warning("outbox: re-sending %s to %s (left unsent by an earlier process)", job["kind"], job["to"])
            self._q.put(job)
        if jobs:
            self._ensure_worker()
        try:
            _purge()
        except Exception as e:
            log.warning("outbox purge failed: %s", e)
        return len(jobs)

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
        oid = job.get("outbox_id")
        if oid:
            _mark(oid, "sending")
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
        if oid:
            _mark(oid, "sent" if ok else "failed", err or None)
        if not ok:
            log.error("mail %s to %s GAVE UP after %d attempts: %s", job["kind"], job["to"], RETRIES, job["subject"])
            try:  # visible in the database (events kind 'mail_failed'), not only in the server console
                from app.db import log_event

                log_event("mail_failed", None, {"kind": job["kind"], "to": job["to"], "ref": job.get("ref"), "error": err or None})
            except Exception:
                pass
        return ok

    def wait(self, timeout: float = 30) -> None:
        """Tests and scripts: block until the queue is drained."""
        deadline = time.time() + timeout
        while not self._q.empty() and time.time() < deadline:
            time.sleep(0.05)

    def stats(self) -> dict[str, Any]:
        return {"pending": self._q.qsize(), "recent": list(self.results)[:20]}


# ---------------------------------------------------------------- the outbox table
def _pack(attachments: list) -> str:
    out = []
    for a in attachments or []:
        name, data, mime = (list(a) + [None, None, None])[:3]
        if isinstance(data, (bytes, bytearray)):
            out.append({"n": name, "b64": base64.b64encode(bytes(data)).decode("ascii"), "m": mime})
        else:
            out.append({"n": name, "t": data, "m": mime})
    return json.dumps(out)


def _unpack(raw: Any) -> list:
    items = raw if isinstance(raw, list) else json.loads(raw or "[]")
    return [(a.get("n"), base64.b64decode(a["b64"]) if "b64" in a else a.get("t"), a.get("m")) for a in items]


def _save(job: dict[str, Any]) -> int | None:
    try:
        from app.db import conn

        with conn() as c:
            row = c.execute(
                """INSERT INTO outbox(kind, to_addr, subject, body, html, attachments, reply_to, ref)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id""",
                (job["kind"], job["to"], job["subject"], job["body"], job.get("html"), _pack(job.get("attachments")),
                 job.get("reply_to"), None if job.get("ref") is None else str(job["ref"]))).fetchone()
            c.commit()
        return int(row[0])
    except Exception as e:
        log.warning("outbox save failed (sending from memory only): %s", e)
        return None


def _mark(oid: int, status: str, error: str | None = None) -> None:
    try:
        from app.db import conn

        with conn() as c:
            c.execute("""UPDATE outbox SET status = %s, attempts = attempts + (CASE WHEN %s IN ('sent', 'failed') THEN 1 ELSE 0 END),
                                last_error = COALESCE(%s, last_error), updated_at = now(),
                                sent_at = CASE WHEN %s = 'sent' THEN now() ELSE sent_at END WHERE id = %s""",
                      (status, status, error, status, oid))
            c.commit()
    except Exception as e:
        log.warning("outbox update failed: %s", e)


def _claim_orphans(limit: int = 50, match: str | None = None) -> list[dict[str, Any]]:
    """Atomically take the emails nobody finished: 'queued' or 'sending' for longer than RECOVER_AFTER_MINUTES."""
    from app.db import conn

    with conn() as c:
        rows = c.execute(
            """UPDATE outbox SET status = 'sending', recovered = recovered + 1, updated_at = now()
               WHERE id IN (SELECT id FROM outbox WHERE status IN ('queued', 'sending') AND recovered < %s
                              AND updated_at < now() - make_interval(mins => %s) AND (%s::text IS NULL OR to_addr LIKE %s)
                            ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)
               RETURNING id, kind, to_addr, subject, body, html, attachments, reply_to, ref""",
            (RECOVER_TIMES, RECOVER_AFTER_MINUTES, match, match, limit)).fetchall()
        c.commit()
    return [{"outbox_id": r[0], "kind": r[1], "to": r[2], "subject": r[3], "body": r[4], "html": r[5], "attachments": _unpack(r[6]),
             "reply_to": r[7], "ref": r[8], "queued_at": datetime.now(timezone.utc).isoformat()} for r in rows]


def _purge() -> None:
    from app.db import conn

    with conn() as c:
        c.execute("DELETE FROM outbox WHERE status = 'sent' AND updated_at < now() - make_interval(days => %s)", (OUTBOX_KEEP_DAYS,))
        c.commit()


def outbox_counts() -> dict[str, int]:
    from app.db import conn

    with conn() as c:
        rows = c.execute("""SELECT status, count(*) FROM outbox WHERE updated_at > now() - interval '1 day' GROUP BY 1""").fetchall()
    return {s: int(n) for s, n in rows}


default = Mailer()
enqueue = default.enqueue
