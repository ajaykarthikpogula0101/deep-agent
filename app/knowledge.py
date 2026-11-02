"""Knowledge scope: which websites the chatbot answers from, chosen in the console (Knowledge tab).

Sources
  deependhq   deependhq.com's own pages (pages.site IS NULL): Deep, the log, the essays, the companies' pages, the tools.
              On unless the settings row kb:own says "off".
  <slug>      each company website of a News tenant (pages.site = slug, app/sites.py). On while the tenant's kb_enabled is
              true (the same flag as "the assistant answers from this website" in the News tenant form). Its pages already
              read stay searchable when its News feed is off or KB_SITES_ENABLED=false; those only stop new reading and
              the live site search, as before.

What a switched-off source changes
  retrieval (app/rag/retrieve.search)   its passages, pinned pages and company profile rows are not searched;
  live site search (app/sites.sites)     its website is not searched live;
  the prompt (scope_note)                the model is told what it covers, so a question about something switched off
                                         gets "not covered here" plus the Email Deep / booking offer, not outside knowledge.
Help-center articles and custom answers written in the console stay on: they are the owner's own words.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.db import conn, get_setting, set_setting

log = logging.getLogger("knowledge")

OWN = "deependhq"
CACHE_SECONDS = 10
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: str, fn):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def own_enabled() -> bool:
    """deependhq.com's own pages are in the knowledge. Never raises: a database hiccup keeps them on."""
    def read() -> bool:
        try:
            return (get_setting("kb:own") or "on") != "off"
        except Exception as e:
            log.warning("kb:own read failed: %s", e)
            return True
    return _cached("own", read)


def active_sites() -> list[dict[str, Any]]:
    """The company websites whose indexed pages the chatbot reads: every tenant switched on here (kb_enabled), whether or
    not its News feed is on and whether or not KB_SITES_ENABLED still re-reads the sites (that flag only stops reading)."""
    def read() -> list[dict[str, Any]]:
        try:
            from app import news

            return [t for t in news.tenants() if t.get("kb_enabled", True)]
        except Exception as e:
            log.warning("active sites failed: %s", e)
            return []
    return _cached("sites", read)


def active_slugs() -> list[str]:
    return [t["slug"] for t in active_sites()]


def own_host() -> str:
    return urlparse(settings.site_base_url).netloc.removeprefix("www.") or "deependhq.com"


def sources() -> list[dict[str, Any]]:
    """For the console: every source with its switch, its size and why it is off."""
    from app import news, sites

    with conn() as c:
        counts = {r[0] or OWN: (int(r[1]), int(r[2])) for r in c.execute(
            """SELECT p.site, count(DISTINCT p.url), count(ch.id) FROM pages p LEFT JOIN chunks ch ON ch.url = p.url
               GROUP BY p.site""").fetchall()}
    own = own_enabled()
    out = [{"key": OWN, "name": own_host(), "host": own_host(), "about": "Deep, the build log, essays, the companies' pages and tools",
            "enabled": own, "on": own, "note": "", "pages": counts.get(OWN, (0, 0))[0], "chunks": counts.get(OWN, (0, 0))[1]}]
    for t in news.tenants():
        root = sites.site_root(t)
        if not root or urlparse(root).netloc.removeprefix("www.") == own_host():
            continue
        on = bool(t.get("kb_enabled", True))
        # answers come from the pages already read; these only stop new pages and the live site search
        note = ("switched off here" if not on else "not re-read: KB_SITES_ENABLED=false" if not settings.kb_sites_enabled
                else "no live search: its News tenant is off" if not t.get("enabled") else "")
        out.append({"key": t["slug"], "name": t.get("name") or t["slug"], "host": urlparse(root).netloc.removeprefix("www."),
                    "about": "the company's own website: services, data, case studies, blog", "enabled": on, "on": on, "note": note,
                    "pages": counts.get(t["slug"], (0, 0))[0], "chunks": counts.get(t["slug"], (0, 0))[1]})
    return out


def set_source(key: str, on: bool) -> list[dict[str, Any]]:
    """Switch one source on or off. Raises LookupError for an unknown key."""
    if key == OWN:
        set_setting("kb:own", None if on else "off")
    else:
        with conn() as c:
            n = c.execute("UPDATE news_tenants SET kb_enabled = %s, updated_at = now() WHERE slug = %s", (bool(on), key)).rowcount
            c.commit()
        if not n:
            raise LookupError(key)
    clear_cache()
    log.info("knowledge source %s switched %s", key, "on" if on else "off")
    return sources()


def scope_note() -> str:
    """A line for the system prompt when the owner narrowed the knowledge; empty when everything is on."""
    try:
        listed = sources()
    except Exception as e:
        log.warning("scope note failed: %s", e)
        return ""
    on = [s for s in listed if s["on"]]
    off = [s for s in listed if not s["on"]]
    if not off:
        return ""
    covered = ", ".join(f"{s['name']} ({s['host']})" if s["name"] != s["host"] else s["host"] for s in on) or "nothing"
    return ("\nKNOWLEDGE SCOPE (set by the site owner): the sources cover only " + covered + ". "
            + ", ".join(s["name"] for s in off) + (" is" if len(off) == 1 else " are") + " not covered in this chat: if the "
            "visitor asks about it, say in one sentence that you can't help with that here and offer to email Deep or book a "
            "call. Do not answer it from your own knowledge.")
