"""Company websites in the assistant's knowledge: the sites of the News tenants (LakeB2B, SPAN, ...), next to
deependhq.com (which app/ingest/pipeline.py indexes on its own).

Index (every KB_SITES_EVERY_HOURS, and at start-up when a site was never read):
  every URL in the site's sitemaps (robots.txt "Sitemap:" lines and /sitemap_index.xml, nested indexes followed) except
  theme parts and taxonomies (SKIP_TYPES) and what robots.txt disallows; newest lastmod first, at most
  KB_SITE_PAGES_PER_RUN pages a run and KB_SITE_MAX_PAGES a site, so a first read spreads over a few runs. A page whose
  sitemap lastmod did not change is not fetched again; one dropped from the sitemaps leaves the index. Pages are stored
  in the same pages / chunks tables with pages.site = the tenant slug (deependhq.com's own pages have site NULL).
Live search (KB_LIVE_SEARCH): when a question names one of the companies, or the index has nothing close, the site's own
  search (WordPress /wp-json/wp/v2/search) is asked; the best pages are read, their closest passages become sources,
  and the pages are indexed on the spot.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.robotparser as robotparser
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.db import conn

log = logging.getLogger("sites")

# sitemap types that are not content worth answering from
SKIP_TYPES = {"attachment", "author", "category", "post_tag", "tag", "home_slider", "elementor_library", "e-landing-page",
              "wp_block", "nav_menu_item", "product_cat", "product_tag", "local", "testimonial", "client"}
_NOISE = ("script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe", "button")
_STOP = set("""a an the and or of to in on for with about from by at as is are was were be been do does did can could would
should will what which who whom whose when where why how this that these those it its your you our we us i me my
tell show give find get know any some more much many please there their them they he she his her than then also just
like into out over under up down not no yes vs versus""".split())
_lock = threading.Lock()


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": settings.crawl_user_agent})


# ---------------------------------------------------------------- which sites
def site_root(t: dict[str, Any]) -> str | None:
    for u in (t.get("site_url"), t.get("sitemap_index_url"), t.get("blog_feed_url")):
        if u:
            p = urlparse(u if "://" in u else "https://" + u)
            if p.netloc:
                return f"{p.scheme}://{p.netloc}"
    return None


def sites() -> list[dict[str, Any]]:
    """Enabled News tenants with a website, other than deependhq.com itself (indexed by the main ingest)."""
    from app import news

    own = urlparse(settings.site_base_url).netloc.removeprefix("www.")
    out = []
    for t in news.tenants(enabled_only=True):
        root = site_root(t)
        if root and t.get("kb_enabled", True) and urlparse(root).netloc.removeprefix("www.") != own:
            out.append({**t, "root": root, "host": urlparse(root).netloc.removeprefix("www.")})
    return out


def aliases(t: dict[str, Any]) -> list[str]:
    """Names a visitor may use for the company: LakeB2B, Lake B2B, lakeb2b.com, SPAN, SPAN Global Services, ..."""
    names = {t.get("name") or "", t.get("mention_query") or "", t.get("slug") or "", t.get("host") or ""}
    out = set()
    for n in names:
        n = n.strip().strip('"').lower()
        if not n:
            continue
        out.add(n)
        out.add(re.sub(r"\.(com|net|org|io|co)$", "", n))
        out.add(re.sub(r"(?<=[a-z])(?=b2b)", " ", n))               # lakeb2b -> lake b2b
        first = n.split()[0] if " " in n else None
        if first and len(first) >= 4 and first not in _STOP:          # "span global services" -> "span"
            out.add(first)
    return sorted((a for a in out if len(a) >= 3), key=len, reverse=True)


def mentioned(query: str, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The company site a question names, if any."""
    q = (query or "").lower()
    for t in candidates if candidates is not None else sites():
        for a in aliases(t):
            if re.search(r"(?<![a-z0-9])" + re.escape(a).replace(r"\ ", r"\s*") + r"(?![a-z0-9])", q):
                return t
    return None


