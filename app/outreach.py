"""Proactive outreach rules: open the greeting bubble with the right message at the right moment.

Today the bubble says the same thing to everyone a few seconds after the page loads. A rule lets the owner say
"if a visitor has read three company pages, offer a call" or "if someone has been on the LakeB2B page for a
minute, offer the walkthrough". The loader (static/widget.js) keeps a small activity record for the visit in
sessionStorage (pages seen, seconds on the page, scroll depth, first referrer) and asks `POST /outreach/check`
whenever something that a rule could care about changes: page load, a time-on-page threshold, a scroll
threshold. The server evaluates the enabled rules in priority order against that activity plus what it knows
about the visitor (return visits, an upcoming booking, their first name), records a firing, and returns the
message to show. Nothing from the activity payload is stored except the page of a firing.

A rule
    trigger   visitor: any | new | returning            booking: any | yes | no (an upcoming call in the calendar)
              page: path pattern for the current page    pages_min + pages_match: distinct pages seen this visit
              dwell_s: seconds on this page              scroll_pct: how far down they scrolled
              referrer: text the referrer host contains  channel: direct|search|social|ai|email|paid|referral|internal
              utm_source: exact value
    message   title, text, replies (quick-reply chips; booking phrasings open the booking flow), intro (the line
              shown at the top of the chat once opened; defaults to text)
    cooldown_hours   how long before the same rule may fire again for the same visitor (device)
    priority         lower fires first when several match

Path patterns: a path matches when it equals the pattern, starts with it, or when a `*` wildcard pattern matches
the whole path (`/company/*`); `|` separates alternatives. Case-insensitive. The path includes the hash
(`/journey.html#day-184`), never the query string.

Templating in title/text/intro: {first_name} {booking} {schedule} {topic} {visits} {page_title}.

Attribution: each firing is an `outreach_events` row. Opening the chat from the bubble stamps opened_at and the
chat session id; "chatted" and "booked" are derived from that session (messages, bookings, leads), so the stats
answer "did this rule lead to anything".
"""
from __future__ import annotations

import fnmatch
import json
import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from app.config import settings
from app.db import conn, get_setting, set_setting

log = logging.getLogger("outreach")

CACHE_SECONDS = 15
MAX_RULES = 50
MAX_PAGES = 50
MAX_DWELL = 1800
VISITOR_CHOICES = ("any", "new", "returning")
BOOKING_CHOICES = ("any", "yes", "no")
CHANNELS = ("direct", "internal", "search", "social", "ai", "email", "paid", "campaign", "referral")
DEFAULT_GREETING_KEY = "outreach:default_greeting"
SEEDED_KEY = "outreach:seeded"
_BOOK_RE = re.compile(r"\b(book|schedule|meeting|appointment|demo call|call with|walkthrough)\b", re.I)

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- rule shape and validation
def empty_trigger() -> dict[str, Any]:
    return {"visitor": "any", "booking": "any", "page": "", "pages_min": 0, "pages_match": "", "dwell_s": 0,
            "scroll_pct": 0, "referrer": "", "channel": "", "utm_source": ""}


