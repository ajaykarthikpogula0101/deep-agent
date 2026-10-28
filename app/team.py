"""Conversations like Fin: the team answers inside the chat, and visitors rate the conversation.

Hand-off thread (Fin's "The team can also help"):
  * the hand-over form (inbox.save_handover) puts the conversation in team_status 'waiting';
  * Deep answers from the console (POST /admin/conversations/{sid}/reply): the reply is a `messages` row with role
    'agent' and the author's name, the status becomes 'replied', and it appears in the visitor's chat (the widget polls
    GET /conversations/{sid}/updates while the chat is open) and as unread in Messages;
  * a reply the visitor has not read within TEAM_EMAIL_AFTER_MINUTES is emailed to them (template visitor_team_reply,
    with a link back to the chat), once (`messages.notified_at`);
  * when the visitor writes again in a conversation that is with the team, the host gets one email per
    TEAM_HOST_NOTIFY_MINUTES with the new message (the assistant keeps answering as before);
  * the console can close or reopen it (POST /admin/conversations/{sid}/status).

Rating (Fin's CSAT): the visitor rates the whole conversation 1-5 (POST /conversations/{sid}/rating), once, with an
optional note; inbox.metrics reports the average and the share of 4-5 ratings.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.config import settings
from app.db import conn, log_event

log = logging.getLogger("team")

STATUSES = ("waiting", "replied", "closed")
_OWNER = "(s.visitor_id = %(vid)s OR (%(uid)s::text IS NOT NULL AND s.user_id = %(uid)s))"


def _owns(c, session_id: str, visitor_id: str | None, user_id: str | None) -> bool:
    if not session_id or (not visitor_id and not user_id):
        return False
    return bool(c.execute(f"SELECT 1 FROM sessions s WHERE s.session_id = %(sid)s AND {_OWNER}",
                          {"sid": session_id, "vid": visitor_id or "", "uid": user_id or None}).fetchone())


# ---------------------------------------------------------------- rating
def rate(session_id: str, visitor_id: str | None, user_id: str | None, score: int, note: str | None = None) -> bool:
    """The visitor's 1-5 rating of the whole conversation; a second rating replaces the first."""
    if score not in (1, 2, 3, 4, 5):
        return False
    with conn() as c:
        if not _owns(c, session_id, visitor_id, user_id):
            return False
        c.execute("UPDATE sessions SET rating = %s, rating_note = %s, rated_at = now() WHERE session_id = %s",
                  (score, (note or "").strip()[:1000] or None, session_id))
        c.commit()
    log_event("conversation_rating", session_id, {"score": score, "note": (note or "")[:200]})
    return True


# ---------------------------------------------------------------- hand-off status
def set_status(session_id: str, status: str | None) -> bool:
    """None = back to the assistant only. Used by the console and by the hand-over form ('waiting')."""
    if status is not None and status not in STATUSES:
        return False
    with conn() as c:
        n = c.execute("UPDATE sessions SET team_status = %s, team_status_at = now() WHERE session_id = %s",
                      (status, session_id)).rowcount
        c.commit()
    return n > 0


