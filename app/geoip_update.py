"""MaxMind GeoLite2 downloads for the local 'mmdb' geo provider (app/tracking.py). Nothing here runs without
MAXMIND_LICENSE_KEY.

python -m app.geoip_update [--force]   GeoLite2-City and GeoLite2-ASN into settings.mmdb_dir (data/geoip by default)

Per edition: skipped while the file is younger than MAX_AGE_DAYS (unless forced); otherwise the .sha256 companion and the
tar.gz are fetched (with MAXMIND_ACCOUNT_ID: basic auth on /geoip/databases/..., redirects followed; key only: the legacy
/app/geoip_download URL), the digest is checked, the one <edition>.mmdb member is copied out (regular file only, no
absolute or '..' path, size capped) into a temp file next to the target, the copy must open as that edition, and it is
swapped in with os.replace while tracking's readers are closed, so the next lookup opens the new file.

The licence key never reaches a log line: our messages pass through redact(), and a filter on the httpx logger
rewrites its 'HTTP Request: GET <url>' lines (the legacy URL carries the key).

Startup (app/main.py) runs update() on a background thread when a file is missing or stale; the weekly job keeps the
files inside the GeoLite2 EULA's 30-day limit. MaxMind publishes new builds on Tuesdays and Fridays.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("geoip_update")

EDITIONS = ("GeoLite2-City", "GeoLite2-ASN")
BASE_URL = "https://download.maxmind.com"
MAX_AGE_DAYS = 6                      # younger files are kept; the weekly job then refreshes once a week
MAX_DOWNLOAD = 200 * 1024 * 1024      # GeoLite2-City.tar.gz is ~35 MB
MAX_MEMBER = 400 * 1024 * 1024        # GeoLite2-City.mmdb is ~60 MB
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_busy = threading.Lock()              # one update at a time (startup thread, weekly job, CLI)
_KEY_RE = re.compile(r"(license_key=)[^&\s\"']+", re.I)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(Exception):
    """A failed edition; the message says what to do. stop=True (credentials, download limit): skip the other edition."""

    def __init__(self, msg: str, stop: bool = False):
        super().__init__(msg)
        self.stop = stop


def configured() -> bool:
    return bool(settings.maxmind_license_key)


def redact(text: Any) -> str:
    """The text with the licence key (and any license_key= value) replaced by ***."""
    s = str(text)
    key = settings.maxmind_license_key
    if key:
        s = s.replace(key, "***")
    return _KEY_RE.sub(r"\1***", s)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def _install_filter() -> None:
    for name in ("httpx", "httpcore"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _RedactFilter) for f in lg.filters):
            lg.addFilter(_RedactFilter())


_install_filter()


# ---------------------------------------------------------------- files
def data_dir() -> Path:
    return Path(settings.mmdb_dir or "data/geoip")


def target(edition: str) -> Path:
    return data_dir() / f"{edition}.mmdb"


def age_days(path: Path) -> float | None:
    """Days since the file was written, None when it is missing."""
    try:
        return (time.time() - path.stat().st_mtime) / 86400
    except OSError:
        return None


def needs_update(max_age_days: float = MAX_AGE_DAYS) -> bool:
    """True when a key is set and a file is missing or older than max_age_days."""
    if not configured():
        return False
    ages = [age_days(target(e)) for e in EDITIONS]
    return any(a is None or a >= max_age_days for a in ages)


# ---------------------------------------------------------------- HTTP
def _request(edition: str, suffix: str) -> tuple[str, dict[str, str], tuple[str, str] | None]:
    """(url, params, basic auth) for one file. Only the legacy form puts the key in the URL."""
    key, account = settings.maxmind_license_key, settings.maxmind_account_id.strip()
    if account:
        return f"{BASE_URL}/geoip/databases/{edition}/download", {"suffix": suffix}, (account, key)
    return f"{BASE_URL}/app/geoip_download", {"edition_id": edition, "license_key": key, "suffix": suffix}, None


def _check_status(r: httpx.Response, edition: str) -> None:
    if r.status_code in (401, 403):
        hint = ("check MAXMIND_ACCOUNT_ID and MAXMIND_LICENSE_KEY, and that the key may download GeoLite2"
                if settings.maxmind_account_id else
                "check MAXMIND_LICENSE_KEY; also set MAXMIND_ACCOUNT_ID (the number on your MaxMind account page)")
        raise UpdateError(f"{edition}: MaxMind refused the credentials (HTTP {r.status_code}); {hint}", stop=True)
    if r.status_code == 429:
        raise UpdateError(f"{edition}: MaxMind's daily download limit is reached (HTTP 429); the next run tries again",
                          stop=True)
    if r.status_code >= 400:
        raise UpdateError(f"{edition}: download failed (HTTP {r.status_code})")


def _expected_sha(client: httpx.Client, edition: str) -> str:
    url, params, auth = _request(edition, "tar.gz.sha256")
    r = client.get(url, params=params, auth=auth)
    _check_status(r, edition)
    digest = (r.text.split() or [""])[0].lower()
    if not _SHA_RE.match(digest):
        raise UpdateError(f"{edition}: the .sha256 file is not a SHA-256 digest")
    return digest


def _download(client: httpx.Client, edition: str, dest: Path) -> str:
    """Stream the tar.gz into dest (size capped); returns its SHA-256."""
    url, params, auth = _request(edition, "tar.gz")
    h, n = hashlib.sha256(), 0
    with client.stream("GET", url, params=params, auth=auth) as r:
        _check_status(r, edition)
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                n += len(chunk)
                if n > MAX_DOWNLOAD:
                    raise UpdateError(f"{edition}: download larger than {MAX_DOWNLOAD // 2**20} MB; refused")
                h.update(chunk)
                f.write(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- archive
def _safe_name(name: str) -> bool:
    p = PurePosixPath(name)
    return bool(name) and "\\" not in name and not p.is_absolute() and ".." not in p.parts and ":" not in name


def extract_mmdb(archive: Path, edition: str, out: Path) -> int:
    """Copy the archive's single <edition>.mmdb member to `out`; returns its size. Nothing else is extracted, and an
    archive whose member is a link, sits on an unsafe path, appears twice or exceeds MAX_MEMBER is refused."""
    want = f"{edition}.mmdb"
    with tarfile.open(archive, "r:gz") as tf:
        found = [m for m in tf if PurePosixPath(m.name.replace("\\", "/")).name == want]
        if len(found) != 1:
            raise UpdateError(f"{edition}: the archive has {len(found)} {want} members, expected 1")
        m = found[0]
        if not m.isreg():
            raise UpdateError(f"{edition}: {want} in the archive is not a regular file; refused")
        if not _safe_name(m.name):
            raise UpdateError(f"{edition}: unsafe path in the archive ({m.name[:80]!r}); refused")
        if m.size > MAX_MEMBER:
            raise UpdateError(f"{edition}: {want} is larger than {MAX_MEMBER // 2**20} MB; refused")
        src = tf.extractfile(m)
        if src is None:
            raise UpdateError(f"{edition}: {want} could not be read")
        n = 0
        with src, open(out, "wb") as f:
            while chunk := src.read(1 << 16):
                n += len(chunk)
                if n > MAX_MEMBER:
                    raise UpdateError(f"{edition}: {want} is larger than {MAX_MEMBER // 2**20} MB; refused")
                f.write(chunk)
    return n


def _validate(path: Path, edition: str) -> str:
    """The build date of a file that opens as `edition` ('' without maxminddb); UpdateError otherwise."""
    try:
        import maxminddb  # type: ignore[import-not-found]
    except ImportError:
        return ""
    try:
        reader = maxminddb.open_database(str(path), maxminddb.MODE_FILE)
        try:
            meta = reader.metadata()
        finally:
            reader.close()
    except Exception as e:
        raise UpdateError(f"{edition}: the downloaded file does not open ({redact(e)[:120]})")
    if meta.database_type != edition:
        raise UpdateError(f"{edition}: the downloaded file is {meta.database_type!r}")
    return time.strftime("%Y-%m-%d", time.gmtime(meta.build_epoch))


def _fetch(client: httpx.Client, edition: str, d: Path) -> tuple[Path, str]:
    """Download, verify and extract one edition into a temp .mmdb next to the target: (temp path, build date)."""
    expected = _expected_sha(client, edition)
    fd, archive = tempfile.mkstemp(prefix=f".{edition}-", suffix=".tar.gz", dir=d)
    os.close(fd)
    fd, tmp = tempfile.mkstemp(prefix=f".{edition}-", suffix=".mmdb.part", dir=d)
    os.close(fd)
    try:
        got = _download(client, edition, Path(archive))
        if got != expected:
            raise UpdateError(f"{edition}: checksum mismatch (got {got[:12]}..., expected {expected[:12]}...); file discarded")
        extract_mmdb(Path(archive), edition, Path(tmp))
        build = _validate(Path(tmp), edition)
        return Path(tmp), build
    except BaseException:
        _unlink(tmp)
        raise
    finally:
        _unlink(archive)


def _unlink(path: str | Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------- entry points
def update(force: bool = False) -> dict[str, str]:
    """Bring both editions up to date: {edition: 'updated <build date>' | 'fresh (<n> days old)' | 'error: ...'}, or
    {'*': ...} when nothing could run. Never raises; every line it logs is redacted."""
    if not configured():
        return {"*": "skipped: MAXMIND_LICENSE_KEY is not set"}
    if not _busy.acquire(blocking=False):
        return {"*": "skipped: another update is running"}
    try:
        return _update(force)
    finally:
        _busy.release()


def _update(force: bool) -> dict[str, str]:
    from app import tracking  # lazy: tracking imports the database layer

    d = data_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("GeoLite2: cannot create %s: %s", d, e)
        return {"*": f"error: cannot create {d}"}
    for stale in d.glob(".GeoLite2-*"):  # temp files of a run that was killed half way
        if (age_days(stale) or 0) > 1 / 24:
            _unlink(stale)
    out: dict[str, str] = {}
    ready: list[tuple[str, Path, str]] = []
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": settings.crawl_user_agent}) as client:
        for edition in EDITIONS:
            age = age_days(target(edition))
            if not force and age is not None and age < MAX_AGE_DAYS:
                out[edition] = f"fresh ({age:.1f} days old)"
                continue
            stop = False
            try:
                tmp, build = _fetch(client, edition, d)
                ready.append((edition, tmp, build))
            except UpdateError as e:
                out[edition], stop = f"error: {redact(e)}", e.stop
            except Exception as e:  # network, disk, a corrupt archive: this edition fails, the other still runs
                out[edition] = f"error: {edition}: {type(e).__name__}: {redact(e)[:160]}"
            if edition in out:
                log.warning("GeoLite2 update: %s", out[edition][7:])
            if stop:  # the same credentials or download limit would fail the other edition too
                break
    if ready:
        def swap() -> None:
            for edition, tmp, build in ready:
                try:
                    os.replace(tmp, target(edition))
                    out[edition] = f"updated{' (build ' + build + ')' if build else ''}"
                except OSError as e:  # Windows: another process (a running app) still maps the old file
                    _unlink(tmp)
                    out[edition] = f"error: {edition}: cannot replace the file ({type(e).__name__}); is another process using it?"
                    log.warning("GeoLite2 update: %s", out[edition][7:])

        tracking.reset_mmdb(swap)
        for edition, _, _ in ready:
            if out[edition].startswith("updated"):
                log.info("GeoLite2: %s %s", edition, out[edition])
    return out


def run() -> dict[str, str]:
    """The weekly scheduler job and the startup thread."""
    try:
        return update()
    except Exception as e:  # never take the scheduler down
        log.warning("GeoLite2 update failed: %s", redact(e))
        return {"*": f"error: {redact(e)[:160]}"}


def start_background() -> bool:
    """Startup: when a key is set and a file is missing or stale, update on a daemon thread. True when one started."""
    if not needs_update():
        return False
    threading.Thread(target=run, name="geoip-update", daemon=True).start()
    return True


def _cli(argv: list[str]) -> int:
    if any(a != "--force" for a in argv):  # -h, --help, anything unknown
        print("usage: python -m app.geoip_update [--force]")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _install_filter()
    print(f"GeoLite2 folder: {data_dir().resolve()}")
    print(f"endpoint: {'account id + licence key (basic auth)' if settings.maxmind_account_id else 'licence key only (legacy URL)'}"
          if configured() else "endpoint: none")
    result = update(force="--force" in argv)
    for edition, what in result.items():
        print(f"{edition}: {what}")
    return 1 if any(v.startswith(("error", "skipped")) for v in result.values()) else 0


if __name__ == "__main__":  # python -m app.geoip_update --force
    sys.exit(_cli(sys.argv[1:]))
