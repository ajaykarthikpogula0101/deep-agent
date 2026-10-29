"""News (the messenger's News tab, like Intercom's): first-party posts, videos, pinned announcements and approved
press mentions, per tenant (docs/ROADMAP.md, spec from 2026-10-29).

Tenants (news_tenants): blog_feed_url, youtube_channel_id, mention_query, sitemap_index_url and the sitemap types to
show. LakeB2B is tenant one; SPAN and deependhq are added in Console -> News with their own values.

Sources, one item shape (source, kind, title, url, published_at, blurb, image):
  blog      the WordPress blog RSS (/blog/feed/; the root /feed is empty), hourly, kind 'post', auto-published
  sitemap   the typed child sitemaps of sitemap_index.xml (news, case_studies, webinar, guide, white_paper, ...),
            hourly: lastmod is diffed against the last run (news_sitemap_seen); a new or changed URL becomes an item of
            kind = its type, titled from the page's og:title/description/image. The first run only records what exists
            (plus anything changed in the last NEWS_DAYS), so the tab never fills with years-old pages. Auto-published.
  youtube   the channel's RSS (no key), daily, kind 'video', auto-published
  mention   Bing News RSS for mention_query, daily, kind 'mention': kept only when the exact term is in the title or
            text, and held as 'pending' until approved in the console (Google News is skipped: it returns DJ sets)
  manual    "Publish to the news" in the console: a LinkedIn / X post, a launch or an event; can be pinned on top

GET /news returns the published items newest first (pinned first), deduplicated on URL, from the last NEWS_DAYS (30)
and at most NEWS_LIMIT (20). Pinned items ignore the 30 days.

Dynamic checking (NEWS_DYNAMIC, the default; off = the fixed hourly / daily runs above). One job every NEWS_TICK_MINUTES
(5) checks each tenant's sources that are due (news_sources):
  cadence   a source that just changed is checked again at its fastest; each quiet check waits 1.5x longer, up to its
            slowest; a failing one backs off (CADENCE: blog 15 min-2 h, sitemaps 30 min-4 h, YouTube 30 min-6 h,
            mentions 6-24 h, links 12-24 h)
  cheap     each feed is fetched with the ETag / Last-Modified it sent last time (news_fetch_cache); a 304, or the same
            bytes again, ends the check without parsing anything
  changes   an item is only rewritten when its title, text, picture or dates changed, so updated_at marks a real edit;
            a page re-saved after it was listed shows "Updated" in the tab
  removals  a page dropped from its sitemap, or a link that now answers 404 / 410 (a video YouTube no longer has), is
            taken off as 'gone'; it comes back by itself if it returns
discover() finds a new website's sources (blog RSS, sitemap index and types, YouTube channel, name) for Console -> News.
"""
from __future__ import annotations

import hashlib
import html as htmlmod
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx

from app.config import settings
from app.db import conn

log = logging.getLogger("news")