# ---------------------------------------------------------------- reading pages (pure, unit-tested)
def _lines(node) -> list[str]:
    """The text of an element as lines: one per heading, paragraph, list item, row or block."""
    for h in node.find_all(["h1", "h2", "h3", "h4"]):
        h.insert_before("\n\n")
        h.insert_after("\n\n")
    for b in node.find_all(["p", "li", "tr", "div"]):
        b.insert_after("\n")
    return [l.strip() for l in re.sub(r"[ \t\xa0]+", " ", node.get_text(" ")).splitlines()]


def extract(url: str, html_text: str, boiler: set[str] | None = None) -> dict[str, str] | None:
    """Title and main text of a page: <main> / <article> / the WordPress content area, without menus, headers,
    footers, forms and cookie banners, nor the short lines every page of the site repeats (`boiler`: the menu, as read
    from the home page). None for a page with almost no text."""
    soup = BeautifulSoup(html_text, "lxml")
    og = soup.find("meta", attrs={"property": "og:title"})
    title = (og.get("content") if og and og.get("content") else (soup.title.string if soup.title and soup.title.string else url)).strip()
    title = re.sub(r"\s*[|–-]\s*[^|–-]{2,40}$", "", title).strip() or title
    total = len((soup.body or soup).get_text(" ").split()) or 1
    noise = soup.find_all(_NOISE) + soup.find_all(attrs={"class": re.compile(r"cookie|consent|popup|modal|newsletter-signup|breadcrumb", re.I)})
    for t in noise:
        # broken markup can leave the whole page inside a <header> or <aside>: never drop most of the page
        if t.name in ("script", "style", "noscript", "svg") or len(t.get_text(" ").split()) < total * 0.4:
            t.decompose()
    main = (soup.find("main") or soup.find("article") or soup.find(attrs={"class": re.compile(r"\b(entry-content|post-content|site-content)\b")})
            or soup.find(attrs={"role": "main"}) or soup.body or soup)
    lines, seen = [], set()
    for line in _lines(main):
        if line and boiler and line in boiler and len(line.split()) <= 12:
            continue
        if line and line not in seen:          # repeated widgets (the same CTA three times) once
            seen.add(line)
            lines.append(line)
        elif not line and lines and lines[-1]:
            lines.append("")
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text.split()) < 20:   # a short FAQ answer is still an answer
        return None
    if title and title.lower() not in text[:300].lower():   # an FAQ page's question is often only in its title
        text = f"{title}\n\n{text}"
    return {"title": title, "text": text}


_boiler_cache: dict[str, tuple[float, set[str]]] = {}


def boilerplate(root: str, get: Callable) -> set[str]:
    """The short lines of the home page (menus, header, footer links): dropped from every other page. Cached 12 h."""
    hit = _boiler_cache.get(root)
    if hit and time.time() - hit[0] < 12 * 3600:
        return hit[1]
    lines: set[str] = set()
    try:
        r = get(root + "/")
        if r.status_code < 400:   # the raw page, menus and footer included: those are exactly the lines to drop
            soup = BeautifulSoup(r.text, "lxml")
            for t in soup.find_all(("script", "style", "noscript", "svg")):
                t.decompose()
            lines = {l for l in _lines(soup.body or soup) if l and len(l.split()) <= 12}
    except Exception as e:
        log.info("home page of %s unreadable: %s", root, e)
    _boiler_cache[root] = (time.time(), lines)
    return lines


def keywords(query: str, drop: list[str] | None = None) -> list[str]:
    """The words a site search should get: no stopwords, no company names, longest first."""
    q = (query or "").lower()
    for a in drop or []:
        q = re.sub(r"(?<![a-z0-9])" + re.escape(a) + r"(?:'s)?(?![a-z0-9])", " ", q)
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9+&-]*", q) if w not in _STOP and len(w) > 1]
    return sorted(dict.fromkeys(words), key=len, reverse=True)


