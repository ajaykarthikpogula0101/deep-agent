"""MaxMind GeoLite2 downloads (app/geoip_update.py) and the mmdb reader reset (app/tracking.py). No network: MaxMind is
stubbed with respx and the archives are tiny tar.gz files built here."""
from __future__ import annotations

import hashlib
import io
import logging
import os
import tarfile
import time

import httpx
import pytest
import respx

from app import geoip_update, tracking
from app.config import settings
from app.geoip_update import EDITIONS, UpdateError, extract_mmdb

KEY = "SeCrEtKeY_123456"
LEGACY = "https://download.maxmind.com/app/geoip_download"
CURRENT = r"https://download\.maxmind\.com/geoip/databases/(?P<edition>[A-Za-z0-9-]+)/download"


def make_tar(edition: str, payload: bytes | None = None, name: str | None = None, link: bool = False) -> bytes:
    """A GeoLite2-shaped archive: <edition>_<date>/COPYRIGHT.txt and <edition>_<date>/<edition>.mmdb."""
    payload = payload if payload is not None else f"fake {edition} database".encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        extra = tarfile.TarInfo(f"{edition}_20261013/COPYRIGHT.txt")
        extra.size = 9
        tf.addfile(extra, io.BytesIO(b"copyright"))
        info = tarfile.TarInfo(name or f"{edition}_20261013/{edition}.mmdb")
        if link:
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tf.addfile(info)
        else:
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def sha_line(body: bytes, edition: str) -> str:
    return f"{hashlib.sha256(body).hexdigest()}  {edition}_20261013.tar.gz\n"


@pytest.fixture
def geo_dir(tmp_path, monkeypatch):
    d = tmp_path / "geoip"
    monkeypatch.setattr(settings, "geoip_mmdb_dir", str(d))
    monkeypatch.setattr(settings, "maxmind_license_key", KEY)
    monkeypatch.setattr(settings, "maxmind_account_id", "")
    monkeypatch.setattr(geoip_update, "_validate", lambda path, edition: "2026-10-13")
    monkeypatch.setattr(tracking, "_mmdb", {})
    return d


def legacy_routes(archives: dict[str, bytes], sha: dict[str, str] | None = None, status: int = 200):
    """The key-only endpoint: edition_id and suffix select the file."""
    def answer(request: httpx.Request) -> httpx.Response:
        ed, suffix = request.url.params["edition_id"], request.url.params["suffix"]
        if status != 200:
            return httpx.Response(status, text="Invalid license key")
        if suffix == "tar.gz.sha256":
            return httpx.Response(200, text=(sha or {}).get(ed) or sha_line(archives[ed], ed))
        return httpx.Response(200, content=archives[ed])

    return respx.get(url__startswith=LEGACY).mock(side_effect=answer)


def leftovers(d) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.startswith("."))


# ---------------------------------------------------------------- downloads
@respx.mock
def test_account_id_uses_basic_auth_follows_the_redirect_and_installs_both_files(geo_dir, monkeypatch):
    monkeypatch.setattr(settings, "maxmind_account_id", "123456")
    archives = {e: make_tar(e) for e in EDITIONS}

    def first(request, edition):
        assert request.headers["authorization"].startswith("Basic ") and KEY not in str(request.url)
        return httpx.Response(302, headers={"location": f"https://r2.example/{edition}.{request.url.params['suffix']}"})

    def storage(request):
        assert "authorization" not in request.headers  # httpx drops it on the cross-origin redirect
        edition, _, suffix = request.url.path.lstrip("/").partition(".")
        return httpx.Response(200, text=sha_line(archives[edition], edition)) if suffix.endswith("sha256") else \
            httpx.Response(200, content=archives[edition])

    respx.get(url__regex=CURRENT).mock(side_effect=first)
    respx.get(url__startswith="https://r2.example/").mock(side_effect=storage)
    out = geoip_update.update()
    assert out == {e: "updated (build 2026-10-13)" for e in EDITIONS}
    for e in EDITIONS:
        assert (geo_dir / f"{e}.mmdb").read_bytes() == f"fake {e} database".encode()
    assert leftovers(geo_dir) == []  # no temp archive or .part file stays behind