UA = "Mozilla/5.0 (compatible; deependhq-assistant/1.0; +https://deependhq.com)"
NS = {"content": "http://purl.org/rss/1.0/modules/content/", "media": "http://search.yahoo.com/mrss/",
      "atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
KIND_LABEL = {"post": "Blog", "video": "Video", "mention": "In the news", "news": "News", "case_studies": "Case study",
              "webinar": "Webinar", "guide": "Guide", "white_paper": "White paper", "research_paper": "Research",
              "infographic": "Infographic", "tip_sheet": "Tip sheet", "newsletter": "Newsletter", "insights": "Insights",
              "announcement": "Announcement", "event": "Event", "linkedin": "LinkedIn", "x": "X"}
LAKEB2B = {"slug": "lakeb2b", "name": "LakeB2B", "blog_feed_url": "https://www.lakeb2b.com/blog/feed/",
           "youtube_channel_id": "UCAzbDvKA8n6bwwSZ6OC9C5g", "mention_query": "LakeB2B",
           "sitemap_index_url": "https://www.lakeb2b.com/sitemap_index.xml",
           "sitemap_types": ["news", "case_studies", "webinar", "guide", "white_paper", "research_paper", "infographic",
                             "tip_sheet", "newsletter", "insights"]}
# minutes between checks, (fastest, slowest): fastest right after a change, slower while a source stays quiet
CADENCE = {"blog": (15, 120), "sitemap": (30, 240), "youtube": (30, 360), "mention": (360, 1440), "links": (720, 1440)}
SOURCES = tuple(CADENCE)
ITEM_SOURCE = {"blog": "blog", "sitemap": "sitemap", "youtube": "youtube", "mention": "bing"}   # news_items.source
# sitemap types that are not news: plain pages, blog posts (the RSS has them), taxonomies and theme parts
SKIP_TYPES = {"page", "post", "category", "post_tag", "tag", "author", "attachment", "product", "product_cat", "product_tag",
              "local", "elementor_library", "e-landing-page", "wp_block", "nav_menu_item", "testimonial", "faq", "team",
              "home_slider", "client", "our_capability", "process_document"}


# ---------------------------------------------------------------- parsing (pure, unit-tested)
def text_of(html_text: str | None, limit: int = 220) -> str:
    """Plain text from feed HTML: tags and entities gone, whitespace collapsed, cut on a word."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text or "", flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", htmlmod.unescape(t)).strip()
    t = re.sub(r"\s*The post .* appeared first on .*$", "", t)   # WordPress feed footer
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return t


def _date(s: str | None) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _first_img(html_text: str | None) -> str | None:
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", html_text or "", re.I)
    return htmlmod.unescape(m.group(1)) if m else None


def parse_rss(xml: bytes | str) -> list[dict[str, Any]]:
    """RSS 2.0 items: title, url, published_at, blurb, image (media:content, enclosure or the first <img>)."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = it.findtext("description") or ""
        full = it.findtext("content:encoded", namespaces=NS) or ""
        img = None
        m = it.find("media:content", NS)
        if m is None:
            m = it.find("media:thumbnail", NS)
        if m is not None:
            img = m.get("url")
        enc = it.find("enclosure")
        if not img and enc is not None and (enc.get("type") or "").startswith("image"):
            img = enc.get("url")
        img = img or _first_img(full) or _first_img(desc)
        news_img = next((c.text for c in it if c.tag.endswith("}Image") and c.text), None)   # Bing: <News:Image>
        if title and link:
            out.append({"title": htmlmod.unescape(title), "url": link, "published_at": _date(it.findtext("pubDate")),
                        "blurb": text_of(desc or full), "image": img or news_img})
    return out


def parse_youtube(xml: bytes | str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    out = []
    for e in root.findall("atom:entry", NS):
        link = e.find("atom:link[@rel='alternate']", NS)
        thumb = e.find("media:group/media:thumbnail", NS)
        out.append({"title": (e.findtext("atom:title", namespaces=NS) or "").strip(),
                    "url": link.get("href") if link is not None else "",
                    "published_at": _date(e.findtext("atom:published", namespaces=NS)),
                    "blurb": text_of(e.findtext("media:group/media:description", namespaces=NS)),
                    "image": thumb.get("url") if thumb is not None else None})
    return [x for x in out if x["title"] and x["url"]]


def parse_sitemap(xml: bytes | str) -> list[tuple[str, datetime | None]]:
    """(loc, lastmod) of a sitemap, or the child sitemaps of a sitemap index."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    out = []
    for node in list(root.findall("sm:url", NS)) + list(root.findall("sm:sitemap", NS)):
        loc = (node.findtext("sm:loc", namespaces=NS) or "").strip()
        if loc:
            out.append((loc, _date(node.findtext("sm:lastmod", namespaces=NS))))
    return out


def sitemap_type(child_url: str) -> str | None:
    """'https://www.lakeb2b.com/case_studies-sitemap.xml' -> 'case_studies'."""
    m = re.search(r"/([a-z0-9_]+)-sitemap\d*\.xml$", child_url)
    return m.group(1) if m else None


def page_meta(html_text: str) -> dict[str, str | None]:
    """og:title / <title>, og:description / description, og:image of a page."""
    def meta(*names):
        for n in names:
            m = re.search(rf"<meta[^>]+(?:property|name)=[\"']{re.escape(n)}[\"'][^>]*content=[\"']([^\"']*)[\"']", html_text, re.I) \
                or re.search(rf"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"']{re.escape(n)}[\"']", html_text, re.I)
            if m and m.group(1).strip():
                return htmlmod.unescape(m.group(1).strip())
        return None
    title = meta("og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
        title = htmlmod.unescape(m.group(1).strip()) if m else None
    if title:
        title = re.sub(r"\s*[|–-]\s*(LakeB2B|Lake B2B|SPAN Global Services)\s*$", "", title).strip()
    return {"title": title, "blurb": text_of(meta("og:description", "description", "twitter:description")),
            "image": meta("og:image", "twitter:image")}


def bing_target(link: str) -> str:
    """Bing News links go through apiclick.aspx?…&url=<article>: keep the article's own URL."""
    q = parse_qs(urlparse(link).query)
    return q.get("url", [link])[0]


def mentions_term(item: dict[str, Any], query: str) -> bool:
    """A mention counts only when the exact token (e.g. LakeB2B, any case) is in its title or text: "Chris Lake b2b"
    is a DJ set, not the company."""
    term = query.strip().strip('"').strip()
    if not term:
        return False
    rx = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(map(re.escape, term.split())) + r"(?![A-Za-z0-9])", re.I)
    return bool(rx.search(f"{item.get('title', '')} {item.get('blurb', '')}"))


# ---------------------------------------------------------------- tenants and items (database)
def _client() -> httpx.Client:
    return httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": UA})


def tenants(enabled_only: bool = False) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("""SELECT slug, name, blog_feed_url, youtube_channel_id, mention_query, sitemap_index_url, sitemap_types, enabled
                            FROM news_tenants """ + ("WHERE enabled " if enabled_only else "") + "ORDER BY created_at").fetchall()
    cols = ["slug", "name", "blog_feed_url", "youtube_channel_id", "mention_query", "sitemap_index_url", "sitemap_types", "enabled"]
    return [dict(zip(cols, r)) for r in rows]


def tenant(slug: str) -> dict[str, Any] | None:
    return next((t for t in tenants() if t["slug"] == slug), None)


def save_tenant(data: dict[str, Any]) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9-]+", "-", (data.get("slug") or "").lower()).strip("-")[:40]
    if not slug:
        raise ValueError("slug is required")
    types = data.get("sitemap_types") or []
    if isinstance(types, str):
        types = [t.strip() for t in types.split(",") if t.strip()]
    vals = (slug, (data.get("name") or slug).strip()[:80], (data.get("blog_feed_url") or "").strip() or None,
            (data.get("youtube_channel_id") or "").strip() or None, (data.get("mention_query") or "").strip() or None,
            (data.get("sitemap_index_url") or "").strip() or None, types, bool(data.get("enabled", True)))
    with conn() as c:
        c.execute("""INSERT INTO news_tenants(slug, name, blog_feed_url, youtube_channel_id, mention_query, sitemap_index_url, sitemap_types, enabled)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, blog_feed_url = EXCLUDED.blog_feed_url,
                       youtube_channel_id = EXCLUDED.youtube_channel_id, mention_query = EXCLUDED.mention_query,
                       sitemap_index_url = EXCLUDED.sitemap_index_url, sitemap_types = EXCLUDED.sitemap_types,
                       enabled = EXCLUDED.enabled, updated_at = now()""", vals)
        c.commit()
    return tenant(slug)


