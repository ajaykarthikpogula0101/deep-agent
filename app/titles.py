"""Conversation titles for the Messages screen.

After the first exchange (visitor message + assistant reply) a small, cheap model call sums the conversation up in
3–6 words; the title is stored on `sessions` and never regenerated on load. Rules:
  * no title yet and ≥1 exchange            -> generate
  * title is a greeting placeholder          -> regenerate on the next real visitor turn
  * exactly 6 visitor turns, auto title made before turn 6 -> regenerate once (topic may have moved on)
  * title_source = 'user'                    -> never touched
Until a title exists the list falls back to the visitor's first message cut to ~40 characters.
Generation runs on a background thread; failures are logged and the fallback stays.
"""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import settings
from app.db import conn

log = logging.getLogger("titles")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="title")
_inflight: set[str] = set()
_lock = threading.Lock()

GREETING_RE = re.compile(r"^\s*(hi|hello|hey|hiya|yo|good (morning|afternoon|evening|day)|morning|evening|greetings|sup|what'?s up|how are you\??|thanks?|thank you|ok|okay|test(ing)?)[\s!.?,]*$", re.I)
GREETING_TITLE = "Quick hello"
PROMPT = ("Summarize this conversation's topic as a 3-6 word title. Title Case, no quotes, no punctuation at the end. "
          "If the visitor only greeted or made small talk, answer exactly: Quick hello. Reply with the title only.")


def clean_title(raw: str | None) -> str:
    t = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    t = re.sub(r"^(title\s*:\s*)", "", t, flags=re.I).strip().strip("\"'“”‘’`")
    t = re.sub(r"[.!?:;,]+$", "", t).strip()
    words = t.split()
    if len(words) > 8:
        t = " ".join(words[:8])
    return t[:60]


def fallback_title(first_message: str | None) -> str:
    m = re.sub(r"\s+", " ", (first_message or "")).strip()
    m = re.sub(r"\[attached: ([^\]]+)\]\(\S+\)", r"\1", m).replace("[GIF]", "GIF")
    if not m:
        return "New conversation"
    if GREETING_RE.match(m):
        return GREETING_TITLE
    return m if len(m) <= 40 else m[:40].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _state(session_id: str) -> dict[str, Any] | None:
    with conn() as c:
        s = c.execute("SELECT title, title_source, title_turns FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
        if not s:
            return None
        turns = c.execute("SELECT count(*) FROM messages WHERE session_id = %s AND role = 'user'", (session_id,)).fetchone()[0]
        rows = c.execute("SELECT role, text FROM messages WHERE session_id = %s ORDER BY id LIMIT 12", (session_id,)).fetchall()
    return {"title": s[0], "source": s[1], "title_turns": s[2], "turns": int(turns), "rows": rows}


def should_generate(state: dict[str, Any]) -> bool:
    """Pure decision rule (unit-tested)."""
    if state["source"] == "user" or state["turns"] < 1:
        return False
    if not state["title"]:
        return True
    if state["title"] == GREETING_TITLE and state["turns"] >= 2:
        return True
    return state["turns"] == 6 and state["source"] == "auto" and (state["title_turns"] or 0) < 6


def _ask_model(rows: list[tuple[str, str]]) -> str:
    from openai import OpenAI

    squash = lambda s: re.sub(r"\s+", " ", s or "")[:400]
    convo = "\n".join(("Visitor: " if r == "user" else "Assistant: ") + squash(t) for r, t in rows)
    client = OpenAI(api_key=settings.chat_api_key, base_url=settings.llm_base_url or None,
                    default_headers={"HTTP-Referer": settings.site_base_url, "X-Title": "deependhq assistant"})
    r = client.chat.completions.create(model=settings.chat_model, temperature=0.2, max_tokens=24,
                                       messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": convo}])
    return clean_title(r.choices[0].message.content)


def generate(session_id: str, force: bool = False, ask=None) -> dict[str, Any]:
    """Generate (or regenerate) now. Returns {"title", "generated": bool}. `ask` is injectable for tests."""
    state = _state(session_id)
    if not state:
        return {"title": None, "generated": False}
    if state["source"] == "user":  # a visitor's own title is never overwritten, not even on force
        return {"title": state["title"], "generated": False}
    if not force and not should_generate(state):
        return {"title": state["title"], "generated": False}
    first = next((t for r, t in state["rows"] if r == "user"), "")
    if GREETING_RE.match(first or "") and state["turns"] < 2:
        title = GREETING_TITLE
    else:
        try:
            title = (ask or _ask_model)(state["rows"]) or fallback_title(first)
        except Exception as e:
            log.warning("title generation failed for %s: %s", session_id, e)
            return {"title": state["title"], "generated": False}
    with conn() as c:
        c.execute("UPDATE sessions SET title = %s, title_source = 'auto', title_turns = %s WHERE session_id = %s AND COALESCE(title_source, '') <> 'user'",
                  (title, state["turns"], session_id))
        c.commit()
    return {"title": title, "generated": True}


def maybe_generate_async(session_id: str | None) -> None:
    """Called after every assistant turn; cheap check first, model call on a worker thread."""
    if not session_id:
        return
    with _lock:
        if session_id in _inflight:
            return
        _inflight.add(session_id)

    def run():
        try:
            generate(session_id)
        except Exception as e:
            log.warning("title job failed for %s: %s", session_id, e)
        finally:
            with _lock:
                _inflight.discard(session_id)

    _executor.submit(run)


def rename(session_id: str, title: str, visitor_id: str | None, user_id: str | None) -> str | None:
    """Visitor renames their own conversation. Returns the stored title or None if not theirs."""
    title = clean_title(title)
    if not title:
        return None
    with conn() as c:
        n = c.execute(
            """UPDATE sessions s SET title = %(t)s, title_source = 'user' WHERE s.session_id = %(sid)s
               AND (s.visitor_id = %(vid)s OR (%(uid)s::text IS NOT NULL AND s.user_id = %(uid)s))""",
            {"t": title, "sid": session_id, "vid": visitor_id or "", "uid": user_id or None}).rowcount
        c.commit()
    return title if n else None
