"""Lead enrichment from the email domain: pure parsing hermetically, lookup with a stubbed homepage fetch."""
from __future__ import annotations

import time

import pytest

from app import enrich
from app.templates import render_host

PAGE = """<html><head><title>Home | LakeB2B - B2B data, intent and audiences</title>
<meta property="og:site_name" content="LakeB2B">
<meta name="description" content="LakeB2B helps revenue teams reach the right accounts with verified B2B data &amp; intent." >
</head><body>hi</body></html>"""


def test_domain_and_free_mail_detection():
    assert enrich.domain_of("Ada@Lovelace.org ") == "lovelace.org"
    assert enrich.domain_of("not-an-email") == "" and enrich.domain_of(None) == "" and enrich.domain_of("x@localhost") == ""
    assert enrich.is_free_mail("gmail.com") and enrich.is_free_mail("yahoo.co.uk") and enrich.is_free_mail("outlook.de")
    assert not enrich.is_free_mail("lakeb2b.com") and not enrich.is_free_mail("championsmail.com")


def test_title_cleaning_prefers_the_brand_part():
    assert enrich.clean_title("Home | LakeB2B - B2B data for revenue teams", "lakeb2b.com") == "LakeB2B"
    assert enrich.clean_title("Welcome", "span-global.co.uk") == "Span Global"
    assert enrich.clean_title("Acme Corp – Industrial fasteners since 1920", "acme.io") == "Acme Corp"
    assert enrich.clean_title("", "ampliz.com") == "Ampliz"


def test_homepage_parsing_and_summary_line():
    data = enrich.parse_homepage(PAGE, "lakeb2b.com")
    assert data["company"] == "LakeB2B" and data["description"].startswith("LakeB2B helps") and "&amp;" not in data["description"]
    data.update(domain="lakeb2b.com", kind="business")
    line = enrich.summary(data)
    assert line.startswith("LakeB2B (lakeb2b.com) · LakeB2B helps")
    assert enrich.summary({"domain": "gmail.com", "kind": "personal"}) == ""
    assert enrich.summary({}) == "" and enrich.summary(None) == ""


def test_lookup_uses_the_fetch_then_the_cache_and_skips_free_mail(monkeypatch):
    calls = []
    store: dict[str, dict] = {}
    monkeypatch.setattr(enrich, "fetch_homepage", lambda d, timeout=3.0: calls.append(d) or {"company": "Lovelace", "source": "homepage", "description": "Engines"})
    monkeypatch.setattr(enrich, "_cache_get", lambda d: store.get(d))
    monkeypatch.setattr(enrich, "_cache_put", lambda d, data: store.__setitem__(d, data))
    monkeypatch.setattr(enrich.settings, "enrich_enabled", True)
    a = enrich.lookup("ada@lovelace.org")
    assert a["kind"] == "business" and a["company"] == "Lovelace" and a["domain"] == "lovelace.org"
    b = enrich.lookup("bob@lovelace.org")
    assert b == a and calls == ["lovelace.org"]  # second address from the same company: cache hit, no fetch
    assert enrich.lookup("someone@gmail.com")["kind"] == "personal" and calls == ["lovelace.org"]
    assert enrich.lookup("garbage") == {}
    monkeypatch.setattr(enrich.settings, "enrich_enabled", False)
    assert enrich.lookup("x@lovelace.org") == {}


def test_slow_homepage_does_not_hold_the_booking(monkeypatch):
    def slow(domain, timeout=3.0):
        time.sleep(0.4)
        return {"company": "Slow Co", "source": "homepage"}

    monkeypatch.setattr(enrich, "fetch_homepage", slow)
    monkeypatch.setattr(enrich, "_cache_get", lambda d: None)
    monkeypatch.setattr(enrich, "_cache_put", lambda d, data: None)
    monkeypatch.setattr(enrich.settings, "enrich_enabled", True)
    t0 = time.monotonic()
    r = enrich.lookup("ada@slowco.example", budget=0.05)
    assert time.monotonic() - t0 < 0.3
    assert r["source"] == "pending" and r["company"] == "Slowco" and r["kind"] == "business"


def test_company_appears_in_the_host_brief_only_when_known():
    lead = {"name": "Ada Lovelace", "email": "ada@lovelace.org", "reason": "demo", "status": "handoff",
            "schedule": "LakeB2B Discovery Call", "schedule_slug": "discovery-call",
            "company": "Lovelace Analytical Engines (lovelace.org) · Computation"}
    _, body = render_host(lead)
    assert "Company: Lovelace Analytical Engines (lovelace.org) · Computation" in body
    lead["company"] = ""
    _, body = render_host(lead)
    assert "Company:" not in body


# ---------------------------------------------------------------- DNS proof of the email domain (domain_dns)
class Resolver:
    """An injected resolve(domain, qtype, nameservers, lifetime): answers from a table per resolver set, records calls."""
    def __init__(self, answers, fallback=None):
        self.answers, self.fallback, self.calls = answers, fallback, []

    def __call__(self, domain, qtype, ns, lifetime):
        self.calls.append((qtype, ns, lifetime, time.monotonic()))
        table = self.answers if ns is None else self.fallback
        v = table.get(qtype, []) if isinstance(table, dict) else table
        if isinstance(v, BaseException) or (isinstance(v, type) and issubclass(v, BaseException)):
            raise v
        return v