@respx.mock
def test_checksum_mismatch_discards_the_download(geo_dir):
    archives = {e: make_tar(e) for e in EDITIONS}
    legacy_routes(archives, sha={"GeoLite2-City": "0" * 64 + "  GeoLite2-City_20261013.tar.gz"})
    out = geoip_update.update()
    assert out["GeoLite2-City"].startswith("error:") and "checksum mismatch" in out["GeoLite2-City"]
    assert not (geo_dir / "GeoLite2-City.mmdb").exists()
    assert out["GeoLite2-ASN"].startswith("updated")  # one bad edition does not block the other
    assert leftovers(geo_dir) == []


@respx.mock
def test_a_traversal_member_is_refused_and_nothing_is_written_outside(geo_dir, tmp_path):
    archives = {e: make_tar(e, name=f"../../{e}.mmdb") for e in EDITIONS}
    legacy_routes(archives)
    out = geoip_update.update()
    assert all("unsafe path" in out[e] for e in EDITIONS), out
    assert not any((p / f"{e}.mmdb").exists() for p in (geo_dir, tmp_path, tmp_path.parent) for e in EDITIONS)


def test_extract_takes_only_the_mmdb_member_and_refuses_links_duplicates_and_oversize(tmp_path, monkeypatch):
    def archive(**kw):
        p = tmp_path / "a.tar.gz"
        p.write_bytes(make_tar("GeoLite2-ASN", **kw))
        return p

    out = tmp_path / "out.mmdb"
    assert extract_mmdb(archive(payload=b"abc"), "GeoLite2-ASN", out) == 3 and out.read_bytes() == b"abc"
    assert not (tmp_path / "GeoLite2-ASN_20261013").exists()  # nothing else is extracted
    for kw, why in (({"link": True}, "not a regular file"), ({"name": "/abs/GeoLite2-ASN.mmdb"}, "unsafe path"),
                    ({"name": "x\\..\\GeoLite2-ASN.mmdb"}, "unsafe path"), ({"name": "x/other.mmdb"}, "0 GeoLite2-ASN.mmdb")):
        with pytest.raises(UpdateError, match=why):
            extract_mmdb(archive(**kw), "GeoLite2-ASN", out)
    monkeypatch.setattr(geoip_update, "MAX_MEMBER", 2)
    with pytest.raises(UpdateError, match="larger than"):
        extract_mmdb(archive(payload=b"abc"), "GeoLite2-ASN", out)


@respx.mock
def test_401_says_what_to_fix_stops_and_never_shows_the_key(geo_dir, caplog):
    route = legacy_routes({}, status=401)
    with caplog.at_level(logging.INFO):
        out = geoip_update.update()
    assert route.call_count == 1  # the ASN edition is not tried with the same bad key
    assert "refused the credentials (HTTP 401)" in out["GeoLite2-City"] and "MAXMIND_ACCOUNT_ID" in out["GeoLite2-City"]
    assert "GeoLite2-ASN" not in out and not (geo_dir / "GeoLite2-City.mmdb").exists()
    assert KEY not in caplog.text and KEY not in str(out)
    assert "HTTP Request" in caplog.text and "license_key=***" in caplog.text  # httpx's own line, redacted


@respx.mock
def test_429_is_reported_as_the_download_limit(geo_dir, caplog):
    legacy_routes({}, status=429)
    with caplog.at_level(logging.WARNING, logger="geoip_update"):
        out = geoip_update.update()
    assert "download limit" in out["GeoLite2-City"] and "download limit" in caplog.text and KEY not in caplog.text


@respx.mock
def test_fresh_files_are_kept_without_a_request_unless_forced(geo_dir):
    geo_dir.mkdir()
    for e in EDITIONS:
        (geo_dir / f"{e}.mmdb").write_bytes(b"old")
    route = legacy_routes({e: make_tar(e) for e in EDITIONS})
    out = geoip_update.update()
    assert route.call_count == 0 and all(out[e].startswith("fresh") for e in EDITIONS)
    assert not geoip_update.needs_update()
    old = time.time() - 7 * 86400
    os.utime(geo_dir / "GeoLite2-ASN.mmdb", (old, old))
    assert geoip_update.needs_update()
    out = geoip_update.update()
    assert out["GeoLite2-City"].startswith("fresh") and out["GeoLite2-ASN"].startswith("updated")
    assert geoip_update.update(force=True) == {e: "updated (build 2026-10-13)" for e in EDITIONS}


