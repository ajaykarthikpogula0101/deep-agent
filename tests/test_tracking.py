"""Session origin tracking: the pure helpers are tested hermetically; the DB round-trip runs only when Postgres is up."""
from __future__ import annotations

import json
import uuid

import pytest

from app import tracking
from app.tracking import classify_channel, client_ip, format_origin, is_public, mask_ip, normalise_geo, parse_utm


def test_client_ip_prefers_proxy_headers_only_when_trusted():
    h = {"x-forwarded-for": "203.0.113.9, 10.0.0.1", "x-real-ip": "203.0.113.10"}
    assert client_ip(h, "10.0.0.2", trust_proxy=True) == "203.0.113.9"    # the XFF walk wins over x-real-ip
    assert client_ip({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.2", trust_proxy=True) == "203.0.113.9"
    assert client_ip({"x-real-ip": "203.0.113.10"}, "10.0.0.2", trust_proxy=True) == "203.0.113.10"   # no XFF: x-real-ip
    assert client_ip(h, "10.0.0.2", trust_proxy=False) == "10.0.0.2"


def test_forged_cf_connecting_ip_or_x_real_ip_never_beats_the_forwarded_for_walk():
    """nginx in front (a trusted peer) appends the real address to X-Forwarded-For but passes the visitor's own
    CF-Connecting-IP through: the walk decides."""
    forged = {"cf-connecting-ip": "17.253.0.5", "x-forwarded-for": "17.253.0.5, 49.207.200.10"}
    assert client_ip(forged, "127.0.0.1", trust_proxy=True) == "49.207.200.10"
    assert client_ip({"x-real-ip": "17.253.0.5", "x-forwarded-for": "49.207.200.10"}, "10.0.0.2", trust_proxy=True) == "49.207.200.10"
    assert client_ip({"cf-connecting-ip": "17.253.0.5"}, "127.0.0.1", trust_proxy=True) == "127.0.0.1"   # no XFF: not from Cloudflare
    # every hop a trusted proxy (Cloudflare's ranges listed in TRUSTED_PROXIES): the outermost one's header names the visitor
    assert client_ip({"cf-connecting-ip": "49.207.200.10", "x-forwarded-for": "10.0.0.7, 10.0.0.5"}, "10.0.0.2", trust_proxy=True) == \
        "49.207.200.10"


def test_client_ip_ignores_garbage_headers():
    assert client_ip({"x-forwarded-for": "not-an-ip"}, "192.0.2.1", trust_proxy=True) == "192.0.2.1"
    assert client_ip({}, None, trust_proxy=True) == "unknown"


def test_public_and_private_addresses():
    assert is_public("8.8.8.8") and is_public("2606:4700::1111")
    for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.5", "::1", "169.254.1.1", "unknown"):
        assert not is_public(ip)


def test_mask_ip_keeps_the_network_only():
    assert mask_ip("203.0.113.77") == "203.0.113.0"
    assert mask_ip("2001:db8:abcd:1234::9") == "2001:db8:abcd::"
    assert mask_ip("unknown") == "unknown"


def test_parse_utm_and_channel_classification():
    page = "https://deependhq.com/pillars?utm_source=linkedin&utm_medium=paidsocial&utm_campaign=q4&x=1"
    utm = parse_utm(page)
    assert utm == {"utm_source": "linkedin", "utm_medium": "paidsocial", "utm_campaign": "q4"}
    assert classify_channel("https://www.linkedin.com/feed/", utm, "deependhq.com") == "paid"
    assert classify_channel("https://www.linkedin.com/feed/", {}, "deependhq.com") == "social"
    assert classify_channel("https://www.google.com/", {}, "deependhq.com") == "search"
    assert classify_channel("https://chatgpt.com/c/abc", {}, "deependhq.com") == "ai"
    assert classify_channel("https://deependhq.com/journey", {}, "deependhq.com") == "internal"
    assert classify_channel("https://news.ycombinator.com/", {}, "deependhq.com") == "referral"
    assert classify_channel("", {}, "deependhq.com") == "direct"
    assert classify_channel("", {"utm_medium": "newsletter"}, "deependhq.com") == "email"
    assert classify_channel(None, {"utm_source": "qr"}, "deependhq.com") == "campaign"


def test_normalise_geo_handles_each_provider_and_failures():
    ipwho = {"success": True, "country": "India", "country_code": "IN", "region": "Karnataka", "city": "Bengaluru",
             "latitude": 12.97, "longitude": 77.59, "connection": {"isp": "Jio"}, "timezone": {"id": "Asia/Kolkata"}}
    g = normalise_geo("ipwho", ipwho)
    assert (g["city"], g["country_code"], g["isp"], g["geo_tz"], g["status"]) == ("Bengaluru", "IN", "Jio", "Asia/Kolkata", "ok")
    ipinfo = {"country": "US", "region": "California", "city": "Mountain View", "loc": "37.38,-122.08", "org": "AS15169 Google"}
    g = normalise_geo("ipinfo", ipinfo)
    assert (g["city"], g["lat"], g["lon"], g["status"]) == ("Mountain View", 37.38, -122.08, "ok")
    assert normalise_geo("ipwho", {"success": False, "message": "reserved range"})["status"] == "failed"
    assert normalise_geo("ipinfo", {"bogon": True})["status"] == "failed"
    assert normalise_geo("ipapi", {"status": "fail"})["status"] == "failed"


def test_format_origin_reads_like_a_sentence():
    row = {"city": "Bengaluru", "region": "Karnataka", "country_code": "IN", "isp": "Jio", "referrer_host": "linkedin.com",
           "channel": "social", "utm": {}, "page": "https://deependhq.com/pillars", "visit_number": 2, "messages": 4}
    assert format_origin(row) == "Bengaluru, Karnataka, IN · Jio · via linkedin.com (social) · on /pillars · visit 2 · 4 messages"
    assert format_origin({"geo_status": "private", "channel": "direct", "messages": 1}) == "local/private network · direct · 1 message"
    camp = {"country": "Germany", "channel": "paid", "utm": '{"utm_source": "linkedin", "utm_medium": "cpc", "utm_campaign": "q4"}'}
    assert format_origin(camp) == "Germany · campaign linkedin/cpc/q4"


def _doc_nets_public(monkeypatch):
    """Let the session tests look up and cache the reserved documentation ranges (TEST-NET-1/2/3): the app treats them
    as private, so no real lookup is ever cached there and a test's ip_net row cannot be anyone else's."""
    real = tracking.is_public
    monkeypatch.setattr(tracking, "is_public", lambda ip: str(ip).startswith(DOC_NETS) or real(ip))


DOC_NETS = ("192.0.2.", "198.51.100.", "203.0.113.")


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_session_round_trip_without_network(monkeypatch):
    """Beacon -> touch -> describe, with the geo provider stubbed so the test needs no internet."""
    monkeypatch.setattr(tracking, "_fetch_geo", lambda ip: normalise_geo("ipwho", {
        "success": True, "country": "India", "country_code": "IN", "region": "Karnataka", "city": "Bengaluru",
        "latitude": 12.97, "longitude": 77.59, "connection": {"isp": "Jio"}, "timezone": {"id": "Asia/Kolkata"}}))
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    monkeypatch.setattr(tracking.settings, "track_ip_mode", "masked")
    sid, vid, ip = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}", "203.0.113.10"
    _doc_nets_public(monkeypatch)
    nets = _Nets(ip)   # the /24 row this test writes is the only one it deletes
    from app.db import conn

    def cleanup():
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
            c.commit()
        nets.drop()

    monkeypatch.setattr(tracking.settings, "net_rdns", False)
    try:
        res = tracking.start_session(sid, vid, ip, "pytest/1.0", "https://deependhq.com/pillars?utm_source=newsletter&utm_medium=email",
                                     "https://mail.google.com/", "Asia/Kolkata", "en-IN", "1440x900")
        assert res["tracked"] and res["channel"] == "email" and res["visit_number"] == 1
        tracking.touch(sid, ip, "pytest/1.0")
        tracking.touch(sid, ip, "pytest/1.0")
        tracking._executor.shutdown(wait=True)  # let the background enrichment finish
        tracking._executor = type(tracking._executor)(max_workers=2)
        line = tracking.describe_session(sid)
        assert line.startswith("Bengaluru, Karnataka, IN · Jio · campaign newsletter/email/-")
        assert line.endswith("visit 1 · 2 messages")
        with conn() as c:
            stored_ip, city, geo_status = c.execute("SELECT ip, city, geo_status FROM sessions WHERE session_id = %s", (sid,)).fetchone()
        assert (stored_ip, city, geo_status) == ("203.0.113.0", "Bengaluru", "ok")  # masked after the lookup
        # the host brief carries the origin line
        from app.booking.email import render_brief

        _, body = render_brief({"name": "Ada", "email": "ada@example.com", "reason": "x", "status": "handoff", "origin": line})
        assert f"Where:   {line}" in body
    finally:
        cleanup()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_returning_visitor_and_private_ip(monkeypatch):
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    vid = f"vis-{uuid.uuid4()}"
    sids = [f"test-{uuid.uuid4()}" for _ in range(2)]
    from app.db import conn

    try:
        first = tracking.start_session(sids[0], vid, "127.0.0.1", None, None, None, None, None, None)
        second = tracking.start_session(sids[1], vid, "127.0.0.1", None, "https://deependhq.com/", None, None, None, None)
        assert (first["visit_number"], second["visit_number"]) == (1, 2)
        tracking._executor.shutdown(wait=True)
        tracking._executor = type(tracking._executor)(max_workers=2)
        with conn() as c:
            status, = c.execute("SELECT geo_status FROM sessions WHERE session_id = %s", (sids[1],)).fetchone()
        assert status == "private"  # loopback is never sent to the provider
        assert tracking.describe_session(sids[1]).startswith("local/private network · direct · on / · visit 2")
    finally:
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE session_id = ANY(%s)", (sids,))
            c.commit()


# ---------------------------------------------------------------- ensure_session: the single write path
IPWHO = {"success": True, "country": "India", "country_code": "IN", "region": "Karnataka", "city": "Bengaluru",
         "latitude": 12.97, "longitude": 77.59, "connection": {"isp": "Jio"}, "timezone": {"id": "Asia/Kolkata"}}


def _drain():
    tracking._executor.shutdown(wait=True)  # waits for every worker, unlike submit(...).result()
    tracking._executor = type(tracking._executor)(max_workers=2)


def _row(sid, cols="visitor_id, ip, user_agent, page, channel, geo_status, messages, leads, city"):
    from app.db import conn

    with conn() as c:
        r = c.execute(f"SELECT {cols} FROM sessions WHERE session_id = %s", (sid,)).fetchone()
    return dict(zip([x.strip() for x in cols.split(",")], r)) if r else None


def _drop(*sids):
    from app.db import conn

    with conn() as c:
        c.execute("DELETE FROM sessions WHERE session_id = ANY(%s)", (list(sids),))
        c.commit()


def _count_submits(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(tracking._executor, "submit", lambda *a, **k: calls.append(a))
    return calls


def test_valid_sid_and_clean_vid():
    assert tracking.valid_sid("test-1234") and tracking.valid_sid("a" * 64)
    assert not any(tracking.valid_sid(s) for s in ("s1", "", None, "a" * 65, "bad id 123", "<script>x"))
    assert tracking.clean_vid(" vis_1-a ") == "vis_1-a" and tracking.clean_vid("x") == "x"
    assert tracking.clean_vid("<b>x") is None and tracking.clean_vid("") is None and tracking.clean_vid("v" * 65) is None


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_ensure_session_creates_row_with_visitor_and_geo(monkeypatch):
    from app.db import conn

    monkeypatch.setattr(tracking, "_fetch_geo", lambda ip: normalise_geo("ipwho", IPWHO))
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    sid, vid, ip = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}", "198.51.100.10"
    _doc_nets_public(monkeypatch)
    nets = _Nets(ip)
    try:
        assert tracking.ensure_session(sid, visitor_id=vid, ip=ip, user_agent="pytest",
                                       page="https://deependhq.com/pricing?utm_source=linkedin",
                                       referrer="https://www.linkedin.com/") is True
        _drain()
        r = _row(sid)
        assert r["visitor_id"] == vid and r["page"] == "https://deependhq.com/pricing?utm_source=linkedin"
        assert r["channel"] == "social" and r["geo_status"] == "ok" and r["city"] == "Bengaluru"
    finally:
        _drop(sid)
        nets.drop()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_ensure_session_upgrades_direct_row_when_beacon_arrives_late(monkeypatch):
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    sid, vid = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}"
    try:
        tracking.touch(sid, "127.0.0.1", "pytest")
        r = _row(sid)
        assert (r["channel"], r["page"], r["messages"]) == ("direct", None, 1)
        res = tracking.start_session(sid, vid, "127.0.0.1", "pytest", "https://deependhq.com/", "https://www.linkedin.com/",
                                     "Asia/Kolkata", "en", "1440x900")
        assert set(res) == {"ok", "tracked", "channel", "visit_number"}
        assert res["ok"] and res["tracked"] and res["channel"] == "social" and res["visit_number"] == 1
        _drain()
        r = _row(sid)
        assert (r["channel"], r["messages"], r["visitor_id"], r["page"]) == ("social", 1, vid, "https://deependhq.com/")
    finally:
        _drop(sid)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_ensure_session_keeps_first_values_and_counts(monkeypatch):
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    _count_submits(monkeypatch)
    sid, junk = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    try:
        assert tracking.ensure_session(sid, visitor_id="vis-first", page="https://deependhq.com/a", ip="unknown") is True
        assert tracking.ensure_session(sid, visitor_id="vis-second", page="https://deependhq.com/b", message=True) is False
        tracking.ensure_session(sid, lead=True)
        r = _row(sid)
        assert (r["visitor_id"], r["page"], r["messages"], r["leads"]) == ("vis-first", "https://deependhq.com/a", 1, 1)
        assert r["ip"] is None and r["geo_status"] == "unknown"  # the 'unknown' string is never stored
        tracking.attach_visitor(junk, "<b>x")
        assert _row(junk) is None  # a junk visitor id alone writes nothing
        tracking.ensure_session(junk, visitor_id=tracking.clean_vid("<b>x"))
        assert _row(junk)["visitor_id"] is None
        assert tracking.ensure_session("s1", message=True) is None  # invalid ids are skipped before any SQL
    finally:
        _drop(sid, junk)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_ensure_session_respects_tracking_disabled(monkeypatch):
    monkeypatch.setattr(tracking.settings, "tracking_enabled", False)
    calls = _count_submits(monkeypatch)
    sid, vid = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}"
    try:
        assert tracking.ensure_session(sid, visitor_id=vid, ip="49.207.200.10", user_agent="ua", page="https://x/",
                                       referrer="https://www.linkedin.com/", client_tz="UTC", lang="en", screen="1x1",
                                       message=True) is True
        r = _row(sid, "visitor_id, ip, user_agent, page, referrer, client_tz, lang, screen, geo_status, messages")
        assert r["visitor_id"] == vid and r["geo_status"] == "disabled" and r["messages"] == 1
        assert all(r[k] is None for k in ("ip", "user_agent", "page", "referrer", "client_tz", "lang", "screen"))
        assert calls == []
    finally:
        _drop(sid)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_got_ip_triggers_enrich_once(monkeypatch):
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    calls = _count_submits(monkeypatch)
    sid, vid, ip = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}", "49.207.200.10"
    try:
        tracking.ensure_session(sid, visitor_id=vid)
        assert _row(sid)["geo_status"] == "unknown" and calls == []
        tracking.ensure_session(sid, ip=ip)
        assert len(calls) == 1 and calls[0][1:] == (sid, ip)
        r = _row(sid)
        assert (r["ip"], r["geo_status"]) == (ip, "pending")
        tracking.ensure_session(sid, ip=ip)
        assert len(calls) == 1
    finally:
        _drop(sid)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_purged_row_is_not_regeolocated(monkeypatch):
    from app.db import conn

    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    calls = _count_submits(monkeypatch)
    sid = f"test-{uuid.uuid4()}"
    try:
        with conn() as c:  # as purge() leaves a geolocated row after TRACK_RETENTION_DAYS
            c.execute("INSERT INTO sessions(session_id, channel, geo_status, city) VALUES (%s, 'direct', 'ok', 'Bengaluru')", (sid,))
            c.commit()
        assert tracking.ensure_session(sid, ip="8.8.8.8") is False
        r = _row(sid)
        assert (r["ip"], r["geo_status"], r["city"]) == (None, "ok", "Bengaluru") and calls == []
    finally:
        _drop(sid)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_attach_lead_creates_missing_row():
    from app.db import conn

    sid = f"test-{uuid.uuid4()}"
    with conn() as c:
        lead_id = c.execute("""INSERT INTO leads(name, email, reason, status) VALUES ('Ada', 'ada@example.test', 'pytest', 'enquiry')
                               RETURNING id""").fetchone()[0]
        s1_before = c.execute("SELECT count(*) FROM sessions WHERE session_id = 's1'").fetchone()[0]
        c.commit()
    try:
        tracking.attach_lead(sid, lead_id)
        assert _row(sid)["leads"] == 1
        with conn() as c:
            assert c.execute("SELECT session_id FROM leads WHERE id = %s", (lead_id,)).fetchone()[0] == sid
        tracking.attach_lead("s1", lead_id)
        with conn() as c:
            assert c.execute("SELECT count(*) FROM sessions WHERE session_id = 's1'").fetchone()[0] == s1_before
    finally:
        _drop(sid)
        with conn() as c:
            c.execute("DELETE FROM leads WHERE id = %s", (lead_id,))
            c.commit()


