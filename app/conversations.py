"""The visitor's own past conversations (the widget's Messages screen).

A conversation is a chat session (`sessions.session_id`); its turns are in `messages`. Ownership: the browser's
persistent visitor id (localStorage, sent as X-Visitor-Id) or, when signed in, the verified user id. A visitor can
only list, read and mark their own sessions. Unread = assistant turns newer than `sessions.last_read_at`.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import conn

log = logging.getLogger("conversations")

_OWNER = "(s.visitor_id = %(vid)s OR (%(uid)s::text IS NOT NULL AND s.user_id = %(uid)s))"


def _args(visitor_id: str | None, user_id: str | None) -> dict[str, Any]:
    return {"vid": visitor_id or "", "uid": user_id or None}


def list_for(visitor_id: str | None, user_id: str | None, limit: int = 50) -> list[dict[str, Any]]:
    """Newest first; only sessions where the visitor actually said something."""
    if not visitor_id and not user_id:
        return []
    with conn() as c:
        rows = c.execute(
            f"""SELECT s.session_id, s.first_seen, s.last_read_at,
                       lm.ts, lm.role, lm.text, lm.outcome,
                       (SELECT count(*) FROM messages m WHERE m.session_id = s.session_id AND m.role = 'assistant'
                          AND m.ts > COALESCE(s.last_read_at, '-infinity'::timestamptz)) AS unread,
                       (SELECT count(*) FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user') AS questions,
                       (SELECT count(*) FROM leads l WHERE l.session_id = s.session_id AND l.status = 'handover') AS handovers,
                       s.title, s.title_source,
                       (SELECT text FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user' ORDER BY m.id LIMIT 1) AS first_message
                FROM sessions s
                JOIN LATERAL (SELECT ts, role, text, outcome FROM messages m WHERE m.session_id = s.session_id
                              ORDER BY m.id DESC LIMIT 1) lm ON true
                WHERE {_OWNER}
                  AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user')
                ORDER BY lm.ts DESC LIMIT %(limit)s""",
            {**_args(visitor_id, user_id), "limit": max(1, min(limit, 200))},
        ).fetchall()
    from app.titles import fallback_title

    return [{"session_id": r[0], "started": r[1], "last_read_at": r[2], "last_ts": r[3], "last_role": r[4],
             "preview": (r[5] or "")[:200], "last_outcome": r[6], "unread": int(r[7]), "questions": int(r[8]),
             "handovers": int(r[9]), "title": r[10] or fallback_title(r[12]), "title_source": r[11] or ("fallback" if not r[10] else None),
             "first_message": (r[12] or "")[:200]} for r in rows]


def history(session_id: str, visitor_id: str | None, user_id: str | None) -> dict[str, Any] | None:
    """Full transcript of one of the visitor's sessions, or None if it is not theirs."""
    if not session_id or (not visitor_id and not user_id):
        return None
    with conn() as c:
        own = c.execute(f"SELECT 1 FROM sessions s WHERE s.session_id = %(sid)s AND {_OWNER}",
                        {**_args(visitor_id, user_id), "sid": session_id}).fetchone()
        if not own:
            return None
        rows = c.execute(
            """SELECT id, ts, role, text, sources, feedback, outcome FROM messages
               WHERE session_id = %s ORDER BY id""", (session_id,)).fetchall()
    return {"session_id": session_id,
            "messages": [{"id": r[0], "ts": r[1], "role": "user" if r[2] == "user" else "bot", "text": r[3],
                          "sources": r[4] or [], "feedback": r[5], "outcome": r[6]} for r in rows]}


def mark_read(session_id: str, visitor_id: str | None, user_id: str | None) -> bool:
    if not session_id or (not visitor_id and not user_id):
        return False
    with conn() as c:
        n = c.execute(f"UPDATE sessions s SET last_read_at = now() WHERE s.session_id = %(sid)s AND {_OWNER}",
                      {**_args(visitor_id, user_id), "sid": session_id}).rowcount
        c.commit()
    return n > 0


def unread_total(visitor_id: str | None, user_id: str | None) -> int:
    """Conversations (not messages) with something unread, for the Messages tab badge."""
    return sum(1 for cv in list_for(visitor_id, user_id) if cv["unread"] > 0)