# ---------------------------------------------------------------- sitemaps
def _robots(root: str, get: Callable) -> tuple[robotparser.RobotFileParser, list[str]]:
    rp = robotparser.RobotFileParser()
    maps: list[str] = []
    try:
        r = get(root + "/robots.txt")
        lines = r.text.splitlines() if r.status_code < 400 else []
        rp.parse(lines)
        maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", "\n".join(lines))
    except Exception:
        rp.parse([])
    return rp, maps


def sitemap_entries(root: str, get: Callable) -> list[tuple[str, datetime | None]]:
    """(url, lastmod) of every content page in the site's sitemaps, robots.txt honoured."""
    from app.news import parse_sitemap, sitemap_type

    rp, maps = _robots(root, get)
    queue = list(dict.fromkeys(maps + [root + "/sitemap_index.xml"]))
    seen_maps: set[str] = set()
    out: dict[str, datetime | None] = {}
    agent = settings.crawl_user_agent.split("/")[0]
    while queue and len(seen_maps) < 60:
        sm = queue.pop(0)
        if sm in seen_maps or sitemap_type(sm) in SKIP_TYPES:
            continue
        seen_maps.add(sm)
        try:
            entries = parse_sitemap(get(sm).content)
        except Exception as e:
            log.info("sitemap %s unreadable: %s", sm, e)
            continue
        for loc, lastmod in entries:
            if re.search(r"\.xml(\.gz)?$", loc):
                queue.append(loc)
            elif urlparse(loc).netloc.removeprefix("www.") == urlparse(root).netloc.removeprefix("www.") and rp.can_fetch(agent, loc):
                out[loc] = lastmod
    return list(out.items())


