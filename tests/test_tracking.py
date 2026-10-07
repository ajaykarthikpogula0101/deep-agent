"""Session origin tracking: the pure helpers are tested hermetically; the DB round-trip runs only when Postgres is up."""
from __future__ import annotations

import uuid

import pytest

from app import tracking
from app.tracking import classify_channel, client_ip, format_origin, is_public, mask_ip, normalise_geo, parse_utm


def test_client_ip_prefers_proxy_headers_only_when_trusted():
    h = {"x-forwarded-for": "203.0.113.9, 10.0.0.1", "x-real-ip": "203.0.113.10"}
    assert client_ip(h, "10.0.0.2", trust_proxy=True) == "203.0.113.10"  # x-real-ip wins over the XFF chain
    assert client_ip({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.2", trust_proxy=True) == "203.0.113.9"
    assert client_ip({"cf-connecting-ip": "198.51.100.7", **h}, "10.0.0.2", trust_proxy=True) == "198.51.100.7"
    assert client_ip(h, "10.0.0.2", trust_proxy=False) == "10.0.0.2"


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
    # 203.0.113.0/24 is a documentation range and Python's ipaddress treats it as private, so use a real public one
    sid, vid, ip = f"test-{uuid.uuid4()}", f"vis-{uuid.uuid4()}", "49.207.200.10"
    from app.db import conn

    def cleanup():
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
            c.execute("DELETE FROM ip_geo WHERE ip = %s", (ip,))  # a cached real lookup would bypass the stub
            c.commit()

    cleanup()
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
        assert (stored_ip, city, geo_status) == ("49.207.200.0", "Bengaluru", "ok")  # masked after the lookup
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
