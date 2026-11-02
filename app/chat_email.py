"""Email me this chat: the visitor gets the whole conversation, with the pages each answer used, in their inbox.

send(session_id, email, name)  -> {"ok", "to", "messages"}: built from the stored conversation (never from what the page
                                  sends), so it holds exactly what was said: the visitor's questions, the assistant's answers
                                  (prose, with their sources listed under each), and Deep's own replies from the team.
                                  The email's Reply-To is the host, so a reply reaches a person, with a "Book a call" button
                                  when a booking link is configured.
Kept as a lead            the address is stored in leads (status 'transcript', with the chat's session): Deep sees it under
                          Bookings → leads, the pre-call score and the hot-lead alert count it like an enquiry. The form tells
                          the visitor so ("Deep may follow up on your questions").
Limits                    per chat MAX_PER_SESSION_HOUR an hour, per address MAX_PER_EMAIL_DAY a day (so the form can't be used to
                          send mail to strangers), only a conversation the browser owns (app/conversations.owns), and only once
                          it has an answer.
Switch: CHAT_EMAIL_ENABLED (on).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.db import conn, log_event

log = logging.getLogger("chat_email")

MAX_PER_SESSION_HOUR = 3
MAX_PER_EMAIL_DAY = 5
MAX_MESSAGES = 40
MAX_ANSWER_CHARS = 3000
_SKIP = ("(no text)", "(stopped before any text)")


class Limited(Exception):
    """Too many emails for this chat or this address."""


class Empty(Exception):
    """Nothing to send yet: no answer in this chat."""


def _array(src: str, start: int) -> tuple[Any, int]:
    """The JSON array that opens at src[start] (strings in double quotes, as openui-lang writes them), and where it ends."""
    depth, i, quoted = 0, start, False
    while i < len(src):
        ch = src[i]
        if quoted:
            if ch == "\\":
                i += 1
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(src[start:i + 1]), i + 1
        i += 1
    raise ValueError("unclosed array")


def table(program: str) -> dict[str, Any] | None:
    """The Table(columns, rows) of an answer card (app/ui_cards.py), e.g. a comparison, so the email carries it too."""
    try:
        at = program.index("Table(")
        cols, end = _array(program, program.index("[", at))
        rows, _ = _array(program, program.index("[", end))
        if isinstance(cols, list) and isinstance(rows, list) and all(isinstance(r, list) for r in rows):
            return {"columns": [str(c) for c in cols], "rows": [[str(x) for x in r] for r in rows][:8]}
    except (ValueError, TypeError):
        pass
    return None


def turns(session_id: str) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("""SELECT id, role, text, sources, author, ts FROM messages WHERE session_id = %s AND role IN ('user', 'assistant', 'agent')
                            ORDER BY id DESC LIMIT %s""", (session_id, MAX_MESSAGES)).fetchall()
        cards = {str(r[0]): r[1] for r in c.execute("""SELECT detail->>'message_id', detail->>'program' FROM events
                                                         WHERE session_id = %s AND kind = 'ui_card' AND detail->>'complete' = 'true'""",
                                                      (session_id,)).fetchall()}
    out = []
    for mid, role, text, sources, author, ts in reversed(rows):
        t = (text or "").strip()
        if not t or t.startswith(_SKIP):
            continue
        out.append({"role": role, "text": t, "sources": sources or [], "author": author, "ts": ts,
                    "table": table(cards[str(mid)]) if role == "assistant" and cards.get(str(mid)) else None})
    return out


def _plain(text: str) -> list[str]:
    """Markdown to the plain lines templates.html_wrap understands: bullets as "• ", no ** or #."""
    lines = []
    for ln in text.replace("\r", "").split("\n"):
        ln = re.sub(r"\*\*(.+?)\*\*", r"\1", ln)
        ln = re.sub(r"^#{1,6}\s*", "", ln).rstrip()
        ln = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", ln)
        if re.match(r"^\s*[-*]\s+", ln):
            ln = "• " + re.sub(r"^\s*[-*]\s+", "", ln)
        elif re.match(r"^\s*\d+[.)]\s+", ln):
            ln = "• " + re.sub(r"^\s*\d+[.)]\s+", "", ln)
        # a line like "Pricing:   on request" would turn into a facts row in html_wrap: keep it a sentence
        ln = re.sub(r"^([A-Za-z ]{1,12}):\s{2,}", r"\1: ", ln)
        if ln.strip():
            lines.append(ln)
    return lines


def _cited(text: str, sources: list[dict]) -> list[dict]:
    used = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
    return [s for s in sources if s.get("url") and (not used or s.get("n") in used)][:6]