# ---------------------------------------------------------------- the index
def _save_page(slug: str, url: str, title: str, text: str, lastmod: datetime | None) -> int:
    """Chunk, embed and store one page (replacing its old chunks). Returns the chunks written (0: unchanged)."""
    from app.embeddings import embed_texts
    from app.ingest.chunker import Doc, chunk_doc
    from app.ingest.pipeline import EMBED_VERSION, embed_input

    sha = hashlib.sha256(f"{settings.embed_model}|{EMBED_VERSION}|{title}|{text}".encode()).hexdigest()
    with conn() as c:
        row = c.execute("SELECT content_sha FROM pages WHERE url = %s", (url,)).fetchone()
        if row and row[0] == sha:
            c.execute("UPDATE pages SET lastmod = %s, crawled_at = now() WHERE url = %s", (lastmod, url))
            c.commit()
            return 0
    chunks = chunk_doc(Doc(url=url, title=title, source="site", text=text, metadata={"kind": "site", "site": slug, "title": title}))
    if not chunks:
        return 0
    vectors = embed_texts([embed_input(ch) for ch in chunks])
    with conn() as c:
        c.execute("""INSERT INTO pages(url, title, source, content_sha, crawled_at, site, lastmod) VALUES (%s, %s, 'site', %s, now(), %s, %s)
                     ON CONFLICT (url) DO UPDATE SET title = EXCLUDED.title, source = EXCLUDED.source, content_sha = EXCLUDED.content_sha,
                       crawled_at = now(), site = EXCLUDED.site, lastmod = EXCLUDED.lastmod""", (url, title[:300], sha, slug, lastmod))
        c.execute("DELETE FROM chunks WHERE url = %s", (url,))
        for ch, vec in zip(chunks, vectors):
            c.execute("""INSERT INTO chunks(url, section, position, text, tokens, embedding, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
                      (url, ch.section, ch.position, ch.text, ch.tokens, vec, json.dumps(ch.metadata)))
        c.commit()
    return len(chunks)


def index_site(t: dict[str, Any], get: Callable | None = None, per_run: int | None = None, pause: float = 0.3) -> dict[str, Any]:
    """One incremental pass over a site: new and changed pages (newest first, at most per_run), removed pages out."""
    get = get or _client().get
    per_run = per_run if per_run is not None else settings.kb_site_pages_per_run
    slug, t0 = t["slug"], time.time()
    entries = sitemap_entries(t["root"], get)
    boiler = boilerplate(t["root"], get)
    with conn() as c:
        have = {r[0]: r[1] for r in c.execute("SELECT url, lastmod FROM pages WHERE site = %s", (slug,)).fetchall()}
    stats = {"site": slug, "in_sitemaps": len(entries), "indexed_before": len(have), "read": 0, "changed": 0, "chunks": 0,
             "removed": 0, "failed": 0}
    listed = {u for u, _ in entries}
    gone = [u for u in have if u not in listed]
    if gone and entries and len(gone) <= max(20, len(have) // 3):   # more is a broken sitemap, not a clean-up
        with conn() as c:
            c.execute("DELETE FROM pages WHERE site = %s AND url = ANY(%s)", (slug, gone))   # chunks go with them
            c.commit()
        stats["removed"] = len(gone)
    room = max(0, settings.kb_site_max_pages - (len(have) - stats["removed"]))
    todo = [(u, m) for u, m in entries if u not in have or (m is not None and have[u] != m)]
    todo.sort(key=lambda e: e[1] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    todo = [e for e in todo if e[0] in have] + [e for e in todo if e[0] not in have][:room]
    for url, lastmod in todo[:per_run]:
        try:
            r = get(url)
            page = extract(url, r.text, boiler) if r.status_code < 400 and url.rstrip("/") != t["root"] else (
                extract(url, r.text) if r.status_code < 400 else None)
            stats["read"] += 1
            if page:
                n = _save_page(slug, url, page["title"], page["text"], lastmod)
                stats["chunks"] += n
                stats["changed"] += bool(n)
            elif r.status_code in (404, 410) and url in have:
                with conn() as c:
                    c.execute("DELETE FROM pages WHERE url = %s", (url,))
                    c.commit()
        except Exception as e:
            stats["failed"] += 1
            log.info("site page %s failed: %s", url, e)
        if pause:
            time.sleep(pause)
    stats["left"] = max(0, len(todo) - per_run)
    stats["seconds"] = round(time.time() - t0, 1)
    return stats


LOCK_KEY = 0x6465657061_03   # "deepa" + 3: one pass at a time across processes (app/leader.py uses + 1)


def _db_lock():
    """A dedicated connection holding the site-index advisory lock, or None when another process holds it."""
    import psycopg

    try:
        c = psycopg.connect(settings.database_url, autocommit=True, connect_timeout=10)
    except Exception as e:
        log.info("site index lock unavailable: %s", e)
        return None
    if c.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
        return c
    c.close()
    return None


def run() -> dict[str, Any]:
    """Every company site, one incremental pass each. Never raises; one run at a time (in this process and across
    processes: a second app instance or a manual run skips)."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "already running"}
    held = _db_lock()
    if held is None:
        _lock.release()
        return {"skipped": "another process is reading the sites"}
    try:
        out = {}
        for t in sites():
            try:
                out[t["slug"]] = index_site(t)
            except Exception as e:
                log.warning("site %s index failed: %s", t["slug"], e)
                out[t["slug"]] = {"error": f"{type(e).__name__}: {e}"[:200]}
        if out:
            log.info("company sites indexed: %s", out)
        _set_state({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sites": out})
        return out
    finally:
        try:
            held.close()   # closing the session releases the advisory lock
        except Exception:
            pass
        _lock.release()


def run_async() -> None:
    threading.Thread(target=run, name="sites-index", daemon=True).start()


def _set_state(state: dict[str, Any]) -> None:
    try:
        with conn() as c:
            c.execute("""INSERT INTO settings(key, value) VALUES ('sites:last', %s)
                         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (json.dumps(state),))
            c.commit()
    except Exception as e:
        log.info("sites state not saved: %s", e)


def report() -> dict[str, Any]:
    """For the console: pages and chunks indexed per site, and the last run."""
    with conn() as c:
        rows = c.execute("""SELECT p.site, count(DISTINCT p.url), count(ch.id), max(p.crawled_at) FROM pages p
                            LEFT JOIN chunks ch ON ch.url = p.url WHERE p.site IS NOT NULL GROUP BY p.site""").fetchall()
        last = c.execute("SELECT value FROM settings WHERE key = 'sites:last'").fetchone()
    try:
        last_run = json.loads(last[0]) if last else None
    except (TypeError, ValueError):
        last_run = None
    return {"sites": [{"site": r[0], "pages": r[1], "chunks": r[2], "updated_at": r[3]} for r in rows], "last_run": last_run,
            "enabled": settings.kb_sites_enabled, "live_search": settings.kb_live_search}


def due() -> bool:
    """A site with nothing indexed yet: the start-up reads it now instead of waiting KB_SITES_EVERY_HOURS."""
    try:
        with conn() as c:
            have = {r[0] for r in c.execute("SELECT DISTINCT site FROM pages WHERE site IS NOT NULL").fetchall()}
        return any(t["slug"] not in have for t in sites())
    except Exception:
        return False


# ---------------------------------------------------------------- live search
def live_hits(query: str, vec: list[float], targets: list[dict[str, Any]], get: Callable | None = None,
              pages_per_site: int = 2, deadline: float = 8.0) -> list[dict[str, Any]]:
    """Ask each target site's own search, read its best pages and return their passages closest to the question
    (url, title, section, text, score, metadata), best first. The pages read are indexed for next time."""
    from app.embeddings import embed_texts
    from app.ingest.chunker import Doc, chunk_doc
    from app.ingest.pipeline import embed_input

    get = get or httpx.Client(timeout=6, follow_redirects=True, headers={"User-Agent": settings.crawl_user_agent}).get
    t0, out = time.time(), []
    for t in targets:
        words = keywords(query, aliases(t))
        if not words:
            continue
        boiler = boilerplate(t["root"], get)
        found: list[dict[str, Any]] = []
        for attempt in (words[:4], words[:2], words[:1]):
            if time.time() - t0 > deadline:
                break
            try:
                r = get(t["root"] + "/wp-json/wp/v2/search", params={"search": " ".join(attempt), "per_page": 6})
                found = [x for x in (r.json() if r.status_code == 200 else []) if x.get("url")]
            except Exception as e:
                log.info("live search %s failed: %s", t["slug"], e)
                found = []
            if found:
                break
        for x in found[:pages_per_site]:
            if time.time() - t0 > deadline:
                break
            try:
                r = get(x["url"])
                page = extract(x["url"], r.text, boiler) if r.status_code < 400 else None
            except Exception:
                page = None
            if not page:
                continue
            chunks = chunk_doc(Doc(url=x["url"], title=page["title"], source="site", text=page["text"],
                                   metadata={"kind": "site", "site": t["slug"], "title": page["title"]}))[:12]
            if not chunks:
                continue
            vecs = embed_texts([embed_input(ch) for ch in chunks])
            scored = sorted(((sum(a * b for a, b in zip(vec, v)), ch) for ch, v in zip(chunks, vecs)), key=lambda s: s[0], reverse=True)
            for score, ch in scored[:2]:
                out.append({"url": x["url"], "title": page["title"], "section": ch.section, "text": ch.text, "score": float(score),
                            "metadata": {**ch.metadata, "live": True}})
            try:
                _save_page(t["slug"], x["url"], page["title"], page["text"], None)
            except Exception as e:
                log.info("live page not indexed: %s", e)
    return sorted(out, key=lambda h: h["score"], reverse=True)
