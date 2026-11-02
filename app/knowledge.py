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
Your own answers (extras): help-center articles (settings kb:help) and custom answers (kb:custom), on unless switched off.
  Off, help articles leave retrieval (app/rag/retrieve.search) and custom answers stop matching (app/chat.py); both stay
  editable in their tabs.

The visitor-facing wording follows the switches too (widget_scope, GET /widget-config "knowledge"): the home screen's intro,
quick actions and the loader's greeting name the first company website that is on (LakeB2B while it is on, exactly as before),
or speak of Deep's companies when none is; suggested questions that name a switched-off website are dropped.
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


EXTRAS = {"help": ("Help-center articles", "the articles in the Help center tab, written by you or drafted for you"),
          "custom": ("Custom answers", "the exact answers in the Custom answers tab, used word for word when a question matches")}


def extra_enabled(key: str) -> bool:
    """Help articles ("help") or custom answers ("custom") are in use. Never raises: a database hiccup keeps them on."""
    def read() -> bool:
        try:
            return (get_setting(f"kb:{key}") or "on") != "off"
        except Exception as e:
            log.warning("kb:%s read failed: %s", key, e)
            return True
    return _cached("extra:" + key, read)


def extras() -> list[dict[str, Any]]:
    """For the console: the owner's own answers, with their switches and sizes."""
    counts = {"help": 0, "custom": 0}
    try:
        with conn() as c:
            counts["custom"] = int(c.execute("SELECT count(*) FROM custom_answers WHERE enabled").fetchone()[0])
            counts["help"] = int(c.execute("SELECT count(*) FROM help_articles WHERE published AND source IN ('builtin', 'owner')").fetchone()[0])
    except Exception as e:
        log.warning("extras count failed: %s", e)
    out = []
    for key, (name, about) in EXTRAS.items():
        on = extra_enabled(key)
        out.append({"key": key, "name": name, "about": about, "enabled": on, "on": on, "count": counts[key],
                    "unit": "published articles" if key == "help" else "answers switched on"})
    return out


def set_source(key: str, on: bool) -> list[dict[str, Any]]:
    """Switch one source on or off. Raises LookupError for an unknown key."""
    if key == OWN:
        set_setting("kb:own", None if on else "off")
    elif key in EXTRAS:
        set_setting(f"kb:{key}", None if on else "off")
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


# ---------------------------------------------------------------- what the visitor sees
def brand() -> str | None:
    """The company the widget's home screen talks about: the first company website that is on (LakeB2B as long as it is
    on), None when no company website is on."""
    try:
        listed = [x for x in sources() if x["key"] != OWN and x["on"]]
    except Exception as e:
        log.warning("brand read failed: %s", e)
        return "LakeB2B"
    if not listed:
        return None
    name = listed[0]["name"]
    return "LakeB2B" if listed[0]["key"] == "lakeb2b" else name


def _off_names() -> list[str]:
    out = []
    for x in sources():
        if x["on"]:
            continue
        if x["key"] == OWN:
            continue   # deependhq.com is the host's own site: questions about Deep are still fine to show
        out += [x["key"].lower(), (x["name"] or "").lower(), (x["host"] or "").lower().split(".")[0]]
        if x["key"] == "lakeb2b":
            out.append("lake b2b")
        first = (x["name"] or "").split(" ")[0].lower()
        if len(first) >= 4:
            out.append(first)
    return [n for n in dict.fromkeys(out) if n]


def keep_question(q: str, off: list[str] | None = None) -> bool:
    """A suggested question is shown unless it names a switched-off website."""
    off = _off_names() if off is None else off
    low = (q or "").lower()
    return not any(n in low for n in off)


def widget_scope(suggestions: list[str] | None = None) -> dict[str, Any]:
    """GET /widget-config "knowledge": {"brand", "own"} and, given the suggested questions, those still in scope. Never raises."""
    try:
        off = _off_names()
        kept = [q for q in (suggestions or []) if keep_question(q, off)]
        return {"brand": brand(), "own": own_enabled(), "suggestions": kept}
    except Exception as e:
        log.warning("widget scope failed: %s", e)
        return {"brand": "LakeB2B", "own": True, "suggestions": list(suggestions or [])}
