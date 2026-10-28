"""Nightly database backups outside Docker: a Docker Desktop reset can no longer wipe the data.

On 2026-10-28 Docker Desktop's storage was recreated and the Postgres volume, with every booking, lead, conversation
and console setting, went with it. Now a `pg_dump` (custom format, compressed) is written every night at BACKUP_CRON
(03:50 host time) into BACKUP_DIR, a folder on the host such as D:\\Backups\\deependhq-db, and the newest BACKUP_KEEP
files are kept. The app also takes one at start-up when the newest is older than a day.

How the dump is taken:
  * the database runs in the compose container BACKUP_DOCKER_CONTAINER (the local set-up): `docker exec … pg_dump`;
  * otherwise a `pg_dump` on PATH, against DATABASE_URL.

Restore (replaces what is in the database with the backup; run it yourself):
    python -m app.backup restore D:\\Backups\\deependhq-db\\deependhq-2026-10-29-0350.dump
List: `python -m app.backup list`. Take one now: `python -m app.backup now`.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings

log = logging.getLogger("backup")

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "deependhq-"
SUFFIX = ".dump"


def backup_dir() -> Path:
    d = Path(settings.backup_dir) if settings.backup_dir else ROOT / "backups"
    return d if d.is_absolute() else ROOT / d


def _db() -> dict:
    u = urlparse(settings.database_url)
    return {"user": u.username or "assistant", "db": (u.path or "/assistant").lstrip("/") or "assistant"}


def _container_running(run=subprocess.run) -> bool:
    name = settings.backup_docker_container
    if not name or not shutil.which("docker"):
        return False
    try:
        r = run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def dump_command(run=subprocess.run) -> list[str] | None:
    """The pg_dump command for this set-up, or None when there is no way to take one."""
    db = _db()
    if _container_running(run):
        return ["docker", "exec", settings.backup_docker_container, "pg_dump", "-U", db["user"], "-d", db["db"], "-Fc"]
    if shutil.which("pg_dump"):
        return ["pg_dump", "-Fc", "-d", settings.database_url]
    return None


def backups() -> list[Path]:
    """Existing backups, newest first."""
    d = backup_dir()
    return sorted(d.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name, reverse=True) if d.is_dir() else []


def age_hours(now: datetime | None = None) -> float | None:
    """Hours since the newest backup was written, or None when there is none."""
    files = backups()
    if not files:
        return None
    written = datetime.fromtimestamp(files[0].stat().st_mtime, timezone.utc)
    return ((now or datetime.now(timezone.utc)) - written).total_seconds() / 3600


def take(run=subprocess.run, now: datetime | None = None) -> dict:
    """One backup, then prune to BACKUP_KEEP. Never raises: {"ok", "file", "bytes", "kept", "error"}."""
    cmd = dump_command(run)
    if not cmd:
        msg = "no way to back up: neither the Docker container nor pg_dump is available"
        log.warning(msg)
        return {"ok": False, "error": msg}
    d = backup_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"cannot create {d}: {e}"}
    stamp = (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m-%d-%H%M%S")
    final, part = d / f"{PREFIX}{stamp}{SUFFIX}", d / f"{PREFIX}{stamp}{SUFFIX}.part"
    try:
        with open(part, "wb") as fh:
            r = run(cmd, stdout=fh, stderr=subprocess.PIPE, timeout=settings.backup_timeout)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or b"").decode("utf-8", "replace").strip()[:300] or f"pg_dump exit {r.returncode}")
        size = part.stat().st_size
        if size < 1024:   # a valid custom-format dump of this schema is never this small
            raise RuntimeError(f"dump is only {size} bytes")
        part.replace(final)
    except Exception as e:
        part.unlink(missing_ok=True)
        log.error("backup failed: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    kept = prune()
    log.info("backup written: %s (%d bytes), %d kept", final, size, len(kept))
    return {"ok": True, "file": str(final), "bytes": size, "kept": len(kept)}


def prune() -> list[Path]:
    files = backups()
    for old in files[settings.backup_keep:]:
        try:
            old.unlink()
        except OSError as e:
            log.warning("could not remove old backup %s: %s", old, e)
    return files[: settings.backup_keep]


def run() -> dict:
    """The nightly job."""
    return take()


def take_if_stale_async(hours: float = 24) -> None:
    """At start-up: a backup in the background when the newest one is older than `hours` (or there is none)."""
    def _go():
        a = age_hours()
        if a is None or a >= hours:
            take()
    threading.Thread(target=_go, name="backup-startup", daemon=True).start()


def restore(path: str, run=subprocess.run) -> int:
    """Replace the database contents with a backup (pg_restore --clean). Command-line only."""
    src = Path(path)
    if not src.is_file():
        print(f"no such file: {src}")
        return 2
    db = _db()
    if _container_running(run):
        cmd = ["docker", "exec", "-i", settings.backup_docker_container, "pg_restore", "-U", db["user"], "-d", db["db"],
               "--clean", "--if-exists", "--no-owner"]
    elif shutil.which("pg_restore"):
        cmd = ["pg_restore", "--clean", "--if-exists", "--no-owner", "-d", settings.database_url]
    else:
        print("neither the Docker container nor pg_restore is available")
        return 2
    with open(src, "rb") as fh:
        r = run(cmd, stdin=fh, stderr=subprocess.PIPE)
    err = (r.stderr or b"").decode("utf-8", "replace").strip()
    print(f"restored {src.name}" + (f" (pg_restore notes: {err[:500]})" if err else ""))
    return 0 if r.returncode in (0, 1) else r.returncode   # 1 = warnings only (e.g. objects that did not exist yet)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "now"
    if cmd == "now":
        r = take()
        print(r)
        return 0 if r.get("ok") else 1
    if cmd == "list":
        for p in backups():
            print(f"{p}  {p.stat().st_size / 1e6:.1f} MB")
        return 0
    if cmd == "restore" and len(argv) > 2:
        return restore(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