def seed() -> bool:
    """LakeB2B as tenant one, once (settings key news:seeded). Never overwrites console edits."""
    with conn() as c:
        if c.execute("SELECT 1 FROM settings WHERE key = 'news:seeded'").fetchone():
            return False
        c.execute("INSERT INTO settings(key, value) VALUES ('news:seeded', 'true') ON CONFLICT (key) DO NOTHING")
        c.commit()
    if not tenant(LAKEB2B["slug"]):
        save_tenant(LAKEB2B)
    return True


def upsert(tenant_slug: str, source: str, kind: str, item: dict[str, Any], status: str = "published",
           lastmod: datetime | None = None) -> bool:
    """Insert or refresh one item (title, blurb, image, date); its status and pin are kept, except that an item taken
    off as 'gone' is published again. A row whose content did not change is left alone, so updated_at marks a real
    change. True when new."""
    if not item.get("url") or not item.get("title"):
        return False
    when = item.get("published_at")
    with conn() as c:
        row = c.execute(
            """INSERT INTO news_items(tenant, source, kind, title, url, published_at, blurb, image, status, lastmod)
               VALUES (%s, %s, %s, %s, %s, COALESCE(%s::timestamptz, now()), %s, %s, %s, %s)
               ON CONFLICT (tenant, url) DO UPDATE SET title = EXCLUDED.title, blurb = COALESCE(NULLIF(EXCLUDED.blurb, ''), news_items.blurb),
                 image = COALESCE(EXCLUDED.image, news_items.image),
                 published_at = COALESCE(%s::timestamptz, news_items.published_at),
                 lastmod = COALESCE(EXCLUDED.lastmod, news_items.lastmod),
                 status = CASE WHEN news_items.status = 'gone' THEN 'published' ELSE news_items.status END, updated_at = now()
               WHERE news_items.status = 'gone' OR news_items.title IS DISTINCT FROM EXCLUDED.title
                  OR (EXCLUDED.blurb <> '' AND news_items.blurb IS DISTINCT FROM EXCLUDED.blurb)
                  OR (EXCLUDED.image IS NOT NULL AND news_items.image IS DISTINCT FROM EXCLUDED.image)
                  OR (%s::timestamptz IS NOT NULL AND news_items.published_at IS DISTINCT FROM %s::timestamptz)
                  OR (EXCLUDED.lastmod IS NOT NULL AND news_items.lastmod IS DISTINCT FROM EXCLUDED.lastmod)
               RETURNING (xmax = 0)""",
            (tenant_slug, source, kind, item["title"][:300], item["url"][:1000], when,
             (item.get("blurb") or "")[:600], (item.get("image") or None), status, lastmod, when, when, when)).fetchone()
        c.commit()
    return bool(row and row[0])


