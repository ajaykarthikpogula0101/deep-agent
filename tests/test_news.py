"""News (app/news.py): feed parsing, the sitemap diff, mentions held for approval, pins and the 30-day / 20-item cap.
Database tests run on their own tenant (news-test-…) with fake feeds, and delete it afterwards."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import news as N

BLOG = b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Blog</title>
<item><title><![CDATA[What Is an AI SDR? &amp; Why Data Matters]]></title><link>https://www.lakeb2b.com/blog/ai-sdr/</link>
<pubDate>Tue, 20 Oct 2026 07:00:00 +0000</pubDate>
<description><![CDATA[<p>Your AI SDR sent 2,000 emails before lunch.</p><p>The post <a href="x">What Is</a> appeared first on <a href="y">LakeB2B</a>.</p>]]></description>
<content:encoded><![CDATA[<p><img src="https://www.lakeb2b.com/img/sdr.webp" alt=""> Body</p>]]></content:encoded></item>
<item><title>No link</title></item>
</channel></rss>"""

YT = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><title>The Secret to Campaigns That Actually Convert</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
<published>2026-10-28T19:21:23+00:00</published><media:group><media:description>Are your campaigns falling flat?</media:description>
<media:thumbnail url="https://i4.ytimg.com/vi/abc/hqdefault.jpg" width="480" height="360"/></media:group></entry></feed>"""

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://site.test/page-sitemap.xml</loc></sitemap><sitemap><loc>https://site.test/case_studies-sitemap.xml</loc></sitemap>
<sitemap><loc>https://site.test/webinar-sitemap.xml</loc></sitemap></sitemapindex>"""


def urlset(*pairs):
    body = "".join(f"<url><loc>{u}</loc><lastmod>{d}</lastmod></url>" for u, d in pairs)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'.encode()


PAGE = """<html><head><title>How LakeB2B helped a pharma brand | LakeB2B</title>
<meta property="og:description" content="A high-engagement HCP email program &amp; more."><meta property="og:image" content="https://site.test/cs.png"></head></html>"""


def test_blog_rss_items():
    items = N.parse_rss(BLOG)
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "What Is an AI SDR? & Why Data Matters" and it["url"] == "https://www.lakeb2b.com/blog/ai-sdr/"
    assert it["published_at"] == datetime(2026, 10, 20, 7, tzinfo=timezone.utc)
    assert it["blurb"] == "Your AI SDR sent 2,000 emails before lunch." and it["image"] == "https://www.lakeb2b.com/img/sdr.webp"


def test_youtube_sitemaps_page_meta_and_mentions():
    v = N.parse_youtube(YT)[0]
    assert v["url"].endswith("v=abc") and v["image"].endswith("hqdefault.jpg") and v["blurb"] == "Are your campaigns falling flat?"
    kids = N.parse_sitemap(INDEX)
    assert [N.sitemap_type(u) for u, _ in kids] == ["page", "case_studies", "webinar"]
    assert N.parse_sitemap(urlset(("https://site.test/a", "2026-10-20T07:00:00+00:00")))[0][1].day == 20
    m = N.page_meta(PAGE)
    assert m == {"title": "How LakeB2B helped a pharma brand", "blurb": "A high-engagement HCP email program & more.", "image": "https://site.test/cs.png"}
    assert N.bing_target("https://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=x&url=https%3a%2f%2fpress.test%2fstory&c=1") == "https://press.test/story"
    assert N.mentions_term({"title": "LakeB2B wins award"}, '"LakeB2B"') and N.mentions_term({"title": "x", "blurb": "says lakeb2b."}, "LakeB2B")
    assert not N.mentions_term({"title": "Chris Lake b2b set"}, "LakeB2B")                  # the DJ sets Google returns
    assert not N.mentions_term({"title": "LakeB2Bx launches"}, "LakeB2B") and not N.mentions_term({"title": "x"}, "")
    assert N.text_of("<p>a &amp; b</p>" + "word " * 100, limit=30).endswith("…")


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
def tenant():
    slug = f"news-test-{uuid.uuid4().hex[:8]}"
    t = N.save_tenant({"slug": slug, "name": "Test Co", "blog_feed_url": "https://site.test/blog/feed/", "youtube_channel_id": "UCtest",
                       "mention_query": "LakeB2B", "sitemap_index_url": "https://site.test/sitemap_index.xml",
                       "sitemap_types": "case_studies, webinar"})
    yield t
    from app.db import conn

    with conn() as c:
        c.execute("DELETE FROM news_sitemap_seen WHERE tenant = %s", (slug,))
        c.execute("DELETE FROM news_tenants WHERE slug = %s", (slug,))   # items go with it (ON DELETE CASCADE)
        c.commit()


def fake_get(pages: dict):
    def get(url):
        body = pages[url]
        return SimpleNamespace(content=body if isinstance(body, bytes) else body.encode(), text=body if isinstance(body, str) else body.decode(),
                               status_code=200)
    return get