def test_dns_status_and_domain_proof(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.config import settings

    monkeypatch.setattr(settings, "domain_check_fallback_ns", "1.1.1.1,8.8.8.8")
    soon = lambda: time.monotonic() + 3  # noqa: E731
    assert enrich.dns_status("acme.com", soon(), Resolver({"MX": ["mx1.acme.com"]})) == "mx"
    r = Resolver({"MX": [], "A": ["1.2.3.4"]})
    assert enrich.dns_status("acme.com", soon(), r) == "a" and [c[0] for c in r.calls] == ["MX", "A"]   # no AAAA once A answers
    assert enrich.dns_status("acme.com", soon(), Resolver({"MX": [], "A": [], "AAAA": ["::1"]})) == "a"
    assert enrich.dns_status("acme.com", soon(), Resolver({"MX": [], "A": [], "AAAA": []})) == "none"
    assert enrich.dns_status("nope.example", soon(), Resolver({"MX": enrich.NoSuchDomain("nope.example")})) == "nxdomain"
    assert enrich.dns_status("acme.com", soon(), Resolver({"MX": ["."]})) == "none"          # null MX (RFC 7505)
    r = Resolver({"MX": TimeoutError("system resolver timed out")}, fallback={"MX": ["mx.acme.com"]})
    assert enrich.dns_status("acme.com", soon(), r) == "mx" and [c[1] for c in r.calls] == [None, ["1.1.1.1", "8.8.8.8"]]
    both = Resolver({"MX": TimeoutError("x")}, fallback={"MX": ValueError("label too long")})
    assert enrich.dns_status("acme.com", soon(), both) == "error" and len(both.calls) == 2
    late = Resolver({"MX": ["mx.acme.com"]})
    assert enrich.dns_status("acme.com", time.monotonic() - 1, late) == "error" and late.calls == []
    deadline = time.monotonic() + 1.0
    r = Resolver({"MX": TimeoutError("x")}, fallback={"MX": [], "A": []})
    enrich.dns_status("acme.com", deadline, r)
    assert r.calls and all(life <= min(enrich.DNS_QUERY_TIMEOUT, deadline - at) + 1e-6 for _, _, life, at in r.calls)
    monkeypatch.setattr(settings, "domain_check", False)                                     # off: no query at all
    monkeypatch.setattr(enrich, "_dns_resolve", lambda *a: (_ for _ in ()).throw(AssertionError("queried")))
    assert enrich.dns_status("acme.com", soon()) == "error"

    now = datetime.now(timezone.utc)
    assert enrich.domain_proof("homepage", None, None, None) == "web" and enrich.domain_proof("test", None, "nxdomain", now) == "web"
    assert enrich.domain_proof("unreachable", "403 text/html", None, None) == "a"   # a server answered with an HTTP status
    assert enrich.domain_proof("unreachable", "[Errno 11001] getaddrinfo failed", "mx", now) == "mx"
    assert enrich.domain_proof(None, None, "nxdomain", now - timedelta(days=1)) == "dead"
    assert enrich.domain_proof(None, None, "none", now - timedelta(days=1)) == "dead"
    assert enrich.domain_proof(None, None, "nxdomain", now - timedelta(days=5)) == "unknown"   # checked again after 3 days
    assert enrich.domain_proof(None, None, "mx", now - timedelta(days=40)) == "unknown"
    assert enrich.domain_proof(None, None, "error", now) == "unknown" and enrich.domain_proof(None, None, None, None) == "unknown"


def _db_up() -> bool:
    from tests.test_reminders import _db_up as up

    return up()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_ensure_checked_uses_domain_dns(monkeypatch):
    import json
    from uuid import uuid4

    from app import precall
    from app.config import settings
    from app.db import conn

    d = f"test-{uuid4().hex[:8]}.example"
    monkeypatch.setattr(settings, "domain_check", True)
    calls = []
    monkeypatch.setattr(enrich, "dns_status", lambda domain, deadline=None, resolve=None: calls.append(domain) or "mx")
    try:
        assert enrich.ensure_checked([d, "gmail.com", "gmial.com", "mailinator.com"], time.monotonic() + 2) == {d: "mx"}
        assert enrich.ensure_checked([d], time.monotonic() + 2) == {} and calls == [d]       # fresh: no second lookup
        with conn() as c:
            assert c.execute("SELECT status FROM domain_dns WHERE domain = %s", (d,)).fetchone()[0] == "mx"
            assert c.execute("SELECT count(*) FROM companies WHERE domain = %s", (d,)).fetchone()[0] == 0   # companies untouched
            # a homepage row past the 30-day cache does not hide the DNS result (the stale-cache regression)
            c.execute("INSERT INTO companies(domain, data, fetched_at) VALUES (%s, %s::jsonb, now() - interval '40 days')",
                      (d, json.dumps({"source": "homepage", "company": "X"})))
            c.commit()
        assert precall.gather(f"ada@{d}")["domain_proof"] == "mx"
        with conn() as c:   # an 'error' row is retried only after DNS_RETRY_MIN
            c.execute("UPDATE domain_dns SET status = 'error', checked_at = now() WHERE domain = %s", (d,))
            c.commit()
        assert enrich.ensure_checked([d], time.monotonic() + 2) == {} and calls == [d]
        monkeypatch.setattr(enrich, "DNS_RETRY_MIN", 0)
        assert enrich.ensure_checked([d], time.monotonic() + 2) == {d: "mx"} and calls == [d, d]
        assert enrich.ensure_checked([d], time.monotonic() - 1) == {}                         # past the deadline: nothing
        monkeypatch.setattr(settings, "domain_check", False)
        with conn() as c:
            c.execute("DELETE FROM domain_dns WHERE domain = %s", (d,))
            c.commit()
        assert enrich.ensure_checked([d], time.monotonic() + 2) == {} and len(calls) == 2      # off: nothing checked or written
    finally:
        with conn() as c:
            c.execute("DELETE FROM domain_dns WHERE domain = %s", (d,))
            c.execute("DELETE FROM companies WHERE domain = %s", (d,))
            c.commit()