# ---------------------------------------------------------------- fetching only what changed
def _fetch(get: Callable, url: str, tenant_slug: str | None = None) -> Any:
    """GET a feed. With a tenant (the dynamic checks), the ETag / Last-Modified saved last time go along and None comes
    back when the feed has not changed: a 304, or the same bytes as last time. _remember() saves the new ones once the
    body has been used, so a check that fails half-way is repeated in full next time."""
    if not tenant_slug:
        return get(url)
    with conn() as c:
        row = c.execute("SELECT etag, last_modified, body_hash FROM news_fetch_cache WHERE tenant = %s AND url = %s",
                        (tenant_slug, url)).fetchone()
    headers = {k: v for k, v in (("If-None-Match", row and row[0]), ("If-Modified-Since", row and row[1])) if v}
    r = get(url, headers=headers) if headers else get(url)
    code = getattr(r, "status_code", 200)
    if code == 304:
        return None
    if code >= 400:
        raise RuntimeError(f"{url} answered {code}")
    if row and row[2] and row[2] == hashlib.sha1(r.content).hexdigest():
        return None
    return r


def _remember(tenant_slug: str | None, url: str, r: Any) -> None:
    if not tenant_slug or r is None:
        return
    h = getattr(r, "headers", None) or {}
    with conn() as c:
        c.execute("""INSERT INTO news_fetch_cache(tenant, url, etag, last_modified, body_hash, checked_at) VALUES (%s, %s, %s, %s, %s, now())
                     ON CONFLICT (tenant, url) DO UPDATE SET etag = EXCLUDED.etag, last_modified = EXCLUDED.last_modified,
                       body_hash = EXCLUDED.body_hash, checked_at = now()""",
                  (tenant_slug, url, h.get("etag") or h.get("ETag"), h.get("last-modified") or h.get("Last-Modified"),
                   hashlib.sha1(r.content).hexdigest()))
        c.commit()


# ---------------------------------------------------------------- polling
def _stored_urls(tenant_slug: str, urls: list[str]) -> set[str]:
    with conn() as c:
        return {r[0] for r in c.execute("SELECT url FROM news_items WHERE tenant = %s AND url = ANY(%s)", (tenant_slug, urls)).fetchall()}


def poll_blog(t: dict[str, Any], get: Callable | None = None, cache: bool = False) -> int:
    if not t.get("blog_feed_url"):
        return 0
    get = get or _client().get
    key = t["slug"] if cache else None
    r = _fetch(get, t["blog_feed_url"], key)
    if r is None:
        return 0
    items = parse_rss(r.content)
    known = _stored_urls(t["slug"], [it["url"] for it in items])
    for it in items:   # WordPress feeds carry no picture: a new post takes its page's og:image
        if not it.get("image") and it["url"] not in known:
            try:
                it["image"] = page_meta(get(it["url"]).text)["image"]
            except Exception as e:
                log.info("news: no image for %s (%s)", it["url"], e)
    new = sum(upsert(t["slug"], "blog", "post", it) for it in items)
    _remember(key, t["blog_feed_url"], r)
    return new


def poll_youtube(t: dict[str, Any], get: Callable | None = None, cache: bool = False) -> int:
    if not t.get("youtube_channel_id"):
        return 0
    get = get or _client().get
    key, url = t["slug"] if cache else None, f"https://www.youtube.com/feeds/videos.xml?channel_id={t['youtube_channel_id']}"
    r = _fetch(get, url, key)
    if r is None:
        return 0
    new = sum(upsert(t["slug"], "youtube", "video", it) for it in parse_youtube(r.content))
    _remember(key, url, r)
    return new


def poll_mentions(t: dict[str, Any], get: Callable | None = None, cache: bool = False) -> int:
    """Bing News for the mention query; every mention waits for approval in the console."""
    q = (t.get("mention_query") or "").strip()
    if not q:
        return 0
    get = get or _client().get
    key, url = t["slug"] if cache else None, f"https://www.bing.com/news/search?q={quote(chr(34) + q.strip(chr(34)) + chr(34))}&format=rss"
    r = _fetch(get, url, key)
    if r is None:
        return 0
    new = 0
    for it in parse_rss(r.content):
        it["url"] = bing_target(it["url"])
        if mentions_term(it, q):
            new += upsert(t["slug"], "bing", "mention", it, status="pending")
    _remember(key, url, r)
    return new


