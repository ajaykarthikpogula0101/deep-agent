"""Snapshot the embedded Postgres to R2 through the Worker (cloudflare/src/index.ts, /__backup/*). Stdlib only.

  backup.py restore   load latest.sql.gz into the empty database, if one exists
  backup.py loop      every BACKUP_INTERVAL seconds pg_dump, upload only when the dump changed

Env: BACKUP_URL (e.g. https://assistant.deependhq.com/__backup; unset = no snapshots), ADMIN_TOKEN, DATABASE_URL.
shortcut: the loss window on a host restart is one interval (30 s), upgrade to WAL shipping if that ever matters.
"""
import gzip
import hashlib
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("BACKUP_URL", "").rstrip("/")
DB = os.environ["DATABASE_URL"]


def _req(method: str, name: str, data: bytes | None = None):
    r = urllib.request.Request(f"{URL}/{name}", data=data, method=method,
                               headers={"X-Admin-Token": os.environ.get("ADMIN_TOKEN", ""), "Content-Type": "application/gzip",
                                        # Cloudflare Browser Integrity Check blocks Python's default user agent (1010).
                                        "User-Agent": "deependhq-assistant/0.1"})
    return urllib.request.urlopen(r, timeout=120)


def restore() -> None:
    if not URL:
        print("backup: BACKUP_URL unset, starting with an empty database", flush=True)
        return
    for attempt in range(6):  # the network may still be coming up right after boot
        try:
            body = _req("GET", "latest.sql.gz").read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print("backup: no snapshot yet, starting with an empty database", flush=True)
                return
            raise
        except urllib.error.URLError as e:
            if attempt == 5:
                raise  # never start empty over a snapshot we could not read: the loop would overwrite it
            print(f"backup: fetch failed ({e}), retrying", flush=True)
            time.sleep(5)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", DB], input=gzip.decompress(body), check=True)
    print(f"backup: restored {len(body)} bytes", flush=True)


def put() -> None:
    """Upload stdin as a named object (boot diagnostics)."""
    if URL:
        _req("PUT", sys.argv[2], sys.stdin.buffer.read())


def snapshot(last: str | None) -> str | None:
    """pg_dump once; upload when the dump changed. Returns the new digest."""
    sql = subprocess.run(["pg_dump", "--no-owner", "--no-privileges", DB], capture_output=True, check=True).stdout
    digest = hashlib.sha256(sql).hexdigest()
    if digest == last:
        return last
    gz = gzip.compress(sql, 6)
    _req("PUT", "latest.sql.gz", gz)
    _req("PUT", time.strftime("daily/%Y-%m-%d.sql.gz"), gz)  # one dated copy per day, rewritten through the day
    print(f"backup: uploaded {len(gz)} bytes", flush=True)
    return digest


def once() -> None:
    """Final snapshot on a graceful stop (the entrypoint's TERM trap)."""
    if URL:
        snapshot(None)


def loop() -> None:
    if not URL:
        return
    interval = int(os.environ.get("BACKUP_INTERVAL", "30"))
    last = None
    while True:
        time.sleep(interval)
        try:
            last = snapshot(last)
        except Exception as e:  # never let a failed snapshot take the app down
            print(f"backup: failed: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    {"restore": restore, "loop": loop, "put": put, "once": once}[sys.argv[1]]()