def test_nothing_runs_without_a_key(monkeypatch, capsys):
    assert settings.maxmind_license_key == ""  # conftest blanks the owner's key
    assert geoip_update.update() == {"*": "skipped: MAXMIND_LICENSE_KEY is not set"}
    assert not geoip_update.needs_update() and not geoip_update.start_background()
    assert geoip_update._cli([]) == 1 and "skipped" in capsys.readouterr().out
    assert geoip_update._cli(["--nope"]) == 2


def test_redact_and_the_httpx_log_filter(monkeypatch, caplog):
    monkeypatch.setattr(settings, "maxmind_license_key", KEY)
    assert geoip_update.redact(f"GET {LEGACY}?edition_id=x&license_key={KEY}&suffix=tar.gz") == \
        f"GET {LEGACY}?edition_id=x&license_key=***&suffix=tar.gz"
    assert geoip_update.redact(f"error near {KEY}") == "error near ***"
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info('HTTP Request: %s %s "%s"', "GET", httpx.URL(LEGACY, params={"license_key": KEY}), "200")
    assert KEY not in caplog.text and "license_key=***" in caplog.text


def test_settings_default_folder_only_with_a_key(monkeypatch):
    monkeypatch.setattr(settings, "geoip_mmdb_dir", "")
    assert settings.mmdb_dir == ""
    monkeypatch.setattr(settings, "maxmind_license_key", KEY)
    assert settings.mmdb_dir == "data/geoip"
    monkeypatch.setattr(settings, "geoip_mmdb_dir", "/srv/geo")
    assert settings.mmdb_dir == "/srv/geo"


def test_validate_rejects_a_file_that_is_not_that_database(tmp_path):
    pytest.importorskip("maxminddb")
    junk = tmp_path / "x.mmdb"
    junk.write_bytes(b"not a maxmind database")
    with pytest.raises(UpdateError, match="does not open"):
        geoip_update._validate(junk, "GeoLite2-City")


# ---------------------------------------------------------------- reader reset (app/tracking.py)
class FakeReader:
    def __init__(self, record):
        self.record, self.closed = record, False

    def get(self, ip):
        assert not self.closed
        return self.record

    def close(self):
        self.closed = True


def test_reset_closes_the_readers_and_the_next_lookup_reopens(monkeypatch):
    maxminddb = pytest.importorskip("maxminddb")
    opened: list[str] = []
    city_v = {"n": 1}

    def open_database(path, *a, **k):
        opened.append(os.path.basename(path))
        if path.endswith("City.mmdb"):
            return FakeReader({"country": {"iso_code": "IN", "names": {"en": "India"}},
                               "city": {"names": {"en": f"City{city_v['n']}"}}})
        return FakeReader({"autonomous_system_number": 55836, "autonomous_system_organization": "Reliance Jio Infocomm Limited"})

    monkeypatch.setattr(maxminddb, "open_database", open_database)
    monkeypatch.setattr(tracking, "_mmdb", {})
    g = tracking._mmdb_lookup("49.207.200.10")
    assert g["status"] == "ok" and g["city"] == "City1" and g["asn"] == 55836 and g["net_domain"] is None
    old = dict(tracking._mmdb)
    assert tracking._mmdb_lookup("49.207.200.11")["city"] == "City1" and len(opened) == 2  # opened once
    swapped = []
    city_v["n"] = 2
    tracking.reset_mmdb(lambda: swapped.append(tracking._mmdb_lock.locked()))
    assert swapped == [True] and old["city"].closed and old["asn"].closed and tracking._mmdb == {}
    assert tracking._mmdb_lookup("49.207.200.10")["city"] == "City2" and len(opened) == 4


@respx.mock
def test_an_update_resets_the_cached_readers_and_clears_a_missing_marker(geo_dir):
    city, asn = FakeReader({}), FakeReader({})
    tracking._mmdb.update(city=city, asn=asn)
    legacy_routes({e: make_tar(e) for e in EDITIONS})
    geoip_update.update()
    assert city.closed and asn.closed and tracking._mmdb == {}
    tracking._mmdb["missing"] = "no such file"  # a lookup before the first download finished
    geoip_update.update(force=True)
    assert tracking._mmdb == {}
