"""Vector retrieval with a confidence floor. Below the floor the caller must refuse, not guess."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.db import conn
from app.embeddings import embed_query


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


def search(query: str, k: int | None = None, vec: list[float] | None = None) -> list[Hit]:
    k = k or settings.retrieval_top_k
    vec = vec if vec is not None else embed_query(query)
    with conn() as c:
        exact = _day_hits(c, query)
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
