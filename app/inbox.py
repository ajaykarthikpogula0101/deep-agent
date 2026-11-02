"""Conversation inbox: every turn is stored with its outcome, visitors can rate answers, and the owner gets
Fin-style reporting (resolution rate, satisfaction, hand-overs, unanswered questions) plus a human hand-over path.

Outcomes of an assistant turn: answered | custom | refused | injection | booking | handover | error | stopped.
"Resolved" for the resolution rate = answered + custom + booking (the visitor got what they came for);
refused + handover + error are the gaps worth reading.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app import enrich
from app.config import settings
from app.db import conn, log_event

log = logging.getLogger("inbox")

_HUMAN_RE = re.compile(
    r"\b(talk|speak|chat|connect|get in touch|contact|reach)\b[^.?!]{0,30}\b(human|person|someone|somebody|agent|"
    r"support|team|real)\b|\b(real person|live agent|human being|a human|an agent)\b|\bnot a bot\b", re.I)


def wants_human(text: str) -> bool:
    """'Can I talk to a real person?' Booking intent ('book a call') is checked first by the caller."""
    return bool(_HUMAN_RE.search(text or ""))


# ---------------------------------------------------------------- logging turns
def log_message(session_id: str | None, role: str, text: str, *, question: str | None = None, outcome: str | None = None,
                reason: str | None = None, sources: list[dict] | None = None, latency_ms: int | None = None,
                model: str | None = None) -> int | None:
    """Never raises: the inbox is a side channel. Also guarantees the session has a sessions row (bare if need be)."""
    from app.tracking import valid_sid  # lazy, like save_handover's: no import cycle

    if not session_id or not text:
        return None
    try:
        with conn() as c:
            if valid_sid(session_id):
                c.execute("""INSERT INTO sessions(session_id, channel, geo_status) VALUES (%s, 'direct', 'unknown')
                             ON CONFLICT (session_id) DO NOTHING""", (session_id,))
            row = c.execute(
                """INSERT INTO messages(session_id, role, text, question, outcome, reason, sources, latency_ms, model)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id""",
                (session_id, role, text[:6000], (question or "")[:2000] or None, outcome, (reason or "")[:300] or None,
                 json.dumps(sources or []), latency_ms, model),
            ).fetchone()
            c.commit()
        return int(row[0])
    except Exception as e:
        log.warning("log_message failed: %s", e)
        return None


def set_feedback(message_id: int, rating: int, note: str | None, session_id: str | None) -> bool:
    """Thumbs up (1) or down (-1) on an assistant message. The session must own the message."""
    if rating not in (1, -1):
        return False
    with conn() as c:
        n = c.execute(
            """UPDATE messages SET feedback = %s, feedback_note = %s, feedback_at = now()
               WHERE id = %s AND role = 'assistant' AND (%s::text IS NULL OR session_id = %s)""",
            (rating, (note or "").strip()[:1000] or None, message_id, session_id, session_id),
        ).rowcount
        c.commit()
    if n:
        log_event("feedback", session_id, {"message_id": message_id, "rating": rating, "note": (note or "")[:200]})
    return n > 0


# ---------------------------------------------------------------- human hand-over
def save_handover(session_id: str | None, name: str, email: str, message: str, send_brief, send_visitor=None,
                  chat_line: str | None = None) -> dict[str, Any]:
    """Store the request as a lead (status 'handover'), email the host, acknowledge the visitor.
    `chat_line` is what the chat history says about it (Email Deep, app/escalate.chat_line); the older line otherwise.
    Returns {"lead_id", "brief_sent", "visitor_mailed"}."""
    from app.tracking import attach_lead, describe_session

    if send_visitor is None:
        from app.booking.email import send_visitor_confirmation as send_visitor

    name, email, message = name.strip()[:120], email.strip()[:200], message.strip()[:2000]
    origin = describe_session(session_id)
    data = enrich.lookup(email)
    company = enrich.summary(data)
    with conn() as c:
        row = c.execute(
            """INSERT INTO leads(name, email, reason, slot_start, visitor_tz, status, schedule_slug, session_id, company, enrichment)
               VALUES (%s, %s, %s, NULL, NULL, 'handover', NULL, %s, %s, %s::jsonb) RETURNING id""",
            (name, email, message, session_id, company or None, json.dumps(data, default=str)),
        ).fetchone()
        c.commit()
    lead_id = int(row[0])
    attach_lead(session_id, lead_id)
    transcript = recent_transcript_text(session_id)
    lead = {"name": name, "email": email, "reason": message, "status": "handover", "origin": origin,
            "note": ("Recent conversation:\n" + transcript) if transcript else "", "session_id": session_id,
            "schedule": "-", "slot_label_host": "-", "slot_label_visitor": "-", "visitor_tz": "-",
            "company": company, "enrichment": data}
    sent = False
    try:
        sent = bool(send_brief(lead))
    except Exception as e:
        log.error("handover brief failed: %s", e)
    if sent:
        with conn() as c:
            c.execute("UPDATE leads SET brief_sent = true WHERE id = %s", (lead_id,))
            c.commit()
    mailed = False
    try:
        mailed = bool(send_visitor(lead))
    except Exception as e:
        log.error("handover visitor ack failed: %s", e)
    log_event("handover", session_id, {"lead_id": lead_id, "brief_sent": sent, "visitor_mailed": mailed, "origin": origin})
    if session_id:
        try:  # the conversation now waits for the team; Deep can answer it from the console (app/team.py)
            from app import team

            team.set_status(session_id, "waiting")
        except Exception as e:
            log.warning("team status failed: %s", e)
    log_message(session_id, "assistant", chat_line or f"Hand-over request sent to {settings.host_email}.", outcome="handover",
                question=message)
    return {"lead_id": lead_id, "brief_sent": sent, "visitor_mailed": mailed}


def recent_transcript_text(session_id: str | None, limit: int = 8) -> str:
    if not session_id:
        return ""
    try:
        with conn() as c:
            rows = c.execute("""SELECT role, text FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s""",
                             (session_id, limit)).fetchall()
    except Exception:
        return ""
    return "\n".join(f"  {'Visitor' if r[0] == 'user' else 'Assistant'}: {r[1][:300]}" for r in reversed(rows))


# ---------------------------------------------------------------- reporting
_RESOLVED = ("answered", "custom", "booking")


def metrics(days: int = 7) -> dict[str, Any]:
    days = max(1, min(days, 365))
    with conn() as c:
        row = c.execute(
            """SELECT count(DISTINCT session_id),
                      count(*) FILTER (WHERE role = 'user'),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = ANY(%s)),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = 'refused'),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = 'handover'),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = 'custom'),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = 'error'),
                      count(*) FILTER (WHERE feedback = 1), count(*) FILTER (WHERE feedback = -1),
                      percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE latency_ms IS NOT NULL)
               FROM messages WHERE ts > now() - make_interval(days => %s)""",
            (list(_RESOLVED), days)).fetchone()
        leads = c.execute(
            """SELECT count(*) FILTER (WHERE status IN ('handoff', 'booked')), count(*) FILTER (WHERE status = 'handover'),
                      count(*) FILTER (WHERE status = 'enquiry')
               FROM leads WHERE ts > now() - make_interval(days => %s)""", (days,)).fetchone()
        daily = c.execute(
            """SELECT date_trunc('day', ts)::date AS d, count(DISTINCT session_id),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = ANY(%s)),
                      count(*) FILTER (WHERE role = 'assistant' AND outcome = 'refused')
               FROM messages WHERE ts > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 1""",
            (list(_RESOLVED), days)).fetchall()
        rated = c.execute(
            """SELECT count(*), avg(rating), count(*) FILTER (WHERE rating >= 4) FROM sessions
               WHERE rating IS NOT NULL AND rated_at > now() - make_interval(days => %s)""", (days,)).fetchone()
        team = c.execute(
            """SELECT count(*) FILTER (WHERE team_status = 'waiting'), count(*) FILTER (WHERE team_status = 'replied'),
                      (SELECT count(*) FROM messages WHERE role = 'agent' AND ts > now() - make_interval(days => %s))
               FROM sessions WHERE team_status IS NOT NULL""", (days,)).fetchone()
        frustrated = c.execute("""SELECT count(DISTINCT session_id) FROM events WHERE kind = 'frustration'
                                    AND ts > now() - make_interval(days => %s)""", (days,)).fetchone()[0]
        top = c.execute(
            """SELECT lower(regexp_replace(trim(question), '\\s+', ' ', 'g')) AS q, count(*)
               FROM messages WHERE role = 'assistant' AND question IS NOT NULL AND ts > now() - make_interval(days => %s)
                 AND (outcome IS NULL OR outcome NOT IN ('injection', 'stopped', 'error'))
               GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10""", (days,)).fetchall()
    sessions, questions, resolved, refused, handovers, custom, errors, up, down, p50 = row
    answered_turns = resolved + refused + handovers + errors
    return {
        "days": days,
        "conversations": int(sessions), "questions": int(questions),
        "resolved": int(resolved), "refused": int(refused), "handovers": int(handovers), "custom": int(custom), "errors": int(errors),
        "resolution_rate": round(resolved / answered_turns, 3) if answered_turns else None,
        "bookings": int(leads[0]), "handover_leads": int(leads[1]), "enquiries": int(leads[2]),
        "csat": {"up": int(up), "down": int(down), "score": round(up / (up + down), 3) if (up + down) else None},
        "median_latency_ms": int(p50) if p50 is not None else None,
        "conversation_rating": {"count": int(rated[0]), "average": round(float(rated[1]), 2) if rated[1] is not None else None,
                                "good_share": round(rated[2] / rated[0], 3) if rated[0] else None},
        "team": {"waiting": int(team[0]), "replied": int(team[1]), "replies": int(team[2])},
        "frustrated": int(frustrated),   # chats where the visitor seemed frustrated (app/mood.py)
        "daily": [{"day": str(d), "conversations": int(s), "resolved": int(r), "refused": int(f)} for d, s, r, f in daily],
        "top_questions": [{"question": q, "count": int(n)} for q, n in top],
    }


def conversations(days: int = 7, limit: int = 100) -> list[dict[str, Any]]:
    days, limit = max(1, min(days, 365)), max(1, min(limit, 500))
    with conn() as c:
        rows = c.execute(
            """SELECT m.session_id, min(m.ts), max(m.ts), count(*) FILTER (WHERE m.role = 'user'),
                      (array_agg(m.text ORDER BY m.id) FILTER (WHERE m.role = 'user'))[1],
                      count(*) FILTER (WHERE m.outcome = ANY(%s)), count(*) FILTER (WHERE m.outcome = 'refused'),
                      count(*) FILTER (WHERE m.outcome = 'handover'), count(*) FILTER (WHERE m.feedback = 1),
                      count(*) FILTER (WHERE m.feedback = -1),
                      s.city, s.country_code, s.channel, s.referrer_host, s.leads, s.team_status, s.rating,
                      EXISTS (SELECT 1 FROM events e WHERE e.session_id = m.session_id AND e.kind = 'frustration')
               FROM messages m LEFT JOIN sessions s ON s.session_id = m.session_id
               WHERE m.ts > now() - make_interval(days => %s)
               GROUP BY m.session_id, s.city, s.country_code, s.channel, s.referrer_host, s.leads, s.team_status, s.rating
               ORDER BY max(m.ts) DESC LIMIT %s""",
            (list(_RESOLVED), days, limit)).fetchall()
    cols = ["session_id", "started", "last", "questions", "first_question", "resolved", "refused", "handovers", "up", "down",
            "city", "country_code", "channel", "referrer_host", "leads", "team_status", "rating", "frustrated"]
    return [dict(zip(cols, r)) for r in rows]


def transcript(session_id: str) -> dict[str, Any]:
    with conn() as c:
        rows = c.execute(
            """SELECT id, ts, role, text, outcome, reason, sources, latency_ms, feedback, feedback_note, author
               FROM messages WHERE session_id = %s ORDER BY id""", (session_id,)).fetchall()
        st = c.execute("SELECT team_status, rating, rating_note FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
        s = c.execute(
            """SELECT first_seen, city, region, country_code, channel, referrer_host, page, client_tz, user_agent, visits
               FROM (SELECT s.*, (SELECT count(*) FROM sessions v WHERE v.visitor_id = s.visitor_id AND s.visitor_id IS NOT NULL) AS visits
                     FROM sessions s WHERE s.session_id = %s) x""", (session_id,)).fetchone()
        leads = c.execute("""SELECT id, ts, name, email, reason, status, slot_start, company, confirmed_at, nudged_at
                             FROM leads WHERE session_id = %s ORDER BY id""", (session_id,)).fetchall()
    mcols = ["id", "ts", "role", "text", "outcome", "reason", "sources", "latency_ms", "feedback", "feedback_note", "author"]
    scols = ["first_seen", "city", "region", "country_code", "channel", "referrer_host", "page", "client_tz", "user_agent", "visits"]
    lcols = ["id", "ts", "name", "email", "reason", "status", "slot_start", "company", "confirmed_at", "nudged_at"]
    from app import session_memory  # admin console only (the Memory panel)

    mem = session_memory.row(session_id)
    return {"session_id": session_id, "messages": [dict(zip(mcols, r)) for r in rows],
            "session": dict(zip(scols, s)) if s else None, "leads": [dict(zip(lcols, r)) for r in leads],
            "memory": mem if mem and not mem["forgotten_at"] else None, "forgotten_at": (mem or {}).get("forgotten_at"),
            "team_status": st[0] if st else None, "rating": st[1] if st else None, "rating_note": st[2] if st else None}


def gaps(days: int = 30, limit: int = 50) -> dict[str, Any]:
    """What the bot could not do: unanswered questions grouped, and answers people marked down."""
    days, limit = max(1, min(days, 365)), max(1, min(limit, 200))
    with conn() as c:
        unanswered = c.execute(
            """SELECT lower(regexp_replace(trim(question), '\\s+', ' ', 'g')) AS q, count(*), max(ts), max(reason)
               FROM messages WHERE role = 'assistant' AND outcome IN ('refused', 'handover', 'error') AND question IS NOT NULL
                 AND ts > now() - make_interval(days => %s)
               GROUP BY 1 ORDER BY 2 DESC, 3 DESC LIMIT %s""", (days, limit)).fetchall()
        down = c.execute(
            """SELECT id, session_id, ts, question, text, feedback_note FROM messages
               WHERE role = 'assistant' AND feedback = -1 AND ts > now() - make_interval(days => %s)
               ORDER BY ts DESC LIMIT %s""", (days, limit)).fetchall()
    return {"days": days,
            "unanswered": [{"question": q, "count": int(n), "last": str(t), "reason": r} for q, n, t, r in unanswered],
            "thumbs_down": [dict(zip(["id", "session_id", "ts", "question", "answer", "note"], r)) for r in down]}
