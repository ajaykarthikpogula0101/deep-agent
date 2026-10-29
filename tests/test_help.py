"""Help center (app/help.py, docs/ROADMAP.md step 3): site pages turned into articles, the API, search, the console's
edits, and owner articles feeding the answers. Database tests only touch rows they create, and delete them."""
from __future__ import annotations

import uuid

import pytest

from app import help as H
from app.config import settings


# ---------------------------------------------------------------- pure: site pages -> articles
def test_company_page_becomes_an_article():
    text = ("Lake B2B — The B2B growth stack. Data, demand, delivery.\n\nTag: Data & Services\n\nPillar: lakeb2b\n\n"
            "Products: Lake Current, Lake Stream\n\nWebsite: https://www.lakeb2b.com")
    a = H.company_article("Lake B2B", text, "https://deependhq.com/company/lake-b2b")
    assert a["title"] == "Lake B2B" and a["summary"] == "The B2B growth stack. Data, demand, delivery."
    assert "- **Products:** Lake Current, Lake Stream" in a["body"] and "[www.lakeb2b.com](https://www.lakeb2b.com)" in a["body"]
    assert a["pillar"] == "lakeb2b" and a["source_url"].endswith("/lake-b2b")
    assert H.company_article("X", "", "u") is None


def test_toolkit_and_now_pages_are_parsed():
    tools = H.toolkit_items("title: ChampBeam\ndescription: Smart links and QR codes.\nurl: https://github.com/x\ncategory: tool\n"
                            "title: Deep Scanner\ndescription: Checks folders before upload.\ntitle: Empty\n")
    assert [t["title"] for t in tools] == ["ChampBeam", "Deep Scanner"] and tools[0]["url"] == "https://github.com/x"
    updated, pairs = H.now_items("updated: 2026-06-12\nnote: x\nfocus:\nk: SHIPPING\ntext: The site publishes itself.\nk: HIRING\ntext: A Chief Campaign Officer.")
    assert updated == "2026-06-12" and pairs == [("Shipping", "The site publishes itself."), ("Hiring", "A Chief Campaign Officer.")]


def test_slugs_and_article_links(monkeypatch):
    monkeypatch.setattr(settings, "site_base_url", "https://deependhq.com")
    assert H.slugify("How do I book a call with Deep?") == "how-do-i-book-a-call-with-deep"
    assert H.slugify("!!!") == "article"
    assert H.article_url("who-is-deep") == "https://deependhq.com/#dh-help=who-is-deep"


def test_builtin_articles_cover_booking_and_the_assistant():
    titles = [b[1] for b in H.BUILTIN]
    assert "How do I reschedule or cancel my call?" in titles and "How do I talk to a person?" in titles
    assert {b[0] for b in H.BUILTIN} <= {c[0] for c in H.COLLECTIONS}


# ---------------------------------------------------------------- database
def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


db = pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")


@pytest.fixture
def mine():
    """A test collection with one owner article; removed afterwards (the real help content is never touched)."""
    tag = uuid.uuid4().hex[:8]
    col = H.save_collection({"title": f"Test collection {tag}", "description": "for tests", "position": 99})
    art = H.save_article({"title": f"How do I get the zqx{tag} sample list?", "summary": "Ask for it in the chat.",
                          "body": f"Send **zqx{tag}** requests to the team.\n\n- one\n- two", "author": "Test",
                          "collection_id": col["id"], "published": True})
    yield {"tag": tag, "col": col, "art": art}
    from app.db import conn

    with conn() as c:
        c.execute("DELETE FROM help_articles WHERE collection_id = %s OR title LIKE %s", (col["id"], f"%{tag}%"))
        c.execute("DELETE FROM help_collections WHERE id = %s", (col["id"],))
        c.commit()


@db
def test_collection_article_and_view_count(mine):
    c = H.collection(mine["col"]["slug"])
    assert c["title"].startswith("Test collection") and [a["slug"] for a in c["articles"]] == [mine["art"]["slug"]]
    assert c["authors"] == ["Test"]
    a = H.article(mine["art"]["slug"])
    assert a["title"] == mine["art"]["title"] and a["collection"]["slug"] == mine["col"]["slug"] and "#dh-help=" in a["url"]
    H.article(mine["art"]["slug"])
    listed = {x["id"]: x for x in H.admin_list()["articles"]}
    assert listed[mine["art"]["id"]]["views"] == 2 and listed[mine["art"]["id"]]["source"] == "owner"
    assert H.article("no-such-article-" + mine["tag"]) is None and H.collection("no-such-" + mine["tag"]) is None


@db
def test_search_finds_by_meaning_and_title(mine):
    hits = H.search(f"zqx{mine['tag']} sample list")
    assert hits and hits[0]["slug"] == mine["art"]["slug"]
    assert H.search("") == []


@db
def test_unpublished_articles_are_hidden_and_edits_keep_the_slug(mine):
    a = H.save_article({**mine["art"], "title": mine["art"]["title"], "published": False}, mine["art"]["id"])
    assert a["slug"] == mine["art"]["slug"]
    assert H.article(mine["art"]["slug"]) is None and H.collection(mine["col"]["slug"])["articles"] == []
    with pytest.raises(ValueError):
        H.save_article({"title": "  "})
    with pytest.raises(LookupError):
        H.save_article({"title": "x"}, 10 ** 12)


@db
def test_editing_a_site_article_makes_it_the_owners(mine):
    from app.db import conn

    with conn() as c:
        aid = c.execute("""INSERT INTO help_articles(slug, title, summary, body, source) VALUES (%s, %s, '', 'b', 'site') RETURNING id""",
                        (f"site-{mine['tag']}", f"Site page {mine['tag']}")).fetchone()[0]
        c.commit()
    out = H.save_article({"title": f"Site page {mine['tag']} (edited)", "body": "mine now"}, aid)
    assert {x["id"]: x for x in H.admin_list()["articles"]}[aid]["source"] == "owner" and out["slug"] == f"site-{mine['tag']}"
    assert H.delete_article(aid) and not H.delete_article(aid)


@db
def test_owner_articles_feed_the_answers(mine):
    from app.embeddings import embed_query

    hits = H.retrieval_hits(embed_query(f"how do I get the zqx{mine['tag']} sample list"), k=3)
    mine_hit = [h for h in hits if h["metadata"]["slug"] == mine["art"]["slug"]]
    assert mine_hit and mine_hit[0]["url"].endswith("#dh-help=" + mine["art"]["slug"]) and "zqx" in mine_hit[0]["text"]


def test_api_endpoints(monkeypatch):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    with patch("app.main.help_center.overview", return_value={"collections": [], "top": []}), \
            patch("app.main.help_center.article", return_value=None), \
            patch("app.main.help_center.search", return_value=[{"slug": "a", "title": "A", "summary": "", "id": 1, "score": 0.9}]):
        c = TestClient(app)
        assert c.get("/help").json() == {"collections": [], "top": []}
        assert c.get("/help/articles/nope").status_code == 404
        assert c.get("/help/search?q=cancel").json()["items"][0]["slug"] == "a"
        assert c.get("/admin/help").status_code in (401, 403)       # the console list needs the admin token
        monkeypatch.setattr(settings, "help_enabled", False)
        assert c.get("/help").status_code == 404
