"""Signed email links (app/links.py): check() never raises, and PUBLIC_BASE_URL is judged openable from a phone or not."""
from __future__ import annotations

import pytest

from app import links
from app.config import settings


def test_check_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "link_secret", "s")
    for bad in ("é", "x" * 500, None, ""):
        assert links.check("outcome", 1, bad) is False
    assert links.check("outcome", 1, links.sign("outcome", 1)) is True


@pytest.mark.parametrize("url", ["http://localhost:8080", "", "http://127.0.0.1:8089", "http://box.local", "http://192.168.1.5",
                                 "http://host.docker.internal", "ftp://x.com", "http://[::1]:8080", "http://app.internal",
                                 "http://0.0.0.0:8080", "not a url"])
def test_public_problem_flags_addresses_a_phone_cannot_open(monkeypatch, url):
    monkeypatch.setattr(settings, "public_base_url", url)
    assert links.public_problem() and not links.public_ok() and not links.plain_http()


def test_public_problem_accepts_public_addresses(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://assistant.deependhq.com")
    assert links.public_problem() == "" and links.public_ok() and not links.plain_http()
    monkeypatch.setattr(settings, "public_base_url", "http://assistant.deependhq.com")
    assert links.public_problem() == "" and links.plain_http()
    monkeypatch.setattr(settings, "public_base_url", "https://203.0.113.7")   # TEST-NET-3 is not global
    assert "203.0.113.7" in links.public_problem()
    monkeypatch.setattr(settings, "public_base_url", "https://8.8.8.8")
    assert links.public_problem() == ""
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8080")
    assert links.public_problem() == "PUBLIC_BASE_URL points at localhost, which a phone or another computer cannot open"