def _int(v: Any, lo: int, hi: int, default: int = 0) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _text(v: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def normalise(data: dict[str, Any]) -> dict[str, Any]:
    """Clean a rule from the console (or the seed list) into the stored shape. Raises ValueError with a message
    the console can show when something essential is missing."""
    t_in = data.get("trigger") or {}
    m_in = data.get("message") or {}
    name = _text(data.get("name"), 80)
    if not name:
        raise ValueError("give the rule a name")
    trigger = empty_trigger()
    trigger["visitor"] = t_in.get("visitor") if t_in.get("visitor") in VISITOR_CHOICES else "any"
    trigger["booking"] = t_in.get("booking") if t_in.get("booking") in BOOKING_CHOICES else "any"
    trigger["page"] = _text(t_in.get("page"), 200)
    trigger["pages_min"] = _int(t_in.get("pages_min"), 0, MAX_PAGES)
    trigger["pages_match"] = _text(t_in.get("pages_match"), 200)
    trigger["dwell_s"] = _int(t_in.get("dwell_s"), 0, MAX_DWELL)
    trigger["scroll_pct"] = _int(t_in.get("scroll_pct"), 0, 100)
    trigger["referrer"] = _text(t_in.get("referrer"), 120).lower()
    ch = t_in.get("channel")
    if isinstance(ch, list):
        ch = ",".join(str(x) for x in ch)
    trigger["channel"] = ",".join(c for c in (x.strip().lower() for x in str(ch or "").split(",")) if c in CHANNELS)
    trigger["utm_source"] = _text(t_in.get("utm_source"), 120).lower()
    for key in ("page", "pages_match"):
        for alt in trigger[key].split("|"):
            if alt.strip() and not alt.strip().startswith("/") and "*" not in alt:
                raise ValueError(f"page patterns start with / (got '{alt.strip()}')")
    message = {"title": _text(m_in.get("title"), 80), "text": _text(m_in.get("text"), 300), "intro": _text(m_in.get("intro"), 300)}
    if not message["text"]:
        raise ValueError("write the message the bubble should show")
    replies = m_in.get("replies") or []
    if isinstance(replies, str):
        replies = replies.replace("|", "\n").split("\n")
    message["replies"] = [r for r in (_text(x, 80) for x in replies) if r][:4]
    return {"name": name, "enabled": bool(data.get("enabled", True)), "priority": _int(data.get("priority"), 1, 100, 10),
            "trigger": trigger, "message": message, "cooldown_hours": _int(data.get("cooldown_hours"), 0, 720, 24)}


# ---------------------------------------------------------------- matching (pure, unit-tested)
def path_of(url_or_path: str | None) -> str:
    """'/company/lake-b2b' from a full URL or a path; keeps the hash, drops the query."""
    s = (url_or_path or "").strip()
    if not s:
        return "/"
    if "://" in s:
        u = urlsplit(s)
        s = (u.path or "/") + (("#" + u.fragment) if u.fragment else "")
    else:
        s = re.sub(r"\?[^#]*", "", s)
    return (s or "/")[:500]


def path_matches(pattern: str, path: str) -> bool:
    pattern = (pattern or "").strip()
    if not pattern:
        return True
    p = (path or "/").lower()
    for alt in (a.strip().lower() for a in pattern.split("|")):
        if not alt:
            continue
        if "*" in alt:
            if fnmatch.fnmatchcase(p, alt):
                return True
        elif p == alt or (len(alt) > 1 and p.startswith(alt)):
            return True
    return False


def evaluate(trigger: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """{'match': True} when every condition holds; {'match': False, 'wait': {'dwell_s': n, 'scroll_pct': n}} when
    only time-on-page or scroll depth is still short (the loader asks again once they are reached); {'match': False}
    when a fixed condition fails on this page."""
    t = {**empty_trigger(), **(trigger or {})}
    if t["visitor"] == "new" and ctx.get("returning"):
        return {"match": False}
    if t["visitor"] == "returning" and not ctx.get("returning"):
        return {"match": False}
    if t["booking"] == "yes" and not ctx.get("booking"):
        return {"match": False}
    if t["booking"] == "no" and ctx.get("booking"):
        return {"match": False}
    if not path_matches(t["page"], ctx.get("path") or "/"):
        return {"match": False}
    if t["pages_min"]:
        seen = {p.lower() for p in (ctx.get("pages") or []) if path_matches(t["pages_match"], p)}
        if len(seen) < t["pages_min"]:
            return {"match": False}
    if t["referrer"] and t["referrer"] not in (ctx.get("referrer_host") or "").lower():
        return {"match": False}
    if t["channel"] and (ctx.get("channel") or "direct") not in t["channel"].split(","):
        return {"match": False}
    if t["utm_source"] and (ctx.get("utm_source") or "").lower() != t["utm_source"]:
        return {"match": False}
    wait: dict[str, int] = {}
    if t["dwell_s"] and int(ctx.get("dwell_s") or 0) < t["dwell_s"]:
        wait["dwell_s"] = t["dwell_s"]
    if t["scroll_pct"] and int(ctx.get("scroll_pct") or 0) < t["scroll_pct"]:
        wait["scroll_pct"] = t["scroll_pct"]
    return {"match": True} if not wait else {"match": False, "wait": wait}


def render(text: str, ctx: dict[str, Any]) -> str:
    """Fill {first_name} {booking} {schedule} {topic} {visits} {page_title}; unknown or empty values vanish cleanly."""
    vals = {"first_name": ctx.get("first_name") or "", "booking": ctx.get("booking_label") or "", "schedule": ctx.get("schedule") or "",
            "topic": ctx.get("topic") or "", "visits": str(ctx.get("visits") or ""), "page_title": ctx.get("page_title") or ""}
    out = re.sub(r"\{(\w+)\}", lambda m: vals.get(m.group(1), ""), text or "")
    out = re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"[ \t]{2,}", " ", out))
    out = re.sub(r",\s*(?=[,.!?;:]|$)", "", out)  # a comma left dangling by an empty {first_name}
    return out.strip()