# ---------------------------------------------------------------- the network behind the IP
def test_normalise_geo_network_keys():
    g = normalise_geo("ipwho", dict(IPWHO, connection={"asn": 15169, "org": "Google LLC", "isp": "Google LLC", "domain": "google.com"}))
    assert (g["asn"], g["as_org"], g["net_domain"], g["org_scope"], g["provider"]) == (15169, "Google LLC", "google.com", "asn", "ipwho")
    assert g["isp"] == "Google LLC" and g["city"] == "Bengaluru"
    g = normalise_geo("ipinfo", {"country": "US", "city": "Mountain View", "loc": "37.38,-122.08", "org": "AS15169 Google LLC",
                                 "hostname": "dns.google", "ip": "8.8.8.8"})
    assert (g["asn"], g["as_org"], g["isp"]) == (15169, "Google LLC", "AS15169 Google LLC")
    assert "hostname" not in g and g["rdns_domain"] == "dns.google" and "8.8.8.8" not in str(g)
    g = normalise_geo("ipapi", {"status": "success", "country": "India", "countryCode": "IN", "city": "Mumbai", "isp": "Reliance Jio",
                                "as": "AS55836 Reliance Jio Infocomm Limited", "asname": "RELIANCEJIO-IN", "org": "",
                                "mobile": True, "proxy": False, "hosting": False, "reverse": "49.200.207.49.jio.example"})
    assert (g["asn"], g["flags"]["mobile"], g["flags"]["proxy"], g["org_scope"]) == (55836, True, False, "netblock")
    assert g["as_org"] == "Reliance Jio Infocomm Limited" and "hostname" not in g and "reverse" not in g
    g = normalise_geo("ipapiis", {"ip": "1.2.3.4", "is_mobile": False, "is_vpn": False, "is_proxy": True, "is_tor": False,
                                  "is_datacenter": False,
                                  "company": {"name": "Infosys Limited", "type": "business", "network": "1.2.3.0 - 1.2.3.255"},
                                  "asn": {"asn": 4755, "org": "TATA Communications", "domain": "tatacommunications.com", "type": "isp"},
                                  "location": {"country": "India", "country_code": "in", "state": "Karnataka", "city": "Bengaluru",
                                               "latitude": 12.9, "longitude": 77.6, "timezone": "Asia/Kolkata"}})
    assert (g["status"], g["type"], g["org"], g["org_scope"], g["asn"], g["country_code"]) == \
        ("ok", "business", "Infosys Limited", "netblock", 4755, "IN")
    assert g["flags"] == {"mobile": False, "proxy": True, "hosting": False} and "1.2.3" not in str(g)
    assert normalise_geo("ipapiis", {"location": {}})["status"] == "failed"


