"""Weekly digest email to the host: what the assistant did last week, on one screen.

Sent on DIGEST_CRON (default Monday 09:00 host time) while DIGEST_ENABLED; the console (Overview) shows the same
text and has an "email to Deep now" button (POST /admin/digest/send). Content: conversations and questions with the
change against the previous week, resolution rate, satisfaction, bookings / hand-overs / enquiries, median answer
time, the most asked questions, the questions the bot could not answer (each a candidate custom answer), and the
leads with their company (app/enrich.py) and follow-up state (app/nudge.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app import inbox, templates
from app.config import settings

log = logging.getLogger("digest")

MAX_TOP = 8
MAX_GAPS = 8
MAX_LEADS = 25


def leads_recent(days: int, limit: int = MAX_LEADS) -> list[dict[str, Any]]:
    from app.db import conn

    with conn() as c:
        rows = c.execute(
            """SELECT id, ts, name, email, reason, status, slot_start, visitor_tz, schedule_slug, company, confirmed_at, nudged_at
               FROM leads WHERE ts > now() - make_interval(days => %s) ORDER BY ts DESC LIMIT %s""", (days, limit)).fetchall()
    cols = ["id", "ts", "name", "email", "reason", "status", "slot_start", "visitor_tz", "schedule_slug", "company", "confirmed_at", "nudged_at"]
    return [dict(zip(cols, r)) for r in rows]


# ---------------------------------------------------------------- pure rendering (tested without a database)
def _delta(now: int | float | None, before: int | float | None, pct: bool = False) -> str:
    if now is None or before is None:
        return ""
    d = now - before
    if abs(d) < (0.005 if pct else 0.5):
        return "(same as the week before)"
    arrow = "up" if d > 0 else "down"
    return f"({arrow} {abs(round(d * 100))} pts vs the week before)" if pct else f"({arrow} {abs(int(round(d)))} vs the week before)"


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{round(x * 100)}%"


def _lead_state(lead: dict[str, Any]) -> str:
    s = lead.get("status")
    if s == "booked" or lead.get("confirmed_at"):
        return "booked"
    if s == "handoff":
        return "sent to Zoom, not confirmed" + (", reminded" if lead.get("nudged_at") else "")
    if s == "handover":
        return "asked for a human reply"
    if s == "enquiry":
        return "enquiry (scheduler was down)"
    return s or "lead"


def _fmt_ts(ts: Any, tz: str) -> str:
    if not ts:
        return ""
    try:
        return ts.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %H:%M")
    except Exception:
        return str(ts)[:16]


def render(m: dict[str, Any], prev: dict[str, Any] | None, g: dict[str, Any], leads: list[dict[str, Any]],
           period: str, tpl: dict[str, str] | None = None) -> tuple[str, str]:
    """(subject, body) from already-computed numbers. `prev` holds the metrics of the week before (or None)."""
    tpl = tpl or templates.get_templates()
    brand = tpl.get("brand_default") or templates.DEFAULTS["brand_default"]
    host = tpl.get("host_name") or templates.DEFAULTS["host_name"]
    site = settings.site_base_url.replace("https://", "").replace("http://", "")
    tz = settings.host_timezone
    p = prev or {}
    csat = m.get("csat") or {}
    lines = [
        f"Weekly digest · {period}",
        "",
        f"Conversations     {m.get('conversations', 0)}   {_delta(m.get('conversations'), p.get('conversations'))}".rstrip(),
        f"Questions         {m.get('questions', 0)}   {_delta(m.get('questions'), p.get('questions'))}".rstrip(),
        f"Resolution rate   {_pct(m.get('resolution_rate'))}   {_delta(m.get('resolution_rate'), p.get('resolution_rate'), pct=True)}".rstrip(),
        f"Satisfaction      {_pct(csat.get('score'))}   ({csat.get('up', 0)} up · {csat.get('down', 0)} down)",
        f"Bookings          {m.get('bookings', 0)}   · hand-overs {m.get('handover_leads', 0)} · enquiries {m.get('enquiries', 0)}",
    ]
    if m.get("median_latency_ms") is not None:
        lines.append(f"Median answer     {m['median_latency_ms'] / 1000:.1f} s")
    if m.get("errors"):
        lines.append(f"Errors            {m['errors']}")
    lines += ["", "Most asked"]
    top = (m.get("top_questions") or [])[:MAX_TOP]
    lines += [f"  {i}. {q['question']}  ×{q['count']}" for i, q in enumerate(top, 1)] or ["  (nothing yet)"]
    lines += ["", "Couldn't answer (each one is a candidate custom answer: Console → Gaps)"]
    gaps = (g.get("unanswered") or [])[:MAX_GAPS]
    lines += [f"  - {u['question']}  ×{u['count']}" for u in gaps] or ["  (none, good)"]
    if g.get("thumbs_down"):
        lines.append(f"  {len(g['thumbs_down'])} answer(s) were marked not helpful: Console → Gaps.")
    lines += ["", f"Leads ({len(leads)})"]
    for lead in leads:
        who = f"{lead.get('name') or '?'} <{lead.get('email') or '?'}>"
        bits = [_fmt_ts(lead.get("ts"), tz), who]
        if lead.get("company"):
            bits.append(lead["company"].split(" · ")[0])
        if lead.get("schedule_slug"):
            bits.append(lead["schedule_slug"].replace("-", " "))
        if lead.get("slot_start"):
            bits.append("wanted " + _fmt_ts(lead["slot_start"], tz))
        bits.append(_lead_state(lead))
        lines.append("  - " + " · ".join(b for b in bits if b))
        if lead.get("reason"):
            lines.append(f"      \"{str(lead['reason'])[:140]}\"")
    if not leads:
        lines.append("  (none this week)")
    lines += ["", f"Console: {settings.site_base_url}/admin", f"Sent by the {site} assistant to {host}."]
    subject = (f"[{brand}] Weekly digest: {m.get('conversations', 0)} conversations, {m.get('bookings', 0)} bookings · {period}")
    return subject, "\n".join(lines).rstrip() + "\n"


def period_label(days: int, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(ZoneInfo(settings.host_timezone))
    start = end - timedelta(days=days)
    if start.year == end.year:
        return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


# ---------------------------------------------------------------- with the database
def build(days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days or 7), 90))
    m = inbox.metrics(days)
    both = inbox.metrics(days * 2)
    # the week before = the two-week window minus this week (rates are recomputed from the counts)
    prev: dict[str, Any] = {k: both[k] - m[k] for k in ("conversations", "questions", "resolved", "refused", "handovers", "errors")}
    answered = prev["resolved"] + prev["refused"] + prev["handovers"] + prev["errors"]
    prev["resolution_rate"] = round(prev["resolved"] / answered, 3) if answered else None
    g = inbox.gaps(days, 20)
    leads = leads_recent(days)
    subject, body = render(m, prev, g, leads, period_label(days))
    return {"days": days, "subject": subject, "body": body, "to": settings.host_email, "metrics": m}


def send(days: int = 7, to: str | None = None) -> dict[str, Any]:
    from app.booking.email import send_plain
    from app.db import log_event, set_setting

    d = build(days)
    to = to or settings.host_email
    ok = send_plain(to, d["subject"], d["body"])
    try:
        if ok:
            set_setting("digest:last_sent", datetime.now(timezone.utc).isoformat())
        log_event("digest", None, {"ok": ok, "to": to, "days": days, "conversations": d["metrics"]["conversations"]})
    except Exception as e:  # bookkeeping only
        log.warning("digest bookkeeping failed: %s", e)
    return {"ok": ok, "to": to, "subject": d["subject"]}


def run() -> None:
    """Scheduler entry point."""
    if not settings.digest_enabled:
        return
    try:
        r = send(7)
        log.info("weekly digest %s to %s: %s", "sent" if r["ok"] else "NOT sent", r["to"], r["subject"])
    except Exception as e:
        log.error("weekly digest failed: %s", e)
