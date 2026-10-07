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
