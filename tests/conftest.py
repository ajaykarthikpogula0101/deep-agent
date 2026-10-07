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
