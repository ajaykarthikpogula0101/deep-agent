"""Knowledge scope (app/knowledge.py): the console switches decide which websites the chatbot reads.

The database tests use a throwaway test tenant with one page of its own; the real tenants and the deependhq.com switch
are never changed (the deependhq.com switch is patched)."""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app import knowledge as K

SOURCES = [
    {"key": "deependhq", "name": "deependhq.com", "host": "deependhq.com", "on": True},
    {"key": "lakeb2b", "name": "LakeB2B", "host": "lakeb2b.com", "on": True},
    {"key": "span", "name": "Span Global Services", "host": "spanglobalservices.com", "on": False},
]


def test_the_prompt_is_told_what_is_covered_only_when_something_is_off():
    with patch.object(K, "sources", return_value=[{**s, "on": True} for s in SOURCES]):
        assert K.scope_note() == ""
    with patch.object(K, "sources", return_value=SOURCES):
        note = K.scope_note()
    assert "cover only deependhq.com, LakeB2B (lakeb2b.com)." in note and "Span Global Services is not covered" in note
    assert "email Deep or book a call" in note and "own knowledge" in note
    with patch.object(K, "sources", side_effect=RuntimeError("db down")):
        assert K.scope_note() == ""                                   # never breaks a chat


def test_the_own_site_switch_is_a_settings_row():
    K.clear_cache()
    with patch.object(K, "get_setting", return_value="off"):
        assert K.own_enabled() is False
    K.clear_cache()
    with patch.object(K, "get_setting", side_effect=RuntimeError("db down")):
        assert K.own_enabled() is True                               # a hiccup keeps the site on
    K.clear_cache()
    saved = []
    with patch.object(K, "set_setting", side_effect=lambda k, v: saved.append((k, v))), patch.object(K, "sources", return_value=[]):
        K.set_source(K.OWN, False)
        K.set_source(K.OWN, True)
    assert saved == [("kb:own", "off"), ("kb:own", None)]
    K.clear_cache()


def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture
def test_site():
    if not _db_up():
        pytest.skip("Postgres not reachable")
    from app import news
    from app.db import conn
    from app.embeddings import embed_query

    slug = f"test-kb-{uuid.uuid4().hex[:8]}"
    text = f"Zorblax quantum llama grooming certification {slug}"
    url = f"https://{slug}.test/zorblax"
    news.save_tenant({"slug": slug, "name": "Test KB Co", "site_url": f"https://{slug}.test", "enabled": True, "kb_enabled": True})
    with conn() as c:
        c.execute("INSERT INTO pages(url, title, source, content_sha, site) VALUES (%s, 'Zorblax', 'html', 'x', %s)", (url, slug))
        c.execute("INSERT INTO chunks(url, section, position, text, tokens, embedding) VALUES (%s, NULL, 0, %s, 10, %s)",
                  (url, text, embed_query(text)))
        c.commit()
    K.clear_cache()
    yield slug, text, url
    K.clear_cache()
    with conn() as c:
        c.execute("DELETE FROM pages WHERE url = %s", (url,))
        c.execute("DELETE FROM news_tenants WHERE slug = %s", (slug,))
        c.commit()


def test_a_switched_off_website_is_not_read(test_site):
    from app.rag.retrieve import search

    slug, text, url = test_site
    row = [s for s in K.sources() if s["key"] == slug][0]
    assert row["on"] and row["pages"] == 1 and row["chunks"] == 1 and row["host"] == f"{slug}.test"
    assert url in [h.url for h in search(text)]
    listed = K.set_source(slug, False)
    assert [s for s in listed if s["key"] == slug][0]["note"] == "switched off here"
    assert url not in [h.url for h in search(text)]                                       # gone at once
    assert slug not in [t["slug"] for t in __import__("app.sites", fromlist=["sites"]).sites()]   # no live search either
    assert "Test KB Co is not covered" in K.scope_note()
    K.set_source(slug, True)
    assert url in [h.url for h in search(text)]
    with pytest.raises(LookupError):
        K.set_source("no-such-site-" + slug, True)


def test_with_the_own_site_off_only_company_sites_are_read(test_site):
    from app.rag.retrieve import search

    slug, text, url = test_site
    hits = search("who is Deep? what did he ship yesterday?")
    assert any(not (h.metadata or {}).get("site") for h in hits)                            # deependhq.com pages, normally
    with patch.object(K, "own_enabled", return_value=False):
        hits = search("who is Deep? what did he ship yesterday?")
        assert all((h.metadata or {}).get("site") or "#dh-help=" in h.url for h in hits)
        assert url in [h.url for h in search(text)]


def test_the_console_endpoints(test_site):
    from fastapi.testclient import TestClient

    from app.main import app

    slug, text, url = test_site
    c = TestClient(app)
    with patch("app.main.settings.admin_token", "test-admin"):
        h = {"X-Admin-Token": "test-admin"}
        assert c.get("/admin/knowledge").status_code == 403
        d = c.get("/admin/knowledge", headers=h).json()
        assert d["sources"][0]["key"] == "deependhq" and any(s["key"] == slug for s in d["sources"])
        t = c.get("/admin/knowledge/test", params={"q": text}, headers=h).json()
        assert t["hits"][0]["url"] == url and t["hits"][0]["site"] == slug
        off = c.post("/admin/knowledge", json={"key": slug, "on": False}, headers=h).json()
        assert not [s for s in off["sources"] if s["key"] == slug][0]["on"] and "Test KB Co" in off["scope_note"]
        assert url not in [x["url"] for x in c.get("/admin/knowledge/test", params={"q": text}, headers=h).json()["hits"]]
        assert c.post("/admin/knowledge", json={"key": "nope-" + slug, "on": True}, headers=h).status_code == 404
