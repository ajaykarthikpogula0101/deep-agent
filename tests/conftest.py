import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Keep tests hermetic: no .env, no real keys.
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://assistant:assistant@localhost:5432/assistant")

import pytest


@pytest.fixture(autouse=True)
def _no_homepage_fetch(monkeypatch):
    """Lead enrichment (app/enrich.py) never reaches the network in tests; tests that care stub it themselves."""
    from app import enrich

    monkeypatch.setattr(enrich, "fetch_homepage",
                        lambda domain, timeout=3.0: {"company": enrich.from_domain(domain), "source": "test"})


@pytest.fixture(autouse=True)
def _no_browser_booking(monkeypatch):
    """The browser worker books on the real Zoom scheduler. Unit tests never reach it: the feature reads as disabled
    and `available()` is False unless a test patches it explicitly (tests/test_browser_booking.py does)."""
    from app.booking import browser_booking
    from app.config import settings

    monkeypatch.setattr(settings, "browser_booking_enabled", False)
    monkeypatch.setattr(settings, "browser_booking_dry_run", True)
    monkeypatch.setattr(browser_booking, "available", lambda: False)
    monkeypatch.setattr(browser_booking, "_ensure_browser", lambda: "")
    monkeypatch.setattr(settings, "zoom_link_from_email", False)  # never reads a real mailbox (tests/test_zoom_mail.py)


@pytest.fixture(autouse=True)
def _no_live_health_or_backup_model(monkeypatch):
    """The health job calls the model provider and emails alerts; a backup model from .env would change which model a
    chat test sees. Tests that need either set them themselves (tests/test_health.py does)."""
    from app.config import settings

    monkeypatch.setattr(settings, "health_checks", False)
    monkeypatch.setattr(settings, "chat_fallback_model", "")
    monkeypatch.setattr(settings, "backup_enabled", False)   # never runs pg_dump against the real database
    monkeypatch.setattr(settings, "mail_outbox", False)      # the app mailer keeps emails in memory (tests/test_outbox.py turns it on)
    monkeypatch.setattr(settings, "scheduler_lock", False)   # a test start-up never takes (or waits for) the live server's lock
    from app import help as help_center

    monkeypatch.setattr(help_center, "seed_async", lambda: None)   # the app's start-up never writes help content in tests


@pytest.fixture(autouse=True)
def _no_rich_digest(monkeypatch):
    """The rich digest calls the model and Node. Unit tests keep the plain text path unless they patch these
    themselves (tests/test_digest_rich.py does)."""
    from app import digest_rich
    from app.config import settings

    monkeypatch.setattr(settings, "digest_rich_email", False)
    monkeypatch.setattr(digest_rich, "available", lambda: False)


@pytest.fixture(autouse=True)
def _no_working_memory(monkeypatch):
    """.env sets LLM_API_KEY and several tests call respond() against the live database: without this every such turn
    would queue a session_memory job (paid extraction calls, rows for 's1' and 's-ui-*'). tests/test_session_memory.py
    turns it back on explicitly."""
    from app import session_memory
    from app.config import settings

    monkeypatch.setattr(settings, "working_memory", False)
    monkeypatch.setattr(settings, "memory_extract", False)
    monkeypatch.setattr(session_memory, "update_async", lambda *a, **k: None)
    monkeypatch.setattr(session_memory, "catch_up_async", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_learned_score(monkeypatch):
    """The lead score uses its fixed points in tests: corrections learned from real call outcomes in the database
    (app/outcomes.py) never leak in. tests/test_outcomes.py passes `adjust` explicitly."""
    from app import outcomes

    monkeypatch.setattr(outcomes, "adjustments", lambda: {})


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """The DNS check of email domains (app/enrich.py) never reaches the network in tests: dns_status reads 'error' and
    ensure_checked does nothing. Unit tests inject resolve=, and the DB tests stub dns_status and turn it back on."""
    from app.config import settings

    monkeypatch.setattr(settings, "domain_check", False)


@pytest.fixture(autouse=True)
def _no_maxmind(monkeypatch):
    """.env may hold the owner's MaxMind key: no test downloads GeoLite2 or reads a real data/geoip folder.
    tests/test_geoip_update.py sets a fake key and stubs HTTP itself."""
    from app.config import settings

    monkeypatch.setattr(settings, "maxmind_license_key", "")
    monkeypatch.setattr(settings, "maxmind_account_id", "")
