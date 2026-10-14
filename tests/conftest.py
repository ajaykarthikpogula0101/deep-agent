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


@pytest.fixture(autouse=True)
def _no_rich_digest(monkeypatch):
    """The rich digest calls the model and Node. Unit tests keep the plain text path unless they patch these
    themselves (tests/test_digest_rich.py does)."""
    from app import digest_rich
    from app.config import settings

    monkeypatch.setattr(settings, "digest_rich_email", False)
    monkeypatch.setattr(digest_rich, "available", lambda: False)


@pytest.fixture(autouse=True)
def _no_learned_score(monkeypatch):
    """The lead score uses its fixed points in tests: corrections learned from real call outcomes in the database
    (app/outcomes.py) never leak in. tests/test_outcomes.py passes `adjust` explicitly."""
    from app import outcomes

    monkeypatch.setattr(outcomes, "adjustments", lambda: {})