def poll_sitemaps(t: dict[str, Any], get: Callable | None = None, now: datetime | None = None, cache: bool = False) -> int:
    """New or changed URLs in the chosen typed sitemaps become items (kind = the type). First run: baseline only.
    A URL dropped from its sitemap takes its item off as 'gone'."""
    if not t.get("sitemap_index_url") or not t.get("sitemap_types"):
        return 0
    get = get or _client().get
    now = now or datetime.now(timezone.utc)
    recent = now - timedelta(days=settings.news_days)
    key = t["slug"] if cache else None
    new = 0
    for child, _ in parse_sitemap(get(t["sitemap_index_url"]).content):
        kind = sitemap_type(child)
        if kind not in t["sitemap_types"]:
            continue
        try:
            r = _fetch(get, child, key)
            if r is None:   # this type's sitemap has not changed since the last check
                continue
            urls = parse_sitemap(r.content)
        except Exception as e:
            log.warning("news sitemap %s failed: %s", child, e)
            continue
        with conn() as c:
            seen = {r[0]: r[1] for r in c.execute("SELECT url, lastmod FROM news_sitemap_seen WHERE tenant = %s AND kind = %s",
                                                   (t["slug"], kind)).fetchall()}
        first_run = not seen
        changed = []
        for loc, lastmod in urls:
            before = seen.get(loc, "missing")
            if before == "missing" or (lastmod and before != lastmod):
                if (not first_run) or (lastmod and lastmod >= recent):
                    changed.append((loc, lastmod))
        listed = {loc for loc, _ in urls}
        removed = [u for u in seen if u not in listed]
        with conn() as c:
            for loc, lastmod in urls:
                c.execute("""INSERT INTO news_sitemap_seen(tenant, kind, url, lastmod) VALUES (%s, %s, %s, %s)
                             ON CONFLICT (tenant, url) DO UPDATE SET lastmod = EXCLUDED.lastmod, kind = EXCLUDED.kind""",
                          (t["slug"], kind, loc, lastmod))
            if removed and urls and len(removed) <= max(5, len(seen) // 2):   # more is a broken sitemap, not a clean-up
                c.execute("DELETE FROM news_sitemap_seen WHERE tenant = %s AND url = ANY(%s)", (t["slug"], removed))
                c.execute("""UPDATE news_items SET status = 'gone', updated_at = now()
                             WHERE tenant = %s AND source = 'sitemap' AND status = 'published' AND url = ANY(%s)""", (t["slug"], removed))
            c.commit()
        for loc, lastmod in changed[:20]:   # a site-wide re-save never floods the tab
            try:
                meta = page_meta(get(loc).text)
            except Exception as e:
                log.warning("news page %s failed: %s", loc, e)
                continue
            if meta["title"]:
                new += upsert(t["slug"], "sitemap", kind, {"url": loc, "published_at": lastmod, **meta}, lastmod=lastmod)
        _remember(key, child, r)
    return new


def check_links(t: dict[str, Any], get: Callable | None = None, cache: bool = False) -> int:
    """Items in the tab whose page now answers 404 / 410 (for a video: YouTube's oEmbed no longer knows it) are taken
    off as 'gone'; a gone one that answers again is put back. Hand-published, hidden and rejected items are never
    touched; a timeout or a 5xx changes nothing. Returns how many items changed."""
    get = get or _client().get
    with conn() as c:
        rows = c.execute("""SELECT id, url, kind, status FROM news_items
                            WHERE tenant = %s AND source <> 'manual' AND status IN ('published', 'gone')
                              AND published_at > now() - make_interval(days => %s)
                            ORDER BY published_at DESC LIMIT 60""", (t["slug"], settings.news_days)).fetchall()
    changed = 0
    for item_id, url, kind, status in rows:
        probe = f"https://www.youtube.com/oembed?format=json&url={quote(url, safe='')}" if kind == "video" else url
        try:
            code = get(probe).status_code
        except Exception as e:
            log.info("news link %s not checked: %s", url, e)
            continue
        now_status = "gone" if code in (404, 410) else "published" if code < 400 else status
        if now_status != status:
            with conn() as c:
                changed += c.execute("UPDATE news_items SET status = %s, updated_at = now() WHERE id = %s AND status = %s",
                                     (now_status, item_id, status)).rowcount
                c.commit()
    return changed


POLLERS = {"blog": poll_blog, "sitemap": poll_sitemaps, "youtube": poll_youtube, "mention": poll_mentions, "links": check_links}


def run(which: tuple[str, ...] = ("blog", "sitemap", "youtube", "mention")) -> dict[str, Any]:
    """Poll the given sources for every enabled tenant. Never raises; one failing source does not stop the others."""
    out: dict[str, Any] = {}
    try:
        ts = tenants(enabled_only=True)
    except Exception as e:
        log.warning("news: no tenants (%s)", e)
        return {"error": str(e)[:200]}
    for t in ts:
        for name in which:
            try:
                out[f"{t['slug']}:{name}"] = POLLERS[name](t)
            except Exception as e:
                log.warning("news %s %s failed: %s", t["slug"], name, e)
                out[f"{t['slug']}:{name}"] = f"error: {type(e).__name__}"
    if any(isinstance(v, int) and v for v in out.values()):
        log.info("news polled: %s", out)
    return out


def run_hourly() -> dict[str, Any]:
    return run(("blog", "sitemap"))


def run_daily() -> dict[str, Any]:
    return run(("youtube", "mention"))


# ---------------------------------------------------------------- dynamic checking (NEWS_DYNAMIC)
def configured(t: dict[str, Any], source: str) -> bool:
    return {"blog": bool(t.get("blog_feed_url")), "sitemap": bool(t.get("sitemap_index_url") and t.get("sitemap_types")),
            "youtube": bool(t.get("youtube_channel_id")), "mention": bool((t.get("mention_query") or "").strip()),
            "links": True}[source]


def next_every(source: str, every: int, changed: bool, failed: bool) -> int:
    """Minutes until the next check: the fastest after a change, 1.5x longer after each quiet check, double after a
    failure; never outside the source's CADENCE."""
    fast, slow = CADENCE[source]
    if failed:
        return min(slow, max(every, fast) * 2)
    if changed:
        return fast
    return min(slow, max(fast, round(every * 1.5)))


_STATE_COLS = ["source", "every_minutes", "next_at", "checked_at", "changed_at", "last_new", "errors", "last_error"]


def source_states(tenant_slug: str) -> dict[str, dict[str, Any]]:
    with conn() as c:
        rows = c.execute(f"SELECT {', '.join(_STATE_COLS)} FROM news_sources WHERE tenant = %s", (tenant_slug,)).fetchall()
    return {r[0]: dict(zip(_STATE_COLS, r)) for r in rows}


def poll_source(t: dict[str, Any], source: str, get: Callable | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Check one source of one tenant now (only what changed is fetched) and schedule its next check."""
    now = now or datetime.now(timezone.utc)
    every = (source_states(t["slug"]).get(source) or {}).get("every_minutes") or CADENCE[source][0]
    with conn() as c:
        started = c.execute("SELECT clock_timestamp()").fetchone()[0]
    new, err = 0, None
    try:
        new = POLLERS[source](t, get=get, cache=True)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
        log.warning("news %s %s failed: %s", t["slug"], source, err)
    changed = bool(new)
    if not err and not changed and source in ITEM_SOURCE:   # an edited title, text or picture counts as a change too
        with conn() as c:
            changed = bool(c.execute("SELECT 1 FROM news_items WHERE tenant = %s AND source = %s AND updated_at >= %s LIMIT 1",
                                     (t["slug"], ITEM_SOURCE[source], started)).fetchone())
    every = next_every(source, every, changed, bool(err))
    with conn() as c:
        c.execute("""INSERT INTO news_sources(tenant, source, every_minutes, next_at, checked_at, changed_at, last_new, errors, last_error)
                     VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN %s::timestamptz END, %s, %s, %s)
                     ON CONFLICT (tenant, source) DO UPDATE SET every_minutes = EXCLUDED.every_minutes, next_at = EXCLUDED.next_at,
                       checked_at = EXCLUDED.checked_at, changed_at = COALESCE(EXCLUDED.changed_at, news_sources.changed_at),
                       last_new = EXCLUDED.last_new,
                       errors = CASE WHEN EXCLUDED.errors > 0 THEN news_sources.errors + 1 ELSE 0 END, last_error = EXCLUDED.last_error""",
                  (t["slug"], source, every, now + timedelta(minutes=every), now, changed, now, new, 1 if err else 0, err))
        c.commit()
    return {"new": new, "changed": changed, "every_minutes": every, "error": err}


def tick(get: Callable | None = None, now: datetime | None = None, tenant_slug: str | None = None) -> dict[str, Any]:
    """The dynamic scheduler's job (every NEWS_TICK_MINUTES): check every enabled tenant's sources (or one tenant's)
    that are due. Never raises; one failing source does not stop the others."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, Any] = {}
    try:
        ts = tenants(enabled_only=True)
    except Exception as e:
        log.warning("news: no tenants (%s)", e)
        return {"error": str(e)[:200]}
    for t in ts:
        if tenant_slug and t["slug"] != tenant_slug:
            continue
        try:
            states = source_states(t["slug"])
        except Exception as e:
            log.warning("news %s: no source state (%s)", t["slug"], e)
            continue
        for s in SOURCES:
            if configured(t, s) and (s not in states or states[s]["next_at"] <= now):
                out[f"{t['slug']}:{s}"] = poll_source(t, s, get=get, now=now)
    if any(v.get("new") or v.get("error") for v in out.values()):
        log.info("news checked: %s", out)
    return out


def check_now(which: tuple[str, ...] = SOURCES, tenant_slug: str | None = None, get: Callable | None = None) -> dict[str, Any]:
    """Console -> News "Check the sources now": every chosen source of every enabled tenant (or one), due or not.
    Same answer as run(): new items per tenant:source, or the error."""
    out: dict[str, Any] = {}
    for t in tenants(enabled_only=True):
        if tenant_slug and t["slug"] != tenant_slug:
            continue
        for s in which:
            if s in CADENCE and configured(t, s):
                r = poll_source(t, s, get=get)
                out[f"{t['slug']}:{s}"] = f"error: {r['error']}" if r["error"] else r["new"]
    return out


SOURCE_LABEL = {"blog": "Blog RSS", "sitemap": "Sitemaps", "youtube": "YouTube", "mention": "Press mentions", "links": "Link check"}


def source_report(tenant_slug: str) -> list[dict[str, Any]]:
    """For the console: each configured source with when it was checked, last changed and is checked next."""
    t = tenant(tenant_slug)
    if not t:
        return []
    states = source_states(tenant_slug)
    return [{"source": s, "label": SOURCE_LABEL[s], "fastest": CADENCE[s][0], "slowest": CADENCE[s][1],
             **{k: v for k, v in (states.get(s) or {"every_minutes": CADENCE[s][0], "errors": 0}).items() if k != "source"}}
            for s in SOURCES if configured(t, s)]


# ---------------------------------------------------------------- finding a new website's sources
def _link_tags(html_text: str) -> list[dict[str, str]]:
    out = []
    for tag in re.findall(r"<link\b[^>]*>", html_text, re.I):
        attrs = {k.lower(): htmlmod.unescape(v) for k, v in re.findall(r"([a-zA-Z:-]+)\s*=\s*[\"']([^\"']*)[\"']", tag)}
        out.append(attrs)
    return out


def _youtube_channel(html_text: str, get: Callable) -> str | None:
    """The channel id (UC…) a page links to: directly, or through an @handle / c/ / user/ link resolved on YouTube."""
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", html_text)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com/((?:@|c/|user/)[\w.%-]+)", html_text)
    if not m:
        return None
    try:
        page = get(f"https://www.youtube.com/{m.group(1)}").text
    except Exception as e:
        log.info("news discover: youtube %s unreadable (%s)", m.group(1), e)
        return None
    m = re.search(r"\"(?:channelId|externalId)\":\"(UC[\w-]{22})\"", page) or re.search(r"youtube\.com/channel/(UC[\w-]{22})", page)
    return m.group(1) if m else None


def discover(site: str, get: Callable | None = None) -> dict[str, Any]:
    """A website's news sources, for the console's tenant form (nothing is saved): the blog RSS (the page's
    <link rel=alternate>, else /blog/feed/ or /feed/: the one with the newest post), the sitemap index (robots.txt, else
    /sitemap_index.xml or /sitemap.xml) with its types (news-like ones suggested), the YouTube channel the page links
    to, and the site's name as the mention search."""
    site = (site or "").strip()
    if not re.match(r"^https?://", site):
        site = "https://" + site
    p = urlparse(site)
    if not p.netloc or "." not in p.netloc:
        raise ValueError("a website address is required, e.g. https://www.lakeb2b.com")
    get = get or _client().get
    root, notes = f"{p.scheme}://{p.netloc}", []
    try:
        r = get(site)
        home = r.text if r.status_code < 400 else ""
    except Exception as e:
        home = ""
        notes.append(f"the home page could not be read ({type(e).__name__})")
    m = re.search(r"<meta[^>]+property=[\"']og:site_name[\"'][^>]*content=[\"']([^\"']+)[\"']", home, re.I)
    host = p.netloc.lower().removeprefix("www.")
    name = htmlmod.unescape(m.group(1)).strip() if m else (page_meta(home)["title"] if home else None) or host
    # blog RSS
    feeds = [urljoin(site, a["href"]) for a in _link_tags(home) if "alternate" in a.get("rel", "").lower()
             and a.get("type", "").lower() == "application/rss+xml" and a.get("href") and "comments" not in a["href"].lower()]
    feeds += [root + "/blog/feed/", root + "/feed/"]
    best: tuple | None = None
    for u in list(dict.fromkeys(feeds))[:5]:
        try:
            items = parse_rss(get(u).content)
        except Exception:
            continue
        if items:
            newest = max((i["published_at"] for i in items if i["published_at"]), default=datetime.min.replace(tzinfo=timezone.utc))
            if best is None or (newest, len(items)) > best[1:]:
                best = (u, newest, len(items))
    notes.append(f"blog RSS: {best[2]} posts, newest {best[1]:%d %b %Y}" if best else "no blog RSS found")
    # sitemap index and its types
    maps = []
    try:
        robots = get(root + "/robots.txt")
        if robots.status_code < 400:
            maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots.text)
    except Exception:
        pass
    index, types = None, []
    for u in list(dict.fromkeys(maps + [root + "/sitemap_index.xml", root + "/sitemap.xml"]))[:5]:
        try:
            found = [sitemap_type(loc) for loc, _ in parse_sitemap(get(u).content)]
        except Exception:
            continue
        if any(found):
            index, types = u, list(dict.fromkeys(x for x in found if x))
            break
    suggested = [x for x in types if x not in SKIP_TYPES]
    notes.append(f"sitemap types: {', '.join(types)}" if index else "no sitemap index found")
    channel = _youtube_channel(home, get) if home else None
    notes.append(f"YouTube channel {channel}" if channel else "no YouTube channel linked from the home page")
    return {"slug": re.sub(r"[^a-z0-9-]+", "-", host.split(".")[0]).strip("-")[:40], "name": name,
            "blog_feed_url": best[0] if best else None, "youtube_channel_id": channel, "mention_query": name,
            "sitemap_index_url": index, "sitemap_types": suggested, "sitemap_types_available": types, "notes": notes}