def render(ts: list[dict[str, Any]], name: str = "", title: str = "") -> tuple[str, str]:
    host = settings.host_name_short or "Deep"
    site = urlparse(settings.site_base_url).netloc.removeprefix("www.") or "deependhq.com"
    first = (name or "").strip().split(" ")[0]
    subject = f"Your chat with {host}'s assistant" + (f": {title}" if title else "")
    out = [f"Hi {first}," if first else "Hi there,",
           f"Here is your conversation with {host}'s assistant on {site}, as you asked. The pages each answer used are listed under it."]
    for t in ts:
        if t["role"] == "user":
            out += ["YOU ASKED"] + _plain(t["text"])
        elif t["role"] == "agent":
            out += [f"{(t.get('author') or host).upper()} REPLIED"[:40]] + _plain(t["text"])
        else:
            text = t["text"] if len(t["text"]) <= MAX_ANSWER_CHARS else t["text"][:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + " …"
            out += ["THE ASSISTANT"] + _plain(text)
            tb = t.get("table")
            if tb and len(tb["columns"]) >= 2:   # an answer card's table (a comparison): one line per row
                cols = tb["columns"]
                out.append("At a glance")
                for r in tb["rows"]:
                    cells = [f"{cols[i]}: {r[i]}" for i in range(1, min(len(cols), len(r))) if r[i] and r[i] != "-"]
                    if r and cells:
                        out.append(f"• {r[0]} — " + " · ".join(cells))
            src = _cited(t["text"], t["sources"])
            if src:
                out.append("Pages this answer used")
                out += [f"• [{s.get('n')}] {s.get('title') or s['url']} — {s['url']}" if s.get("n") else f"• {s.get('title') or s['url']} — {s['url']}"
                        for s in src]
    out += ["WHAT NEXT",
            f"Reply to this email and it reaches {host} directly."
            + (" Or book a short call with the button above." if settings.zoom_booking_base else ""),
            "You got this email because you asked for this chat in the assistant. We use your address to send it and so "
            f"{host} can follow up on your questions; reply \"stop\" and we won't contact you again."]
    return subject, "\n".join(out)


def _counts(session_id: str, email: str) -> tuple[int, int]:
    with conn() as c:
        per_chat = c.execute("""SELECT count(*) FROM events WHERE kind = 'chat_email' AND session_id = %s
                                AND ts > now() - interval '1 hour'""", (session_id,)).fetchone()[0]
        per_mail = c.execute("""SELECT count(*) FROM events WHERE kind = 'chat_email' AND lower(detail->>'email') = %s
                                AND ts > now() - interval '1 day'""", (email,)).fetchone()[0]
    return int(per_chat), int(per_mail)


def _title(session_id: str) -> str:
    try:
        with conn() as c:
            row = c.execute("SELECT title FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
        return (row[0] or "").strip()[:80] if row else ""
    except Exception:
        return ""


def _keep_lead(session_id: str, name: str, email: str) -> None:
    """The address as a lead (status 'transcript'), once per chat and address."""
    with conn() as c:
        seen = c.execute("SELECT 1 FROM leads WHERE session_id = %s AND lower(email) = %s AND status = 'transcript' LIMIT 1",
                         (session_id, email)).fetchone()
        if not seen:
            c.execute("""INSERT INTO leads(name, email, reason, status, session_id) VALUES (%s, %s, %s, 'transcript', %s)""",
                      (name or "", email, "Asked for this chat by email", session_id))
        c.commit()


def send(session_id: str, email: str, name: str = "", mailer=None) -> dict[str, Any]:
    from app import mailer as mm
    from app import templates

    email = (email or "").strip().lower()
    per_chat, per_mail = _counts(session_id, email)
    if per_chat >= MAX_PER_SESSION_HOUR or per_mail >= MAX_PER_EMAIL_DAY:
        raise Limited()
    ts = turns(session_id)
    if not any(t["role"] in ("assistant", "agent") for t in ts):
        raise Empty()
    subject, body = render(ts, name, _title(session_id))
    body = templates._tidy(body)
    cta = ("Book a call with " + (settings.host_name_short or "Deep"), settings.zoom_booking_base) if settings.zoom_booking_base else None
    (mailer or mm.default).enqueue(email, subject, body, html=templates.html_wrap(subject, body, cta, audience="visitor"),
                                   reply_to=settings.host_email or None, kind="chat_email")
    log_event("chat_email", session_id, {"email": email, "messages": len(ts)})
    try:
        _keep_lead(session_id, name, email)
    except Exception as e:
        log.warning("chat email lead not saved: %s", e)
    return {"ok": True, "to": email, "messages": len(ts)}
