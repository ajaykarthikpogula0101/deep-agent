"""Company websites in the knowledge (app/sites.py): page reading, sitemaps with robots.txt, the incremental index, live
search and the ranking next to deependhq.com's own pages. Database tests use their own tenant (sites-test-…) on a fake
site and delete it afterwards."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import sites as S
from app.rag.retrieve import Hit, confident, rank_sites

MENU = '<header class="top"><nav><a href="/">Home</a><a href="/data">Data</a></nav><div>Products &amp; Access</div><div>How can we help you?</div></header>'
ANSWER = ("LakeB2B builds healthcare email lists of verified physicians, nurses and hospital executives, updated every "
          "quarter and checked by a team of data experts before delivery to marketing teams.")


def page(title, body, header=MENU):
    return (f'<html><head><title>{title} | LakeB2B</title><meta property="og:title" content="{title}"></head><body>{header}'
            f'<main><h1>{title}</h1><p>{body}</p><form>Subscribe to our newsletter today</form></main>'
            f'<footer>Copyright LakeB2B · Privacy · Terms</footer><script>var x = 1;</script></body></html>')


HOME = page("LakeB2B", "Welcome to LakeB2B, the data company that helps marketers reach the right buyers with verified data.")


def test_reading_a_page():
    p = S.extract("https://site.test/hc", page("Healthcare Email Lists", ANSWER))
    assert p["title"] == "Healthcare Email Lists" and "verified physicians" in p["text"]
    assert "Copyright" not in p["text"] and "newsletter today" not in p["text"] and "var x" not in p["text"]
    boiler = {"Products & Access", "How can we help you?", "Home", "Data"}
    bare = page("Short", ANSWER, header="").replace("<main>", "<main><div>Products &amp; Access</div><div>How can we help you?</div>")   # a menu that is no <nav>
    assert "How can we help you?" in S.extract("https://site.test/s", bare)["text"]
    assert "How can we help you?" not in S.extract("https://site.test/s", bare, boiler)["text"]       # dropped as site-wide
    assert S.extract("https://site.test/x", page("Empty", "Too short.")) is None
    faq = S.extract("https://site.test/faq", page("How accurate is your list?", "We guarantee 90 to 95 percent accuracy, verified "
                                                  "through a multi-step validation process for deliverability.", header=""))
    assert faq["text"].startswith("How accurate is your list?")        # the question only in the title is kept with the answer
    whole = f"<html><body><header>{'<p>' + ANSWER + '</p>' * 3}</header></body></html>"   # broken markup: all inside <header>
    assert S.extract("https://site.test/w", whole) is not None


def test_names_keywords_and_mentions():
    t = {"slug": "lakeb2b", "name": "LakeB2B", "mention_query": "LakeB2B", "host": "lakeb2b.com"}
    span = {"slug": "span", "name": "SPAN Global Services", "mention_query": "SPAN Global Services", "host": "spanglobalservices.com"}
    assert {"lakeb2b", "lake b2b", "lakeb2b.com"} <= set(S.aliases(t)) and "span" in S.aliases(span)
    assert S.mentioned("What does Lake B2B charge?", [t, span])["slug"] == "lakeb2b"
    assert S.mentioned("tell me about SPAN's case studies", [t, span])["slug"] == "span"
    assert S.mentioned("who is Deep?", [t, span]) is None and S.mentioned("spanish lessons", [t, span]) is None
    assert S.keywords("What does LakeB2B's healthcare email list cost?", S.aliases(t)) == ["healthcare", "email", "list", "cost"]
    assert "span global" in S.aliases(span) and S.mentioned("span global", [t, span])["slug"] == "span"
    # just the name, or a question about the company as a whole: its profile pages, not a keyword search for "global"
    assert S.general_question("span global", span) and S.general_question("What does LakeB2B do?", t)
    assert S.general_question("tell me about SPAN Global Services and their services", span)
    assert not S.general_question("How accurate is SPAN's healthcare email list?", span)


def test_ranking_next_to_deependhq():
    own = Hit("https://deependhq.com/company/lake-b2b", "Lake B2B", None, "own", 0.70, {})
    site = Hit("https://www.lakeb2b.com/healthcare-email-lists", "Healthcare", None, "site", 0.72, {"site": "lakeb2b"})
    assert rank_sites("anything", [site, own], target=None)[0] is own                 # a close call: deependhq.com's own page
    assert rank_sites("LakeB2B lists", [own, site], target="lakeb2b")[0] is site      # the company named: its site first
    assert rank_sites("x", [own], target=None) == [own]
    assert confident([own, site], floor=0.71)                                         # confidence from the best score, wherever it sits
    from app.rag.retrieve import per_page

    same = [Hit("https://www.lakeb2b.com/x", "X", None, f"part {i}", 0.8 - i / 100, {"site": "lakeb2b"}) for i in range(4)]
    assert [h.text for h in per_page(same + [own])] == ["part 0", "part 1", "own"]   # one long page cannot fill every slot


def fake_get(pages: dict):
    def get(url, params=None, headers=None):
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")
        body = pages.get(key, 404)
        if isinstance(body, int):
            return SimpleNamespace(status_code=body, text="", content=b"", json=lambda: [])
        if isinstance(body, list):
            return SimpleNamespace(status_code=200, text="", content=b"", json=lambda b=body: b)
        return SimpleNamespace(status_code=200, text=body, content=body.encode(), json=lambda: [])
    return get


def urlset(*pairs):
    body = "".join(f"<url><loc>{u}</loc><lastmod>{d}</lastmod></url>" for u, d in pairs)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def index(*children):
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in children)
    return f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'


R = "https://site.test"


def test_sitemaps_follow_indexes_skip_taxonomies_and_honour_robots():
    pages = {R + "/robots.txt": "User-agent: *\nDisallow: /private/\nSitemap: https://site.test/sitemap_index.xml\n",
             R + "/sitemap_index.xml": index(R + "/page-sitemap.xml", R + "/category-sitemap.xml"),
             R + "/page-sitemap.xml": urlset((R + "/a", "2026-10-01T00:00:00+00:00"), (R + "/private/x", "2026-10-01T00:00:00+00:00"),
                                             ("https://other.test/b", "2026-10-01T00:00:00+00:00")),
             R + "/category-sitemap.xml": urlset((R + "/category/c", "2026-10-01T00:00:00+00:00"))}
    assert [u for u, _ in S.sitemap_entries(R, fake_get(pages))] == [R + "/a"]


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
def site():
    from app import news
    from app.db import conn

    slug = f"sites-test-{uuid.uuid4().hex[:8]}"
    news.save_tenant({"slug": slug, "name": "Test Data Co", "site_url": R, "enabled": False})   # never polled for news
    yield {"slug": slug, "name": "Test Data Co", "root": R, "host": "site.test", "mention_query": "Test Data Co"}
    with conn() as c:
        c.execute("DELETE FROM pages WHERE site = %s", (slug,))
        c.execute("DELETE FROM news_tenants WHERE slug = %s", (slug,))
        c.commit()
    S._boiler_cache.pop(R, None)


def _pages(slug):
    from app.db import conn

    with conn() as c:
        return {r[0]: r[1] for r in c.execute("SELECT url, count(ch.id) FROM pages p LEFT JOIN chunks ch USING (url) WHERE p.site = %s GROUP BY url",
                                              (slug,)).fetchall()}


@db
def test_the_index_reads_new_and_changed_pages_only(site):
    old, new = "2026-09-01T00:00:00+00:00", "2026-10-20T00:00:00+00:00"
    pages = {R + "/robots.txt": "User-agent: *\nAllow: /\n", R + "/": HOME,
             R + "/sitemap_index.xml": urlset((R + "/hc", old), (R + "/cs", old), (R + "/gone", old)),
             R + "/hc": page("Healthcare Email Lists", ANSWER), R + "/cs": page("Pharma case study", ANSWER.replace("healthcare", "pharma")),
             R + "/gone": page("Old page", ANSWER.replace("healthcare", "legacy"))}
    calls = []
    get = fake_get(pages)

    def counting(url, **kw):
        calls.append(url)
        return get(url, **kw)
    first = S.index_site(site, get=counting, pause=0)
    assert first["changed"] == 3 and all(n >= 1 for n in _pages(site["slug"]).values())
    calls.clear()
    assert S.index_site(site, get=counting, pause=0)["read"] == 0 and R + "/hc" not in calls   # nothing changed: no page fetched
    pages[R + "/sitemap_index.xml"] = urlset((R + "/hc", new), (R + "/cs", old))                # /hc edited, /gone removed
    pages[R + "/hc"] = page("Healthcare Email Lists", ANSWER + " Now with nurse practitioners too.")
    again = S.index_site(site, get=counting, pause=0)
    assert again == {**again, "read": 1, "changed": 1, "removed": 1} and set(_pages(site["slug"])) == {R + "/hc", R + "/cs"}
    assert S.index_site(site, get=fake_get({**pages, R + "/sitemap_index.xml": urlset()}), pause=0)["removed"] == 0   # an empty sitemap purges nothing


@db
def test_live_search_reads_the_sites_own_search_and_indexes_the_page(site):
    from app.embeddings import embed_query

    pages = {R + "/": HOME, R + "/hc": page("Healthcare Email Lists", ANSWER),
             # 4 words found nothing; the 2 longest did
             R + "/wp-json/wp/v2/search?per_page=6&search=healthcare email": [{"url": R + "/hc", "title": "Healthcare Email Lists"}]}
    q = "Does Test Data Co sell healthcare email lists?"
    hits = S.live_hits(q, embed_query(q), [site], get=fake_get(pages))
    assert hits and hits[0]["url"] == R + "/hc" and hits[0]["metadata"]["site"] == site["slug"] and hits[0]["metadata"]["live"]
    assert R + "/hc" in _pages(site["slug"])                                            # indexed for next time
    assert S.live_hits("hello", embed_query("hello"), [site], get=fake_get(pages)) == []   # nothing to search for


@db
def test_a_question_about_the_company_reads_its_home_and_about_pages(site):
    from app.embeddings import embed_query

    about = page("About Us", "Test Data Co was founded in 2009 and builds verified B2B and healthcare data for marketing teams worldwide.")
    pages = {R + "/": page("Test Data Co", ANSWER), R + "/about-us/": about, R + "/about/": about}
    q = "Test Data Co"
    hits = S.live_hits(q, embed_query(q), [site], get=fake_get(pages))
    assert {h["url"] for h in hits} == {R + "/", R + "/about-us/"}                      # /about/ is the same page: read once
    from app.db import conn

    with conn() as c:
        rows = S.profile_rows(c, site)
    assert {r[0] for r in rows} >= {R + "/"}                                            # indexed, so the next question pins it
