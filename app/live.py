"""Live chat between a visitor and the team: instant messages, typing, "Seen", and taking over from the assistant.

The hub is in-process (the app runs one uvicorn worker, Dockerfile --workers 1, like app/tracking.py's state): any thread
publishes an event; every open stream (an async SSE response) for that conversation, and the console's stream, gets it at
once. Nothing here is required for correctness: the widget still checks for replies itself (GET /conversations/{sid}/updates)
and the console still reloads its lists, so a dropped stream only costs speed.

Streams
  visitor   GET /conversations/{sid}/live     the team's messages, their typing, take-over on/off (owner only)
  console   GET /admin/live                   everything, every conversation: visitor and assistant messages, typing both
                                              ways, "Seen", take-over and status changes

Take over (sessions.live_agent, live_at)
  take_over(sid, author)   the assistant stops answering in that chat: the visitor's messages go to the team (app/chat.respond
                           answers {"type": "live"} instead), the visitor sees "Deep joined the chat"; the conversation shows
                           as with the team (team_status 'replied' if it had none)
  hand_back(sid)           the assistant answers again; the visitor sees "the assistant is back"
  agent_for(sid)           who has the chat, or None; a take-over with no team activity for LIVE_IDLE_MINUTES ends by itself so
                           a visitor is never left talking to nobody

Seen: the visitor's chat marks itself read (POST /conversations/{sid}/read, sessions.last_read_at); the console shows "Seen"
under the team's messages sent before that moment.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.config import settings
from app.db import conn, log_event

log = logging.getLogger("live")

CONSOLE = "console"
QUEUE_SIZE = 200
PING_SECONDS = 15
VISITOR_EVENTS = {"message", "typing", "live"}   # what a visitor's stream may carry (their side of the conversation only)


# ---------------------------------------------------------------- the hub
class Hub:
    def __init__(self) -> None:
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, topic: str) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        sub = (asyncio.get_running_loop(), asyncio.Queue(maxsize=QUEUE_SIZE))
        with self._lock:
            self._subs.setdefault(topic, set()).add(sub)
        return sub

    def unsubscribe(self, topic: str, sub) -> None:
        with self._lock:
            subs = self._subs.get(topic)
            if subs:
                subs.discard(sub)
                if not subs:
                    self._subs.pop(topic, None)

    def publish(self, topic: str, event: dict[str, Any]) -> int:
        """From any thread. Returns how many open streams got it. Never raises."""
        with self._lock:
            subs = list(self._subs.get(topic, ()))
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_offer, q, event)
            except RuntimeError:   # the loop has closed: the stream is gone
                self.unsubscribe(topic, (loop, q))
        return len(subs)

    def count(self, topic: str) -> int:
        with self._lock:
            return len(self._subs.get(topic, ()))


def _offer(q: asyncio.Queue, event: dict[str, Any]) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:   # a stuck reader drops events; it catches up from the database on reconnect
        pass


hub = Hub()


def _topic(session_id: str) -> str:
    return "s:" + session_id


def emit(session_id: str | None, event: dict[str, Any], visitor: bool = True, console: bool = True) -> None:
    """Publish one event about a conversation to its visitor stream and/or the console. Never raises."""
    if not session_id:
        return
    try:
        ev = {**event, "sid": session_id, "at": datetime.now(timezone.utc).isoformat()}
        if visitor and ev.get("type") in VISITOR_EVENTS:
            hub.publish(_topic(session_id), ev)
        if console:
            hub.publish(CONSOLE, ev)
    except Exception as e:
        log.warning("live emit failed: %s", e)


async def stream(topic: str, is_disconnected, first: dict[str, Any] | None = None) -> AsyncIterator[str]:
    """SSE lines for one subscriber until the client goes away; a comment line every PING_SECONDS keeps proxies open."""
    sub = hub.subscribe(topic)
    try:
        yield "retry: 3000\n\n"
        if first:
            yield "data: " + json.dumps(first, default=str) + "\n\n"
        while True:
            if await is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(sub[1].get(), timeout=PING_SECONDS)
                yield "data: " + json.dumps(ev, default=str) + "\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    finally:
        hub.unsubscribe(topic, sub)


def visitor_topic(session_id: str) -> str:
    return _topic(session_id)


# ---------------------------------------------------------------- take over
def agent_for(session_id: str | None) -> str | None:
    """Who has taken this chat over, or None (the assistant answers). An idle take-over ends by itself. Never raises."""
    if not session_id:
        return None
    try:
        with conn() as c:
            row = c.execute("""SELECT live_agent, live_at > now() - make_interval(mins => %s) FROM sessions WHERE session_id = %s""",
                            (settings.live_idle_minutes, session_id)).fetchone()
        if not row or not row[0]:
            return None
        if not row[1]:
            hand_back(session_id, reason="idle")
            return None
        return row[0]
    except Exception as e:
        log.warning("live state read failed: %s", e)
        return None


def take_over(session_id: str, author: str | None = None) -> dict[str, Any] | None:
    author = (author or settings.team_reply_author or settings.host_name_short or "Deep").strip()[:80]
    with conn() as c:
        n = c.execute("""UPDATE sessions SET live_agent = %s, live_at = now(), team_status = COALESCE(team_status, 'replied'),
                         team_status_at = CASE WHEN team_status IS NULL THEN now() ELSE team_status_at END WHERE session_id = %s""",
                      (author, session_id)).rowcount
        c.commit()
    if not n:
        return None
    log_event("live_takeover", session_id, {"agent": author})
    emit(session_id, {"type": "live", "on": True, "agent": author})
    return {"ok": True, "live_agent": author}


def hand_back(session_id: str, reason: str = "console") -> bool:
    with conn() as c:
        row = c.execute("""UPDATE sessions SET live_agent = NULL WHERE session_id = %s AND live_agent IS NOT NULL RETURNING session_id""",
                        (session_id,)).fetchone()
        c.commit()
    if not row:
        return False
    log_event("live_handback", session_id, {"reason": reason})
    emit(session_id, {"type": "live", "on": False, "reason": reason})
    return True


def touch(session_id: str) -> None:
    """Team activity in a taken-over chat keeps it from ending as idle. Never raises."""
    try:
        with conn() as c:
            c.execute("UPDATE sessions SET live_at = now() WHERE session_id = %s AND live_agent IS NOT NULL", (session_id,))
            c.commit()
    except Exception as e:
        log.warning("live touch failed: %s", e)


# ---------------------------------------------------------------- typing and seen
def typing(session_id: str, who: str, on: bool, author: str | None = None) -> None:
    emit(session_id, {"type": "typing", "who": who, "on": bool(on), **({"author": author} if author else {})},
         visitor=(who == "agent"), console=(who == "visitor" or who == "agent"))


def seen(session_id: str, at: datetime | None = None) -> None:
    emit(session_id, {"type": "seen", "read_at": (at or datetime.now(timezone.utc)).isoformat()}, visitor=False)


# ---------------------------------------------------------------- the console's inbox
VIEWS = ("waiting", "live", "team", "recent")


def inbox(view: str = "waiting", limit: int = 60) -> dict[str, Any]:
    """The console's queue. waiting: the visitor wrote after the team's last message in a chat that is with the team (longest
    wait first); live: taken over; team: every chat with the team; recent: every chat of the last 24 hours."""
    view = view if view in VIEWS else "waiting"
    where = {"waiting": "x.waiting_since IS NOT NULL AND (x.team_status IN ('waiting', 'replied') OR x.live_agent IS NOT NULL)",
             "live": "x.live_agent IS NOT NULL",
             "team": "(x.team_status IN ('waiting', 'replied') OR x.live_agent IS NOT NULL)",
             "recent": "x.last_ts > now() - interval '24 hours'"}[view]
    order = "x.waiting_since ASC NULLS LAST" if view == "waiting" else "x.last_ts DESC"
    with conn() as c:
        rows = c.execute(f"""
            WITH x AS (
              SELECT s.session_id, s.team_status, s.live_agent, s.last_read_at, s.city, s.country_code, s.net_org,
                     COALESCE(NULLIF(s.user_name, ''), (SELECT name FROM leads l WHERE l.session_id = s.session_id AND name <> '' ORDER BY l.id DESC LIMIT 1)) AS name,
                     COALESCE(s.user_email, (SELECT email FROM leads l WHERE l.session_id = s.session_id ORDER BY l.id DESC LIMIT 1)) AS email,
                     lm.text AS last_text, lm.role AS last_role, lm.ts AS last_ts,
                     (SELECT min(m.ts) FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user'
                        AND m.id > COALESCE((SELECT max(a.id) FROM messages a WHERE a.session_id = s.session_id AND a.role = 'agent'), 0)) AS waiting_since,
                     EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.session_id AND e.kind = 'frustration') AS frustrated,
                     EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.session_id AND e.kind = 'buying') AS buying,
                     EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.session_id AND e.kind = 'quote') AS quote
              FROM sessions s
              JOIN LATERAL (SELECT text, role, ts FROM messages m WHERE m.session_id = s.session_id ORDER BY m.id DESC LIMIT 1) lm ON true
              WHERE s.last_seen > now() - interval '30 days')
            SELECT * FROM x WHERE {where} ORDER BY {order} LIMIT %s""", (max(1, min(limit, 200)),)).fetchall()
        counts = c.execute("""
            SELECT count(*) FILTER (WHERE s.live_agent IS NOT NULL),
                   count(*) FILTER (WHERE (s.team_status IN ('waiting', 'replied') OR s.live_agent IS NOT NULL) AND EXISTS (
                     SELECT 1 FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user'
                       AND m.id > COALESCE((SELECT max(a.id) FROM messages a WHERE a.session_id = s.session_id AND a.role = 'agent'), 0)))
            FROM sessions s WHERE s.last_seen > now() - interval '30 days'""").fetchone()
    cols = ["session_id", "team_status", "live_agent", "last_read_at", "city", "country_code", "net_org", "name", "email", "last_text",
            "last_role", "last_ts", "waiting_since", "frustrated", "buying", "quote"]
    items = [dict(zip(cols, r)) for r in rows]
    for it in items:
        it["last_text"] = (it["last_text"] or "")[:160]
    return {"view": view, "items": items, "counts": {"live": int(counts[0]), "waiting": int(counts[1])}}


def profile(session_id: str) -> dict[str, Any]:
    """The right-hand column: who the visitor is, from what the assistant already stores."""
    with conn() as c:
        s = c.execute("""SELECT s.visitor_id, s.city, s.region, s.country, s.country_code, s.channel, s.referrer_host, s.page, s.net_org,
                                s.net_kind, s.user_name, s.user_email, s.verified_email, s.first_seen, s.last_seen, s.team_status, s.live_agent,
                                s.last_read_at, s.rating,
                                (SELECT count(*) FROM sessions v WHERE v.visitor_id = s.visitor_id AND s.visitor_id IS NOT NULL) AS visits
                         FROM sessions s WHERE s.session_id = %s""", (session_id,)).fetchone()
        if not s:
            return {}
        keys = ["visitor_id", "city", "region", "country", "country_code", "channel", "referrer_host", "page", "net_org", "net_kind",
                "user_name", "user_email", "verified_email", "first_seen", "last_seen", "team_status", "live_agent", "last_read_at", "rating", "visits"]
        p = dict(zip(keys, s))
        leads = c.execute("""SELECT name, email, company, status, ts FROM leads WHERE session_id = %s ORDER BY id DESC""", (session_id,)).fetchall()
        bookings = c.execute("""SELECT schedule_name, start_utc, status FROM bookings WHERE session_id = %s ORDER BY start_utc DESC LIMIT 5""",
                             (session_id,)).fetchall()
        flags = [r[0] for r in c.execute("""SELECT DISTINCT kind FROM events WHERE session_id = %s
                                            AND kind IN ('frustration', 'buying', 'quote', 'wrong_fit', 'handover')""", (session_id,)).fetchall()]
        quote = c.execute("""SELECT detail FROM events WHERE session_id = %s AND kind = 'quote' ORDER BY id DESC LIMIT 1""", (session_id,)).fetchone()
        pages = [r[0] for r in c.execute("""SELECT DISTINCT page FROM sessions WHERE visitor_id = %s AND page IS NOT NULL LIMIT 6""",
                                         (p["visitor_id"],)).fetchall()] if p["visitor_id"] else ([p["page"]] if p["page"] else [])
        earlier = int(c.execute("""SELECT count(*) FROM sessions v WHERE v.visitor_id = %s AND v.session_id <> %s AND v.messages > 0""",
                                (p["visitor_id"], session_id)).fetchone()[0]) if p["visitor_id"] else 0
    p.pop("visitor_id", None)
    p["name"] = p.get("user_name") or next((l[0] for l in leads if l[0]), "")
    p["email"] = p.get("verified_email") or p.get("user_email") or next((l[1] for l in leads if l[1]), "")
    p["company"] = next((l[2] for l in leads if l[2]), "") or p.get("net_org") or ""
    p["leads"] = [{"name": l[0], "email": l[1], "status": l[3], "ts": l[4]} for l in leads]
    p["bookings"] = [{"name": b[0], "start_utc": b[1], "status": b[2]} for b in bookings]
    p["flags"] = flags
    p["quote"] = (dict(quote[0]) if quote else None)
    p["pages"] = pages
    p["earlier_chats"] = earlier
    p["score"] = None
    if p["email"]:
        try:
            from app import precall

            sc = precall.score(precall.gather(p["email"], session_id, name=p["name"]))
            p["score"] = {"score": sc["score"], "label": sc["label"]}
        except Exception as e:
            log.info("inbox score failed: %s", e)
    return p