def test_client_ip_walks_forwarded_for_and_ignores_untrusted_peers():
    assert client_ip({"x-forwarded-for": "1.2.3.4, 49.207.200.10"}, "10.0.0.2", trust_proxy=True) == "49.207.200.10"
    assert client_ip({"x-forwarded-for": "1.2.3.4, 49.207.200.10, 10.0.0.5"}, "10.0.0.2", trust_proxy=True) == "49.207.200.10"
    assert client_ip({"x-forwarded-for": "10.0.0.7, 10.0.0.5"}, "10.0.0.2", trust_proxy=True) == "10.0.0.7"
    assert client_ip({"x-real-ip": "8.8.8.8"}, "49.207.200.10", trust_proxy=True) == "49.207.200.10"
    assert client_ip({"cf-connecting-ip": "17.0.0.1"}, "49.207.200.10", trust_proxy=True) == "49.207.200.10"


def test_geolocate_unknown_and_format_network():
    assert tracking.geolocate("unknown")["status"] == "unknown"
    assert tracking.format_network({"net_kind": "consumer", "net_org": "Reliance Jio", "net_flags": {"mobile": True}}) == \
        "Reliance Jio · mobile network"
    assert tracking.format_network({"net_kind": "local"}) == "local test network (no lookup)"
    assert tracking.format_network({"net_kind": None, "isp": "Jio"}) == ""
    assert tracking.format_network({"net_kind": "corporate", "net_org": "Infosys Limited", "net_flags": '{"dev": true}'},
                                   "matches their company") == "Infosys · company network · matches their company [dev test IP]"