def status_of(session_id: str) -> str | None:
    try:
        with conn() as c:
            row = c.execute("SELECT team_status FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------- the team's replies
def reply(session_id: str, text: str, author: str | None = None) -> dict[str, Any] | None:
    """A message from the team in the visitor's chat. None when the conversation does not exist."""
    text = (text or "").strip()[:6000]
    author = (author or settings.team_reply_author or "Deep").strip()[:80]
    if not text:
        return None
    with conn() as c:
        if not c.execute("SELECT 1 FROM sessions WHERE session_id = %s", (session_id,)).fetchone():
            return None
        row = c.execute("""INSERT INTO messages(session_id, role, text, author, outcome) VALUES (%s, 'agent', %s, %s, 'team')
                           RETURNING id, ts""", (session_id, text, author)).fetchone()
        c.execute("UPDATE sessions SET team_status = 'replied', team_status_at = now() WHERE session_id = %s", (session_id,))
        c.commit()
    log_event("team_reply", session_id, {"message_id": int(row[0]), "author": author, "chars": len(text)})
    return {"id": int(row[0]), "ts": row[1], "role": "agent", "author": author, "text": text}


def updates(session_id: str, visitor_id: str | None, user_id: str | None, after_id: int = 0) -> dict[str, Any] | None:
    """For the open chat: team messages newer than `after_id`, and where the hand-off stands. None if not theirs."""
    with conn() as c:
        if not _owns(c, session_id, visitor_id, user_id):
            return None
        rows = c.execute("""SELECT id, ts, text, author FROM messages WHERE session_id = %s AND role = 'agent' AND id > %s
                            ORDER BY id""", (session_id, max(0, int(after_id or 0)))).fetchall()
        st = c.execute("SELECT team_status, rating FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
    return {"session_id": session_id, "team_status": st[0] if st else None, "rating": st[1] if st else None,
            "messages": [{"id": r[0], "ts": r[1], "role": "agent", "author": r[3] or "Deep", "text": r[2]} for r in rows]}


# ---------------------------------------------------------------- emails
def render_reply_email(name: str, author: str, reply_text: str, link: str, tpl: dict[str, str] | None = None) -> tuple[str, str] | None:
    from app import templates

    tpl = tpl or templates.get_templates()
    if (tpl.get("visitor_team_reply_enabled") or "true").lower() != "true":
        return None
    v = templates.build_vars({"name": name, "status": "handover"}, tpl)
    v.update(author=author, reply=reply_text, link=link)
    return (templates.render(tpl["visitor_team_reply_subject"], v).strip(),
            templates.render(tpl["visitor_team_reply_body"], v).strip() + "\n")


def chat_link(session_id: str) -> str:
    return f"{settings.site_base_url.rstrip('/')}/#dh-chat={session_id}"


def _visitor_contact(c, session_id: str) -> tuple[str, str] | None:
    """(name, email) for the conversation: the hand-over form, a booking or lead from it, or a verified sign-in."""
    row = c.execute("""SELECT name, email FROM leads WHERE session_id = %s AND email IS NOT NULL AND email <> ''
                       ORDER BY (status = 'handover') DESC, id DESC LIMIT 1""", (session_id,)).fetchone()
    if row:
        return (row[0] or "", row[1])
    row = c.execute("SELECT user_name, verified_email FROM sessions WHERE session_id = %s AND verified_email IS NOT NULL",
                    (session_id,)).fetchone()
    return (row[0] or "", row[1]) if row else None


def notify_unread_replies(send: Callable[..., Any] | None = None, now: datetime | None = None) -> dict[str, int]:
    """Scheduled every minute: email team replies the visitor has not read after TEAM_EMAIL_AFTER_MINUTES. Never raises."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.team_email_after_minutes)
    sent = skipped = 0
    try:
        with conn() as c:
            rows = c.execute(
                """SELECT m.id, m.session_id, m.text, m.author FROM messages m JOIN sessions s ON s.session_id = m.session_id
                   WHERE m.role = 'agent' AND m.notified_at IS NULL AND m.ts <= %s
                     AND m.ts > COALESCE(s.last_read_at, '-infinity'::timestamptz)
                   ORDER BY m.id LIMIT 50""", (cutoff,)).fetchall()
            for mid, sid, text, author in rows:
                contact = _visitor_contact(c, sid)
                rendered = render_reply_email(contact[0], author or "Deep", text, chat_link(sid)) if contact else None
                if rendered:
                    if send is None:
                        from app import mailer

                        send = mailer.default.enqueue
                    send(contact[1], rendered[0], rendered[1], reply_to=settings.host_email, kind="team_reply", ref=mid)
                    sent += 1
                else:
                    skipped += 1   # no address, or the email is switched off: the reply waits in Messages
                c.execute("UPDATE messages SET notified_at = %s WHERE id = %s", (now, mid))
            c.commit()
    except Exception as e:
        log.error("team reply emails failed: %s", e)
    return {"sent": sent, "skipped": skipped}


def visitor_wrote(session_id: str | None, text: str, send: Callable[..., Any] | None = None) -> bool:
    """The visitor wrote in a conversation that is with the team: tell the host, at most once per
    TEAM_HOST_NOTIFY_MINUTES. The assistant answers as usual. Never raises."""
    if not session_id or not text:
        return False
    try:
        with conn() as c:
            row = c.execute(
                """UPDATE sessions SET team_notified_at = now() WHERE session_id = %s AND team_status IN ('waiting', 'replied')
                     AND (team_notified_at IS NULL OR team_notified_at < now() - make_interval(mins => %s))
                   RETURNING session_id""", (session_id, settings.team_host_notify_minutes)).fetchone()
            contact = _visitor_contact(c, session_id) if row else None
            c.commit()
        if not row:
            return False
        who = f"{contact[0]} <{contact[1]}>" if contact else "A visitor"
        base = (settings.public_base_url or "").rstrip("/")
        body = (f"{who} wrote again in a conversation that is waiting for the team:\n\n{text[:2000]}\n\n"
                + (f"Reply in the console: {base}/admin#conv={session_id}\n" if base else f"Conversation: {session_id}\n")
                + "\nThe assistant answered them as usual; your reply from the console appears in their chat.\n")
        if send is None:
            from app import mailer

            send = mailer.default.enqueue
        send(settings.host_email, f"New message from {contact[0] if contact and contact[0] else 'a visitor'} (ask deep)", body,
             reply_to=contact[1] if contact else None, kind="team_visitor_wrote", ref=session_id)
        return True
    except Exception as e:
        log.warning("visitor_wrote failed: %s", e)
        return False