def context(payload: dict[str, Any], facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """The activity snapshot from the loader plus the server-side facts, in the shape evaluate() reads."""
    from app.tracking import classify_channel, parse_utm, referrer_host

    facts = facts or {}
    pages = [path_of(p) for p in (payload.get("pages") or [])[:MAX_PAGES] if isinstance(p, str)]
    path = path_of(payload.get("path") or payload.get("page") or "/")
    if path not in pages:
        pages.append(path)
    first = payload.get("first_page") or payload.get("page") or ""
    utm = parse_utm(first if isinstance(first, str) else "")
    referrer = payload.get("referrer") if isinstance(payload.get("referrer"), str) else ""
    up = facts.get("upcoming") or None
    visits = _int(payload.get("visits"), 0, 100000)
    returning = bool(facts.get("returning")) or visits > 1
    return {"path": path, "pages": pages, "dwell_s": _int(payload.get("dwell_s"), 0, 10 ** 6), "scroll_pct": _int(payload.get("scroll_pct"), 0, 100),
            "referrer_host": referrer_host(referrer), "channel": classify_channel(referrer, utm), "utm_source": utm.get("utm_source", ""),
            "visits": max(visits, int(facts.get("visits") or 0)), "returning": returning,
            "booking": bool(up), "booking_label": (up or {}).get("label_visitor"), "schedule": (up or {}).get("schedule_name"),
            "first_name": ((facts.get("name") or "").strip().split(" ") or [""])[0], "topic": (facts.get("topics") or [None])[0],
            "page_title": _text(payload.get("title"), 120)}


def public_message(rule: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    m = rule["message"]
    text = render(m.get("text", ""), ctx)
    return {"id": rule["id"], "name": rule["name"], "title": render(m.get("title", ""), ctx), "text": text,
            "intro": render(m.get("intro") or "", ctx) or text,
            "replies": [{"label": render(r, ctx), "book": bool(_BOOK_RE.search(r))} for r in m.get("replies", []) if render(r, ctx)]}


# ---------------------------------------------------------------- storage
def _row(r: tuple) -> dict[str, Any]:
    trig, msg = r[5], r[6]
    if isinstance(trig, str):
        trig = json.loads(trig)
    if isinstance(msg, str):
        msg = json.loads(msg)
    return {"id": r[0], "name": r[1], "enabled": bool(r[2]), "priority": int(r[3]), "cooldown_hours": int(r[4]),
            "trigger": {**empty_trigger(), **trig}, "message": msg, "created_at": r[7], "updated_at": r[8]}


_COLS = "id, name, enabled, priority, cooldown_hours, trigger, message, created_at, updated_at"


def list_rules() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(f"SELECT {_COLS} FROM outreach_rules ORDER BY priority, id").fetchall()
    return [_row(r) for r in rows]


def enabled_rules() -> list[dict[str, Any]]:
    """Cached for CACHE_SECONDS; never raises (an outreach failure must not break the page)."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get("rules")
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        rules = [r for r in list_rules() if r["enabled"]]
    except Exception as e:
        log.warning("outreach rules unavailable: %s", e)
        rules = []
    with _lock:
        _cache["rules"] = (now, rules)
    return rules


def invalidate() -> None:
    with _lock:
        _cache.clear()


def create_rule(data: dict[str, Any]) -> dict[str, Any]:
    r = normalise(data)
    with conn() as c:
        n = c.execute("SELECT count(*) FROM outreach_rules").fetchone()[0]
        if n >= MAX_RULES:
            raise ValueError(f"at most {MAX_RULES} rules")
        row = c.execute(
            f"""INSERT INTO outreach_rules(name, enabled, priority, cooldown_hours, trigger, message)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING {_COLS}""",
            (r["name"], r["enabled"], r["priority"], r["cooldown_hours"], json.dumps(r["trigger"]), json.dumps(r["message"]))).fetchone()
        c.commit()
    invalidate()
    return _row(row)


def update_rule(rule_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    """Partial update: only the keys present change (so the console's on/off switch sends just `enabled`)."""
    with conn() as c:
        cur = c.execute(f"SELECT {_COLS} FROM outreach_rules WHERE id = %s", (rule_id,)).fetchone()
        if not cur:
            return None
        merged = {**_row(cur), **{k: v for k, v in data.items() if k in ("name", "enabled", "priority", "cooldown_hours", "trigger", "message")}}
        r = normalise(merged)
        row = c.execute(
            f"""UPDATE outreach_rules SET name=%s, enabled=%s, priority=%s, cooldown_hours=%s, trigger=%s::jsonb, message=%s::jsonb,
                       updated_at=now() WHERE id=%s RETURNING {_COLS}""",
            (r["name"], r["enabled"], r["priority"], r["cooldown_hours"], json.dumps(r["trigger"]), json.dumps(r["message"]), rule_id)).fetchone()
        c.commit()
    invalidate()
    return _row(row)


def delete_rule(rule_id: int) -> bool:
    with conn() as c:
        n = c.execute("DELETE FROM outreach_rules WHERE id = %s", (rule_id,)).rowcount
        c.execute("DELETE FROM outreach_events WHERE rule_id = %s", (rule_id,))  # its history goes with it
        c.commit()
    invalidate()
    return n > 0


def default_greeting_enabled() -> bool:
    try:
        return (get_setting(DEFAULT_GREETING_KEY) or "on") != "off"
    except Exception:
        return True


def set_default_greeting(on: bool) -> None:
    set_setting(DEFAULT_GREETING_KEY, "on" if on else "off")


# ---------------------------------------------------------------- the check
def _facts(visitor_id: str | None) -> dict[str, Any]:
    if not visitor_id or not settings.visitor_memory:
        return {}
    from app import memory

    return memory.profile(visitor_id)


def _cooled_down(c: Any, rule: dict[str, Any], visitor_id: str | None) -> bool:
    if not visitor_id or not rule.get("cooldown_hours"):
        return True
    row = c.execute(
        """SELECT 1 FROM outreach_events WHERE rule_id = %s AND visitor_id = %s
           AND fired_at > now() - make_interval(hours => %s) LIMIT 1""", (rule["id"], visitor_id, rule["cooldown_hours"])).fetchone()
    return row is None


def check(payload: dict[str, Any], visitor_id: str | None, record: bool = True, rules: list[dict[str, Any]] | None = None,
          facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate the enabled rules against one activity snapshot. Returns
    {rule: <message to show> | None, recheck: {dwell_s?, scroll_pct?}, default: <show the generic greeting?>}.
    `shown` in the payload lists rule ids the loader already displayed on this page, so a rule fires once per page."""
    rules = enabled_rules() if rules is None else rules
    ctx = context(payload, _facts(visitor_id) if facts is None else facts)
    shown = {int(x) for x in (payload.get("shown") or []) if str(x).lstrip("-").isdigit()}
    wait: dict[str, int] = {}
    out: dict[str, Any] = {"rule": None, "recheck": {}, "default": default_greeting_enabled()}
    if not rules:
        return out
    try:
        with conn() as c:
            for r in rules:
                if r["id"] in shown:
                    continue
                ev = evaluate(r["trigger"], ctx)
                if ev["match"]:
                    if not _cooled_down(c, r, visitor_id):
                        continue
                    msg = public_message(r, ctx)
                    if record:
                        row = c.execute(
                            "INSERT INTO outreach_events(rule_id, visitor_id, page) VALUES (%s, %s, %s) RETURNING id",
                            (r["id"], visitor_id, _text(payload.get("page"), 500) or None)).fetchone()
                        c.commit()
                        msg["event_id"] = row[0]
                    out["rule"] = msg
                    return out
                for k, v in (ev.get("wait") or {}).items():
                    wait[k] = min(wait[k], v) if k in wait else v
    except Exception as e:
        log.warning("outreach check failed: %s", e)
        return out
    out["recheck"] = wait
    return out


def mark(event_id: int, action: str, visitor_id: str | None, session_id: str | None) -> bool:
    """The bubble was opened (into the chat session `session_id`) or dismissed. The visitor id must match the
    firing's, so a stranger cannot stamp someone else's event."""
    col = {"opened": "opened_at", "dismissed": "dismissed_at"}.get(action)
    if not col:
        return False
    with conn() as c:
        n = c.execute(
            f"""UPDATE outreach_events SET {col} = COALESCE({col}, now()),
                       session_id = COALESCE(session_id, %s)
                WHERE id = %s AND (visitor_id IS NULL OR visitor_id = %s)""",
            ((session_id or "")[:64] or None if action == "opened" else None, event_id, (visitor_id or "")[:64] or None)).rowcount
        c.commit()
    return n > 0


def stats(days: int = 30) -> dict[str, Any]:
    """Per rule: fired, opened, dismissed, chatted (the opened session has messages), booked (a booking or a
    booking lead from that session)."""
    days = max(1, min(int(days), 365))
    with conn() as c:
        rows = c.execute(
            """SELECT e.rule_id, count(*), count(e.opened_at), count(e.dismissed_at),
                      count(*) FILTER (WHERE s.messages > 0),
                      count(*) FILTER (WHERE EXISTS (SELECT 1 FROM bookings b WHERE b.session_id = e.session_id AND b.status <> 'cancelled')
                                          OR EXISTS (SELECT 1 FROM leads l WHERE l.session_id = e.session_id AND l.status IN ('booked', 'handoff')))
               FROM outreach_events e LEFT JOIN sessions s ON s.session_id = e.session_id
               WHERE e.fired_at > now() - make_interval(days => %s) GROUP BY e.rule_id""", (days,)).fetchall()
        recent = c.execute(
            """SELECT e.id, e.fired_at, e.rule_id, r.name, e.page, e.opened_at IS NOT NULL, e.dismissed_at IS NOT NULL, e.session_id
               FROM outreach_events e LEFT JOIN outreach_rules r ON r.id = e.rule_id
               WHERE e.fired_at > now() - make_interval(days => %s) ORDER BY e.fired_at DESC LIMIT 50""", (days,)).fetchall()
    by_rule = {int(r[0]): {"fired": int(r[1]), "opened": int(r[2]), "dismissed": int(r[3]), "chatted": int(r[4]), "booked": int(r[5])} for r in rows}
    return {"days": days, "by_rule": by_rule,
            "recent": [{"id": r[0], "ts": r[1], "rule_id": r[2], "rule": r[3], "page": r[4], "opened": r[5], "dismissed": r[6], "session_id": r[7]} for r in recent]}


def summary(trigger: dict[str, Any]) -> str:
    """One line for humans: 'returning visitors · on /company/* · 2+ pages under /company/ · after 45 s'."""
    t = {**empty_trigger(), **(trigger or {})}
    parts = []
    parts.append({"new": "first-time visitors", "returning": "returning visitors"}.get(t["visitor"], "anyone"))
    if t["booking"] == "yes":
        parts.append("with an upcoming call")
    elif t["booking"] == "no":
        parts.append("without a booking")
    if t["page"]:
        parts.append(f"on {t['page']}")
    if t["pages_min"]:
        parts.append(f"{t['pages_min']}+ pages" + (f" under {t['pages_match']}" if t["pages_match"] else " this visit"))
    if t["dwell_s"]:
        parts.append(f"after {t['dwell_s']} s on the page")
    if t["scroll_pct"]:
        parts.append(f"scrolled {t['scroll_pct']}%")
    if t["referrer"]:
        parts.append(f"from {t['referrer']}")
    if t["channel"]:
        parts.append(f"channel {t['channel']}")
    if t["utm_source"]:
        parts.append(f"utm_source={t['utm_source']}")
    return " · ".join(parts)


# ---------------------------------------------------------------- starter rules
SEED: list[dict[str, Any]] = [
    {"name": "Upcoming call", "priority": 1, "cooldown_hours": 12,
     "trigger": {"booking": "yes"},
     "message": {"title": "Your call is in the diary 📅", "text": "{schedule} on {booking}. Need the Zoom link, or want to move it?",
                 "intro": "Your {schedule} is on {booking}. Ask me for the link or to reschedule.",
                 "replies": ["When is my call?", "Reschedule my call"]}},
    {"name": "LakeB2B walkthrough offer", "priority": 5, "cooldown_hours": 48,
     "trigger": {"page": "/company/lake-b2b", "dwell_s": 45, "booking": "no"},
     "message": {"title": "Deep into LakeB2B?", "text": "Want a 30-minute walkthrough of LakeB2B's data with Deep? I can book it right here.",
                 "intro": "Happy to book a LakeB2B walkthrough with Deep, or answer questions first.",
                 "replies": ["Book a LakeB2B walkthrough", "What does LakeB2B do?"]}},
    {"name": "Comparing the companies", "priority": 10, "cooldown_hours": 48,
     "trigger": {"pages_min": 3, "pages_match": "/company/", "booking": "no"},
     "message": {"title": "Looking across the group?", "text": "You've seen a few of the companies. I can explain how they fit together, or set up a call with Deep.",
                 "intro": "Ask me how the companies fit together, or book a call with Deep.",
                 "replies": ["How do the companies fit together?", "Book a call with Deep"]}},
    {"name": "Read the journey to the end", "priority": 20, "cooldown_hours": 24,
     "trigger": {"page": "/journey", "scroll_pct": 85, "dwell_s": 60},
     "message": {"title": "Still reading? 👀", "text": "Ask me about any day of the journey, or what Deep is working on right now.",
                 "intro": "Ask me about any day of the journey, or what Deep is working on now.",
                 "replies": ["What is Deep working on?", "What happened this week?"]}},
    {"name": "Welcome back", "priority": 30, "cooldown_hours": 72,
     "trigger": {"visitor": "returning", "booking": "no"},
     "message": {"title": "Welcome back, {first_name}", "text": "Good to see you again. Pick up where you left off, or book time with Deep.",
                 "intro": "Welcome back. Pick up where you left off, or book time with Deep.",
                 "replies": ["What did I ask last time?", "Book a call with Deep"]}},
]


def seed_if_empty() -> int:
    """Insert the starter rules once (settings key outreach:seeded). Deleting them later does not bring them back."""
    try:
        if get_setting(SEEDED_KEY):
            return 0
        n = 0
        with conn() as c:
            if c.execute("SELECT count(*) FROM outreach_rules").fetchone()[0] == 0:
                for s in SEED:
                    r = normalise(s)
                    c.execute("""INSERT INTO outreach_rules(name, enabled, priority, cooldown_hours, trigger, message)
                                 VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)""",
                              (r["name"], True, r["priority"], r["cooldown_hours"], json.dumps(r["trigger"]), json.dumps(r["message"])))
                    n += 1
                c.commit()
        set_setting(SEEDED_KEY, "1")
        invalidate()
        if n:
            log.info("outreach: %d starter rules created", n)
        return n
    except Exception as e:
        log.warning("outreach seed failed: %s", e)
        return 0