def _fresh_provider_state(monkeypatch, chain="ipwho", cap=300):
    monkeypatch.setattr(tracking.settings, "geoip_provider", chain)
    monkeypatch.setattr(tracking.settings, "geoip_daily_cap", cap)
    monkeypatch.setattr(tracking, "_quota", {})
    monkeypatch.setattr(tracking, "_cooldown", {})
    monkeypatch.setattr(tracking, "_errors", {})


def _ok_payload(provider="ipwho", **conn_):
    return normalise_geo("ipwho", dict(IPWHO, connection={"isp": "Jio", **conn_})) | {"provider": provider}


class _Nets:
    """Dedicated /24s for one test; skips if any already holds a cached lookup (never touch rows we did not write)."""
    def __init__(self, *ips):
        from app.db import conn

        self.nets = [mask_ip(i) for i in ips]
        with conn() as c:
            if c.execute("SELECT count(*) FROM ip_net WHERE net = ANY(%s)", (self.nets,)).fetchone()[0]:
                pytest.skip("test /24 already cached")

    def drop(self):
        from app.db import conn

        with conn() as c:
            c.execute("DELETE FROM ip_net WHERE net = ANY(%s)", (self.nets,))
            c.commit()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_geolocate_caches_per_net_without_the_ip(monkeypatch):
    from app.db import conn

    _fresh_provider_state(monkeypatch)
    calls = []
    monkeypatch.setattr(tracking, "_fetch_one", lambda p, ip: calls.append((p, ip)) or _ok_payload(p, asn=55836))
    a, b, bad = "49.207.233.10", "49.207.233.99", "49.207.234.10"
    nets = _Nets(a, bad)
    try:
        assert tracking.geolocate(a)["status"] == "ok" and tracking.geolocate(b)["status"] == "ok"
        assert calls == [("ipwho", a)]
        with conn() as c:
            assert c.execute("SELECT net, status FROM ip_net WHERE net = %s", ("49.207.233.0",)).fetchone() == ("49.207.233.0", "ok")
            assert c.execute("SELECT count(*) FROM ip_net WHERE data::text LIKE %s OR data::text LIKE %s",
                             (f"%{a}%", f"%{b}%")).fetchone()[0] == 0
        monkeypatch.setattr(tracking, "_fetch_one", lambda p, ip: calls.append((p, ip)) or tracking._failed(p, "error"))
        g = tracking.geolocate(bad)
        assert g["status"] == "failed" and g["reason"] == "error" and len(calls) == 2
        with conn() as c:
            assert c.execute("SELECT retry_after > now() FROM ip_net WHERE net = '49.207.234.0'").fetchone()[0] is True
        assert tracking.geolocate(bad)["reason"] == "error" and len(calls) == 2  # inside the retry window: no call
    finally:
        nets.drop()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_rate_limit_cooldown_and_daily_cap(monkeypatch):
    _fresh_provider_state(monkeypatch, chain="ipwho,ipinfo")
    calls = []

    def fetch(p, ip):
        calls.append(p)
        if p == "ipwho":
            return tracking._failed(p, "rate_limited") | {"retry_in": 900}
        return _ok_payload(p)

    monkeypatch.setattr(tracking, "_fetch_one", fetch)
    ips = ["49.207.235.10", "49.207.236.10", "49.207.237.10", "49.207.238.10"]
    nets = _Nets(*ips)
    try:
        assert tracking.geolocate(ips[0])["provider"] == "ipinfo" and calls == ["ipwho", "ipinfo"]
        assert tracking.geolocate(ips[1])["provider"] == "ipinfo" and calls == ["ipwho", "ipinfo", "ipinfo"]  # ipwho paused
        _fresh_provider_state(monkeypatch, chain="ipinfo", cap=1)
        calls.clear()
        assert tracking.geolocate(ips[2])["status"] == "ok" and calls == ["ipinfo"]
        g = tracking.geolocate(ips[3])
        assert (g["status"], g["reason"], calls) == ("failed", "quota", ["ipinfo"])
    finally:
        nets.drop()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_enrich_writes_network_columns_and_dev_ip(monkeypatch):
    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    monkeypatch.setattr(tracking.settings, "track_ip_mode", "masked")
    monkeypatch.setattr(tracking.settings, "net_rdns", False)
    _fresh_provider_state(monkeypatch)
    monkeypatch.setattr(tracking, "_fetch_one", lambda p, ip: _ok_payload(p, asn=55836, org="Reliance Jio Infocomm Limited",
                                                                           domain="jio.com"))
    ip, dev_ip = "49.207.239.10", "49.207.240.10"
    nets = _Nets(ip, dev_ip)
    sids = [f"test-{uuid.uuid4()}" for _ in range(3)]
    cols = "ip, geo_status, asn, net_org, net_domain, net_kind, net_flags, geo_at"
    try:
        tracking.attach_visitor(sids[0], f"vis-{uuid.uuid4()}")  # a row with no IP yet
        assert _row(sids[0], "ip, geo_status")["ip"] is None
        tracking.ensure_session(sids[0], ip=ip)
        _drain()
        r = _row(sids[0], cols)
        assert (r["ip"], r["geo_status"], r["asn"], r["net_org"], r["net_domain"], r["net_kind"]) == \
            ("49.207.239.0", "ok", 55836, "Reliance Jio Infocomm Limited", "jio.com", "consumer")
        assert r["net_flags"]["provider"] == "ipwho" and r["net_flags"]["dev"] is False and r["geo_at"] is not None
        assert "49.207" not in json.dumps(r["net_flags"])
        # format_origin is unchanged by the network; the network is its own line
        assert tracking.describe_session(sids[0]).startswith("Bengaluru, Karnataka, IN · Jio · direct")
        assert tracking.describe_network(sids[0])["net_kind"] == "consumer"
        # GEOIP_DEV_IP: only against a local database
        monkeypatch.setattr(tracking.settings, "geoip_dev_ip", dev_ip)
        monkeypatch.setattr(tracking.settings, "database_url", "postgresql://u:p@127.0.0.1:5432/x")
        tracking.ensure_session(sids[1], ip="127.0.0.1")
        _drain()
        r = _row(sids[1], cols)
        assert (r["geo_status"], r["net_kind"], r["net_flags"]["dev"]) == ("ok", "consumer", True)
        assert "[dev test IP]" in tracking.format_network(r)
        monkeypatch.setattr(tracking.settings, "database_url", "postgresql://u:p@db.example.com:5432/x")
        tracking.ensure_session(sids[2], ip="127.0.0.1")
        _drain()
        r = _row(sids[2], cols)
        assert (r["geo_status"], r["net_kind"], r["net_flags"]["dev"]) == ("private", "local", False)
        assert tracking.format_network(r) == "local test network (no lookup)"
    finally:
        _drop(*sids)
        nets.drop()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_retry_pending_picks_up_stuck_rows(monkeypatch):
    from app.db import conn

    monkeypatch.setattr(tracking.settings, "tracking_enabled", True)
    calls = _count_submits(monkeypatch)
    sid = f"test-{uuid.uuid4()}"
    try:
        with conn() as c:
            c.execute("""INSERT INTO sessions(session_id, ip, channel, geo_status, first_seen)
                         VALUES (%s, '49.207.241.10', 'direct', 'failed', now() - interval '1 hour')""", (sid,))
            c.commit()
        assert tracking.retry_pending() >= 1
        assert any(a[1:] == (sid, "49.207.241.10") for a in calls)
    finally:
        _drop(sid)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_purge_keeps_places_only_for_organisations():
    from app.db import conn

    sids = {k: f"test-{uuid.uuid4()}" for k in ("consumer", "unknown", "corporate")}
    try:
        with conn() as c:
            for kind, sid in sids.items():
                c.execute("""INSERT INTO sessions(session_id, ip, channel, geo_status, city, lat, country, net_org, net_kind, first_seen)
                             VALUES (%s, '49.207.242.10', 'direct', 'ok', 'Pune', 18.5, 'India', %s, %s,
                                     now() - make_interval(days => %s))""",
                          (sid, f"Org {kind}", None if kind == "unknown" else kind, tracking.settings.track_retention_days + 5))
            c.commit()
        r = tracking.purge(session_ids=list(sids.values()))
        assert r["sessions_scrubbed"] == 3 and r["places_scrubbed"] == 2 and r["geo_cache_dropped"] == 0
        for kind, sid in sids.items():
            row = _row(sid, "ip, city, lat, country, net_org")
            assert row["ip"] is None and row["country"] == "India" and row["net_org"] == f"Org {kind}"
            assert (row["city"], row["lat"]) == (("Pune", 18.5) if kind == "corporate" else (None, None))
    finally:
        _drop(*sids.values())


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_one_ips_reverse_dns_never_decides_its_neighbours_network(monkeypatch):
    """ipinfo's hostname is a fact about the one IP looked up: that call keeps rdns_domain/rdns_dynamic, the /24 cache
    (and every neighbour served from it) never does, including rows cached before the fields were left out."""
    from app import network
    from app.db import conn

    _fresh_provider_state(monkeypatch, chain="ipinfo")
    _doc_nets_public(monkeypatch)
    payload = {"country": "IN", "region": "Karnataka", "city": "Pune", "loc": "18.52,73.85", "org": "AS64500 Small Town Broadband",
               "timezone": "Asia/Kolkata", "hostname": "mail.acme-widgets.example"}
    calls = []
    monkeypatch.setattr(tracking, "_fetch_one", lambda p, ip: calls.append(ip) or normalise_geo("ipinfo", payload))
    a, b = "192.0.2.10", "192.0.2.77"
    nets = _Nets(a)
    try:
        first = tracking.geolocate(a)
        assert first["rdns_domain"] == "acme-widgets.example" and first["rdns_dynamic"] is False
        with conn() as c:
            data = c.execute("SELECT data FROM ip_net WHERE net = %s", (mask_ip(a),)).fetchone()[0]
            assert data["rdns_domain"] is None and data["rdns_dynamic"] is None and data["city"] == "Pune"
            assert tracking.cached_geo(b, c)["rdns_domain"] is None
        neighbour = tracking.geolocate(b)
        assert calls == [a] and neighbour["rdns_domain"] is None and neighbour["rdns_dynamic"] is None
        assert network.classify(neighbour)[0] == network.classify(normalise_geo("ipinfo", dict(payload, hostname=None)))[0]
        with conn() as c:   # a row cached before the fix still holds them: they are dropped on read
            c.execute("UPDATE ip_net SET data = data || '{\"rdns_domain\": \"acme-widgets.example\", \"rdns_dynamic\": false}'::jsonb WHERE net = %s",
                      (mask_ip(a),))
            c.commit()
            assert tracking.cached_geo(b, c)["rdns_domain"] is None
        assert tracking.geolocate(b)["rdns_domain"] is None and calls == [a]
    finally:
        nets.drop()
