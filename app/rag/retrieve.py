"""Vector retrieval with a confidence floor. Below the floor the caller must refuse, not guess."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.db import conn
from app.embeddings import embed_query

log = logging.getLogger("retrieve")


@dataclass
class Hit:
    url: str
    title: str
    section: str | None
    text: str
    score: float  # cosine similarity in [0,1]
    metadata: dict


_DAY_RE = re.compile(r"\bday\s*#?\s*(\d{1,4})\b", re.I)


def _day_hits(c, query: str) -> list[Hit]:
    """Embeddings are poor at numbers: 'day 338' must return that entry, so fetch it by metadata directly."""
    m = _DAY_RE.search(query)
    if not m:
        return []
    rows = c.execute(
        """SELECT ch.url, p.title, ch.section, ch.text, ch.metadata
           FROM chunks ch JOIN pages p ON p.url = ch.url
           WHERE ch.metadata->>'day' = %s ORDER BY ch.position LIMIT 3""",
        (m.group(1),),
    ).fetchall()
    return [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=1.0, metadata=r[4] or {}) for r in rows]


# Questions a vector search answers badly on this site (measured 2026-10-16: "who is Deep?" ranked the privacy page
# first at 0.565, "latest log entry" the home page, "what tools does he use" the toolkit fourth). Each rule names the
# page that answers it; those chunks come first with score 1.0, like a day number does.
_ABOUT_DEEP = re.compile(
    r"\b(who('?s| is)( this)? (deep|sreedeep|he|the (founder|owner|author))|(about|tell me about|introduce) (deep|sreedeep|him)"
    r"|where('?s| is| does)? (deep|sreedeep|he)\b.*\b(based|live|located|from|work)|(based|located) (in|where)"
    r"|(deep|sreedeep|he)('?s| is) (based|located|from)|what does (deep|sreedeep|he) do"
    r"|(his|deep'?s|sreedeep'?s) (role|roles|job|title|titles|background|bio|position|companies|location|city)"
    r"|sreedeep|surapaneni)\b", re.I)
_TOOLS = re.compile(r"\b(tools?|toolkit|tool stack|stack|software|tech stack|uses? to build|ai stack)\b", re.I)
_NOW = re.compile(r"\b(working on|focus(ed|ing)? on|right now|currently|these days|at the moment|up to|now page|hiring|launching)\b", re.I)
_LATEST = re.compile(r"\b(latest|newest|most recent|recent|last|today|yesterday|this week)\b.{0,30}\b(entry|entries|post|posts|"
                     r"log|update|updates|day|days|note|notes|shipped|ship|build|built)\b"
                     r"|\bwhat (did|has) (he|deep) (ship|shipped|build|built|do|done)\b.{0,20}\b(today|yesterday|lately|recently|this week)\b",
                     re.I)

PINNED_PAGES = {  # rule -> (url, how many leading chunks)
    "about": [("https://deependhq.com/", 1), ("https://deependhq.com/now", 1)],
    "tools": [("https://deependhq.com/toolkit", 3)],
    "now": [("https://deependhq.com/now", 1)],
}


def pinned_rules(query: str) -> list[str]:
    """Which pinned pages a question needs (pure, unit-tested)."""
    q = query or ""
    out = []
    if _LATEST.search(q):
        out.append("latest")
    if _ABOUT_DEEP.search(q):
        out.append("about")
    if _TOOLS.search(q):
        out.append("tools")
    if _NOW.search(q) and "about" not in out:
        out.append("now")
    return out


def _pinned_hits(c, query: str) -> list[Hit]:
    hits: list[Hit] = []
    for rule in pinned_rules(query):
        if rule == "latest":
            rows = c.execute(
                """SELECT DISTINCT ON ((ch.metadata->>'day')::int) ch.url, p.title, ch.section, ch.text, ch.metadata
                   FROM chunks ch JOIN pages p ON p.url = ch.url
                   WHERE ch.metadata ? 'day' AND ch.metadata->>'day' ~ '^[0-9]+$'
                   ORDER BY (ch.metadata->>'day')::int DESC, ch.position LIMIT 3""").fetchall()
        else:
            rows = []
            for url, n in PINNED_PAGES[rule]:
                rows += c.execute(
                    """SELECT ch.url, p.title, ch.section, ch.text, ch.metadata FROM chunks ch JOIN pages p ON p.url = ch.url
                       WHERE ch.url = %s ORDER BY ch.position LIMIT %s""", (url, n)).fetchall()
        hits += [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=1.0, metadata=r[4] or {}) for r in rows]
    return hits


def search(query: str, k: int | None = None, vec: list[float] | None = None) -> list[Hit]:
    k = k or settings.retrieval_top_k
    vec = vec if vec is not None else embed_query(query)
    with conn() as c:
        exact = _day_hits(c, query)
        try:
            exact += [h for h in _pinned_hits(c, query) if h.text not in {e.text for e in exact}]
        except Exception as e:  # a pinned page missing from the index must never break the search
            log.warning("pinned pages failed: %s", e)
        rows = c.execute(
            """
            SELECT ch.url, p.title, ch.section, ch.text, 1 - (ch.embedding <=> %s::vector) AS score, ch.metadata
            FROM chunks ch JOIN pages p ON p.url = ch.url
            ORDER BY ch.embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, vec, k),
        ).fetchall()
    hits = [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=float(r[4]), metadata=r[5] or {}) for r in rows]
    seen = {h.url for h in exact}
    return exact + [h for h in hits if h.url not in seen]


def confident(hits: list[Hit], floor: float | None = None) -> bool:
    """Pure decision rule (unit-tested): the best hit must clear the floor."""
    floor = settings.retrieval_min_score if floor is None else floor
    return bool(hits) and hits[0].score >= floor