@db
def test_blog_and_youtube_publish_and_the_feed_is_ordered(tenant):
    get = fake_get({"https://site.test/blog/feed/": BLOG, "https://www.youtube.com/feeds/videos.xml?channel_id=UCtest": YT})
    now = datetime.now(timezone.utc)
    blog = N.parse_rss(BLOG)[0]
    N.upsert(tenant["slug"], "blog", "post", {**blog, "published_at": now - timedelta(days=2)})
    assert N.poll_youtube(tenant, get=get) == 1 and N.poll_youtube(tenant, get=get) == 0        # deduplicated on url
    N.upsert(tenant["slug"], "blog", "post", {"title": "Old post", "url": "https://site.test/old", "published_at": now - timedelta(days=45)})
    items = N.published(tenant["slug"])
    assert [i["kind"] for i in items] == ["video", "post"] and items[0]["label"] == "Video"            # newest first, the 45-day-old one dropped
    old = [i for i in N.admin_items(tenant["slug"]) if i["title"] == "Old post"][0]
    assert N.moderate(old["id"], pinned=True)
    assert N.published(tenant["slug"])[0]["title"] == "Old post"                                      # pinned: on top, despite its age
    assert N.moderate(old["id"], status="hidden") and "Old post" not in [i["title"] for i in N.published(tenant["slug"])]
    with pytest.raises(ValueError):
        N.moderate(old["id"], status="bogus")
    assert len(N.published(tenant["slug"], limit=1)) == 1


@db
def test_mentions_wait_for_approval(tenant):
    rss = b"""<rss><channel><item><title>LakeB2B named a top data vendor</title><link>https://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fpress.test%2fa&amp;c=1</link>
      <pubDate>Wed, 28 Oct 2026 10:00:00 GMT</pubDate><description>Coverage of LakeB2B.</description></item>
      <item><title>Chris Lake b2b DJ set</title><link>https://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fdj.test%2fb</link><description>music</description></item></channel></rss>"""
    get = fake_get({'https://www.bing.com/news/search?q=%22LakeB2B%22&format=rss': rss})
    assert N.poll_mentions(tenant, get=get) == 1                                                    # the DJ set is filtered out
    item = N.admin_items(tenant["slug"], status="pending")[0]
    assert item["url"] == "https://press.test/a" and item["kind"] == "mention"
    assert N.published(tenant["slug"]) == []                                                        # not shown until approved
    N.moderate(item["id"], status="published")
    assert N.published(tenant["slug"])[0]["label"] == "In the news"


@db
def test_sitemaps_first_run_is_a_baseline_then_changes_become_items(tenant):
    now = datetime.now(timezone.utc)
    recent, old = (now - timedelta(days=3)).isoformat(), (now - timedelta(days=200)).isoformat()
    pages = {"https://site.test/sitemap_index.xml": INDEX,
             "https://site.test/case_studies-sitemap.xml": urlset(("https://site.test/cs/old", old), ("https://site.test/cs/new", recent)),
             "https://site.test/webinar-sitemap.xml": urlset(("https://site.test/web/1", old)),
             "https://site.test/cs/new": PAGE, "https://site.test/cs/old": PAGE, "https://site.test/cs/added": PAGE,
             "https://site.test/web/1": PAGE}
    assert N.poll_sitemaps(tenant, get=fake_get(pages)) == 1                         # first run: only the recently changed page
    item = N.admin_items(tenant["slug"])[0]
    assert item["kind"] == "case_studies" and item["title"] == "How LakeB2B helped a pharma brand" and item["label"] == "Case study"
    assert N.poll_sitemaps(tenant, get=fake_get(pages)) == 0                         # nothing changed since
    later = (now - timedelta(hours=1)).isoformat()
    pages["https://site.test/case_studies-sitemap.xml"] = urlset(("https://site.test/cs/old", later), ("https://site.test/cs/new", recent),
                                                                 ("https://site.test/cs/added", later))
    assert N.poll_sitemaps(tenant, get=fake_get(pages)) == 2                         # the edited old page and the added one
    assert "page" not in {i["kind"] for i in N.admin_items(tenant["slug"])}          # types not chosen are never read


@db
def test_publish_a_post_by_hand(tenant):
    item = N.publish_manual(tenant["slug"], "https://www.linkedin.com/posts/lakeb2b_launch", kind="linkedin", title="We launched Lake Sonar",
                            blurb="Now live.", pinned=True, get=lambda url: SimpleNamespace(status_code=999, text=""))
    top = N.published(tenant["slug"])[0]
    assert top["id"] == item["id"] and top["pinned"] and top["kind"] == "linkedin" and top["label"] == "LinkedIn"
    with pytest.raises(ValueError):
        N.publish_manual(tenant["slug"], "https://x.com/lakeb2b/status/1", kind="x", get=lambda url: SimpleNamespace(status_code=403, text=""))
    with pytest.raises(ValueError):
        N.publish_manual(tenant["slug"], "not a link")
    with pytest.raises(LookupError):
        N.publish_manual("no-such-tenant", "https://site.test/x", title="x")


def test_api(monkeypatch):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    with patch("app.main.news.tenant", return_value={"slug": "lakeb2b", "name": "LakeB2B", "enabled": True}), \
            patch("app.main.news.published", return_value=[{"id": 1, "title": "A"}]):
        c = TestClient(app)
        d = c.get("/news").json()
        assert d["tenant"] == settings.news_tenant and d["items"][0]["title"] == "A"
        assert c.get("/admin/news").status_code in (401, 403)
        monkeypatch.setattr(settings, "news_enabled", False)
        assert c.get("/news").status_code == 404