# ---------------------------------------------------------------- reading (widget) and moderation (console)
_COLS = ["id", "tenant", "source", "kind", "title", "url", "published_at", "blurb", "image", "status", "pinned", "created_at"]


def published(tenant_slug: str, limit: int | None = None, days: int | None = None) -> list[dict[str, Any]]:
    """The News tab: pinned first, then newest; last `days` days (pinned excepted), at most `limit` items. `updated`:
    the page was re-saved on the site after it was first listed."""
    limit, days = limit or settings.news_limit, days or settings.news_days
    with conn() as c:
        rows = c.execute(
            f"""SELECT {', '.join(_COLS)}, (lastmod IS NOT NULL AND lastmod > created_at + interval '1 hour') FROM news_items
                WHERE tenant = %s AND status = 'published' AND (pinned OR published_at > now() - make_interval(days => %s))
                ORDER BY pinned DESC, published_at DESC LIMIT %s""", (tenant_slug, days, limit)).fetchall()
    return [{**dict(zip(_COLS + ["updated"], r)), "label": KIND_LABEL.get(r[3], r[3].replace("_", " ").title())} for r in rows]


def admin_items(tenant_slug: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            f"""SELECT {', '.join(_COLS)} FROM news_items
                WHERE (%s::text IS NULL OR tenant = %s) AND (%s::text IS NULL OR status = %s)
                ORDER BY (status = 'pending') DESC, pinned DESC, published_at DESC LIMIT %s""",
            (tenant_slug, tenant_slug, status, status, limit)).fetchall()
    return [{**dict(zip(_COLS, r)), "label": KIND_LABEL.get(r[3], r[3])} for r in rows]


