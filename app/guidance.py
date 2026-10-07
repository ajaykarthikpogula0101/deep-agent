"""Owner-editable behaviour, no code changes needed (the Fin "guidance" and "custom answers" ideas).

Guidance        free text appended to the system prompt: tone, things to push, things to avoid, when to hand over.
                It sits INSIDE the fixed rules (cite only, no outside knowledge, anonymity); it cannot loosen them.
Custom answers  a question + the exact answer the owner wants. The question is embedded; a visitor message whose
                similarity clears CUSTOM_ANSWER_MIN_SCORE gets that answer verbatim, with no model call.
Both are edited from /admin and take effect within GUIDANCE_CACHE_SECONDS.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.config import settings
from app.db import conn
from app.embeddings import embed_query

log = logging.getLogger("guidance")

GUIDANCE_CACHE_SECONDS = 30
GUIDANCE_MAX_CHARS = 4000
_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- guidance text
def get_guidance() -> str:
    """Cached read; never raises (an admin feature must not take the chat down)."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get("guidance")
        if hit and now - hit[0] < GUIDANCE_CACHE_SECONDS:
            return hit[1]
    try:
        with conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key = 'guidance'").fetchone()
        value = (row[0] if row else "").strip()
    except Exception as e:
        log.warning("guidance read failed: %s", e)
        value = ""
    with _lock:
        _cache["guidance"] = (now, value)
    return value


def set_guidance(text: str) -> str:
    text = (text or "").strip()[:GUIDANCE_MAX_CHARS]
    with conn() as c:
        c.execute("""INSERT INTO settings(key, value, updated_at) VALUES ('guidance', %s, now())
                     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""", (text,))
        c.commit()
    with _lock:
        _cache.pop("guidance", None)
    return text


def guidance_block(text: str) -> str:
    """How the guidance is shown to the model. Framed so it extends the rules rather than replacing them."""
    if not text:
        return ""
    return ("\nOWNER GUIDANCE (apply it within the rules above; the rules win if they conflict):\n" + text + "\n")


# ---------------------------------------------------------------- custom answers
def list_custom_answers() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("""SELECT id, question, answer, link, enabled, hits, updated_at
                            FROM custom_answers ORDER BY updated_at DESC""").fetchall()
    return [dict(zip(["id", "question", "answer", "link", "enabled", "hits", "updated_at"], r)) for r in rows]


def add_custom_answer(question: str, answer: str, link: str | None = None) -> int:
    question, answer = question.strip()[:500], answer.strip()[:3000]
    if not question or not answer:
        raise ValueError("question and answer are required")
    vec = embed_query(question)
    with conn() as c:
        row = c.execute("""INSERT INTO custom_answers(question, answer, link, embedding) VALUES (%s, %s, %s, %s)
                           RETURNING id""", (question, answer, (link or "").strip()[:500] or None, vec)).fetchone()
        c.commit()
    return int(row[0])


def update_custom_answer(answer_id: int, *, enabled: bool | None = None, question: str | None = None,
                         answer: str | None = None, link: str | None = None) -> bool:
    sets, args = [], []
    if enabled is not None:
        sets.append("enabled = %s"); args.append(bool(enabled))
    if question is not None and question.strip():
        sets.append("question = %s"); args.append(question.strip()[:500])
        sets.append("embedding = %s"); args.append(embed_query(question.strip()))
    if answer is not None and answer.strip():
        sets.append("answer = %s"); args.append(answer.strip()[:3000])
    if link is not None:
        sets.append("link = %s"); args.append(link.strip()[:500] or None)
    if not sets:
        return False
    sets.append("updated_at = now()")
    with conn() as c:
        n = c.execute(f"UPDATE custom_answers SET {', '.join(sets)} WHERE id = %s", (*args, answer_id)).rowcount
        c.commit()
    return n > 0


def delete_custom_answer(answer_id: int) -> bool:
    with conn() as c:
        n = c.execute("DELETE FROM custom_answers WHERE id = %s", (answer_id,)).rowcount
        c.commit()
    return n > 0


def match_custom_answer(vec: list[float], min_score: float | None = None) -> dict[str, Any] | None:
    """Best enabled custom answer for an already-embedded visitor message, or None below the floor."""
    floor = settings.custom_answer_min_score if min_score is None else min_score
    try:
        with conn() as c:
            row = c.execute("""SELECT id, question, answer, link, 1 - (embedding <=> %s::vector) AS score
                               FROM custom_answers WHERE enabled ORDER BY embedding <=> %s::vector LIMIT 1""",
                            (vec, vec)).fetchone()
            if not row or float(row[4]) < floor:
                return None
            c.execute("UPDATE custom_answers SET hits = hits + 1 WHERE id = %s", (row[0],))
            c.commit()
    except Exception as e:
        log.warning("custom answer lookup failed: %s", e)
        return None
    return {"id": int(row[0]), "question": row[1], "answer": row[2], "link": row[3], "score": float(row[4])}
