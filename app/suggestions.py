"""Smart suggestions: the questions visitors actually asked most in the last SUGGESTIONS_DAYS days become the
chips on the welcome screen and the quick replies under the greeting bubble (served in GET /widget-config).

"Book a call with Deep" always leads. Then the top answered questions (asked at least MIN_COUNT times, cleaned:
no emails, numbers or chit-chat, 10–70 characters, sentence case, trailing "?"), then the fixed defaults until
there are LIMIT chips. Cached CACHE_SECONDS in process; a site attribute (data-quick-replies / suggestions=)
still wins on the client.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from app.config import settings

log = logging.getLogger("suggestions")

PINNED = ["Book a call with Deep"]
DEFAULTS = ["What is Deep working on?", "Tell me about the companies"]
LIMIT = 3
MIN_COUNT = 2
CACHE_SECONDS = 600
RESOLVED = ("answered", "custom")

_BAD = re.compile(r"@|https?://|www\.|\d{3,}|\b(i'?m|i am|hi|hello|hey|thanks|thank you|yes|no|ok|okay|please call|"
                  r"my name|my email|my company|call me)\b", re.I)
_QUESTION_START = re.compile(r"^(what|how|who|whom|whose|which|where|when|why|does|do|did|is|are|was|were|can|could|will|would|"
                             r"should|tell|show|explain|describe|list|give|summari[sz]e|compare|has|have)\b", re.I)
_BOOKING = re.compile(r"\b(book|schedule|meeting|slot|appointment)\b", re.I)

_cache: dict[str, tuple[float, list[str], list[dict[str, Any]]]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- pure helpers
def clean(q: str | None) -> str | None:
    """A visitor's question as a chip label, or None when it is personal, chatty, too long or not a question."""
    t = re.sub(r"\s+", " ", (q or "")).strip().strip("\"'“”")
    if not (10 <= len(t) <= 70) or len(t.split()) > 12 or _BAD.search(t) or not _QUESTION_START.match(t):
        return None
    t = t[0].upper() + t[1:]
    t = re.sub(r"[.!,;:\s]+$", "", t)
    if not t.endswith("?") and re.match(r"^(what|how|who|which|where|when|why|does|do|did|is|are|can|could|will|would|should|has|have)\b", t, re.I):
        t += "?"
    return t


def merge(asked: list[str], pinned: list[str] | None = None, defaults: list[str] | None = None, limit: int = LIMIT) -> list[str]:
    """pinned first, then asked questions (no duplicates, no booking phrasings that repeat the pinned chip),
    then defaults, cut to `limit`."""
    pinned = PINNED if pinned is None else pinned
    defaults = DEFAULTS if defaults is None else defaults
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        k = re.sub(r"[^a-z0-9 ]", "", x.lower()).strip()
        if k and k not in seen and len(out) < limit:
            seen.add(k)
            out.append(x)

    for x in pinned:
        add(x)
    for x in asked:
        if _BOOKING.search(x) and any(_BOOKING.search(p) for p in pinned):
            continue
        add(x)
    for x in defaults:
        add(x)
    return out


# ---------------------------------------------------------------- database
def top_questions(days: int | None = None, limit: int = 8) -> list[dict[str, Any]]:
    """Most asked answered questions, normalised, with counts; cleaned for display (unfit ones dropped)."""
    from app.db import conn

    days = max(1, min(int(days or settings.suggestions_days), 365))
    with conn() as c:
        rows = c.execute(
            """SELECT lower(regexp_replace(trim(question), '\\s+', ' ', 'g')) AS q, count(*), min(trim(question))
               FROM messages
               WHERE role = 'assistant' AND outcome = ANY(%s) AND question IS NOT NULL
                 AND ts > now() - make_interval(days => %s)
               GROUP BY 1 HAVING count(*) >= %s ORDER BY 2 DESC, 1 LIMIT %s""",
            (list(RESOLVED), days, MIN_COUNT, limit * 3)).fetchall()
    out: list[dict[str, Any]] = []
    for _norm, n, original in rows:
        label = clean(original)
        if label:
            out.append({"question": label, "count": int(n)})
        if len(out) >= limit:
            break
    return out


def current(force: bool = False) -> list[str]:
    """The chips to show right now. Never raises: without a database the defaults come back."""
    return explain(force)["items"]


def explain(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    with _lock:
        hit = _cache.get("s")
    if hit and not force and now - hit[0] < CACHE_SECONDS:
        return {"items": list(hit[1]), "asked": list(hit[2]), "days": settings.suggestions_days, "cached": True}
    asked: list[dict[str, Any]] = []
    try:
        asked = top_questions()
    except Exception as e:
        log.warning("top questions unavailable, using defaults: %s", e)
    items = merge([a["question"] for a in asked])
    with _lock:
        _cache["s"] = (now, items, asked)
    return {"items": items, "asked": asked, "days": settings.suggestions_days, "cached": False,
            "pinned": PINNED, "defaults": DEFAULTS, "min_count": MIN_COUNT}


def invalidate() -> None:
    with _lock:
        _cache.pop("s", None)