def moderate(item_id: int, status: str | None = None, pinned: bool | None = None) -> bool:
    if status is not None and status not in ("published", "pending", "rejected", "hidden", "gone"):
        raise ValueError("unknown status")
    with conn() as c:
        n = c.execute("""UPDATE news_items SET status = COALESCE(%s, status), pinned = COALESCE(%s, pinned), updated_at = now()
                         WHERE id = %s""", (status, pinned, item_id)).rowcount
        c.commit()
    return n > 0


def publish_manual(tenant_slug: str, url: str, kind: str = "announcement", title: str | None = None, blurb: str | None = None,
                   image: str | None = None, pinned: bool = False, get: Callable | None = None) -> dict[str, Any]:
    """'Publish to the news': a LinkedIn / X post, a launch or an event. Title and image come from the page when it
    allows it (LinkedIn usually does not, so the title can be typed)."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise ValueError("a full https:// link is required")
    if not tenant(tenant_slug):
        raise LookupError("no such tenant")
    meta: dict[str, Any] = {"title": None, "blurb": "", "image": None}
    if not title or not image:
        try:
            r = (get or _client().get)(url)
            if r.status_code < 400:
                meta = page_meta(r.text)
        except Exception as e:
            log.info("news manual: could not read %s: %s", url, e)
    item = {"url": url, "title": (title or meta["title"] or "").strip(), "blurb": (blurb or meta["blurb"] or "").strip(),
            "image": image or meta["image"], "published_at": datetime.now(timezone.utc)}
    if not item["title"]:
        raise ValueError("the page gave no title: type one")
    upsert(tenant_slug, "manual", kind or "announcement", item, status="published")
    with conn() as c:
        row = c.execute("""UPDATE news_items SET status = 'published', pinned = %s, kind = %s, updated_at = now()
                           WHERE tenant = %s AND url = %s RETURNING id""", (bool(pinned), kind or "announcement", tenant_slug, url)).fetchone()
        c.commit()
    return {"id": int(row[0]), **item, "kind": kind, "pinned": bool(pinned)}
