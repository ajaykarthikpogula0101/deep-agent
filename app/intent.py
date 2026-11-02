"""Visitor detections: who is not a customer (wrong fit), and when a customer is ready to buy (buying moment).

Rules only, like app/mood.py: nothing is added to the reply time and every flag can be explained.

Wrong fit  (wrong_fit(message) -> "job" | "student" | "seller" | None)
  job       "are you hiring?", "looking for a job / internship", "send my CV", "join your team"
  student   "I'm a student", "my college project / thesis / assignment"
  seller    "we offer SEO / web development / backlinks / outsourcing", "guest post", "can I pitch our services"
  A message that also talks about buying data (lists, contacts, leads, pricing, a quote, ...) is never wrong fit: "we provide
  marketing services and need contact lists" is a customer.
  What the chat does (app/chat.py):
    job, seller  a short, kind reply written for that case (no search, no "couldn't find that", no Email Deep offer): this chat
                 is for customers, and where to go instead (the console's Detections routes, when set);
    student      answered as usual (their questions about the companies are welcome), the model is told not to offer a call;
    all          {"type": "wrong_fit", "kind", "label", "link"} for the widget (a route button when the console set a link and
                 no frustration or buying card), the event 'wrong_fit' (console tag and count), and the session is left out of
                 the hourly hot-lead alert (app/precall.py) and the buying-moment ping.

Buying moment  (buying(message, earlier) -> {"kinds", "details", "why"} or None)
  price     pricing, cost, a quote, "how much", "per contact"
  volume    a number of records: "50,000 contacts", "10k leads", "2 million emails"
  timeline  "by Friday", "next week", "ASAP", "deadline", "campaign launches on ..."
  budget    "budget of", "$5,000", "3 lakh rupees"
  decision  "we want to buy", "send us a quote / sample / proposal", "for our campaign"
  The new message must show one of these and the chat so far (its visitor messages) two different kinds. Once per chat:
    * the model is told (BUYING_NOTE): answer, then offer a call with Deep for exact options in one sentence;
    * the widget gets {"type": "buying", "kinds", "details"}: a "Want exact pricing for this?" card with Book a call and Email Deep;
    * Deep gets "Hot visitor on the site now" by email (BUYING_ALERTS, the console switch, at most BUYING_ALERTS_PER_HOUR an hour,
      never for a wrong-fit chat or one that already booked or wrote to Deep);
    * the event 'buying' (console tag and count).
Typed volumes and budgets are claims: they never change the lead score (app/precall.py scores checked evidence only).

Switches: WRONG_FIT_DETECTION, BUYING_DETECTION, BUYING_ALERTS in .env, and the same three plus frustration (app/mood.py) in the
console (Detections; settings rows detect:<name> = "off"), with the wrong-fit routes (settings rows fit:<kind>_link / _label).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from app.config import settings
from app.db import conn, get_setting, log_event, set_setting

log = logging.getLogger("intent")

BUYING_ALERTS_PER_HOUR = 6
CACHE_SECONDS = 10

# ---------------------------------------------------------------- wrong fit
_JOB = re.compile(
    r"\b(are you (guys |all )?hiring|(is|are) (your|the) (company|team) hiring|(any|open|current) (job )?(openings?|vacanc\w+|positions)|"
    r"job (openings?|vacanc\w+|opportunit\w+|offers?)|(looking|searching|applying) for (a |an )?(job|internship|full[- ]time role|work)|"
    r"apply (for|to) (a |an |the )?(job|internship|position|role|opening)|(send|share|submit|forward|attach\w*) (you )?(my |our )?(resume|cv|portfolio)|"
    r"(my|attached) (resume|cv)\b|internships?|career opportunit\w+|careers? (page|section)|work (at|for) (you|your (company|team)|deep|lakeb2b|span)|"
    r"join (your|the) team|i('m| am) a fresher|fresher|walk-?in interview|job (seeker|hunting))", re.I)
_STUDENT = re.compile(
    r"\b(i('m| am) (a |an )?(student|undergrad\w*|grad(uate)? student|phd student|mba student)|"
    r"(college|university|uni|school|class|course|semester|final[- ]year|academic) (project|assignment|research|work)|"
    r"my (thesis|dissertation|assignment|homework|coursework)|for my (project|research paper|thesis|dissertation|assignment|class))", re.I)
_SELLER = re.compile(
    r"\b((we|i) (offer|provide|specialize in|specialise in|deliver|sell) .{0,40}(seo|web ?(site )?(design|development)|app development|"
    r"software development|link ?building|backlinks?|guest post\w*|digital marketing|social media marketing|outsourc\w+|staff augmentation|"
    r"virtual assistants?|bookkeeping|video editing|white[- ]label)|guest post\w*|backlinks?|sponsored (post|article|content)|"
    r"(would|will) you be interested in (our|my)|(i|we)('d| would) like to (pitch|offer|propose|introduce) (to )?(you |your team )?(our|my)|"
    r"can (i|we) pitch|partnership proposal|our (agency|company|team) (can|could) help (you|your)|i('m| am) reaching out (to offer|from an agency))", re.I)
# talking about buying data makes it a customer, whatever else they say
_BUYER = re.compile(r"\b(buy|purchase|pricing|price|quote|cost|lists?|database|contacts|leads|records|data|mailing|prospects)\b", re.I)

FIT_KINDS = ("job", "student", "seller")
FIT_LABEL = {"job": "job seeker", "student": "student", "seller": "selling to us"}
FIT_DEFAULT_BUTTON = {"job": "See open roles", "student": "Read more", "seller": "Send your proposal"}


def wrong_fit(message: str) -> str | None:
    text = (message or "").strip()
    if not text or _BUYER.search(text):
        return None
    for kind, rx in (("job", _JOB), ("seller", _SELLER), ("student", _STUDENT)):
        if rx.search(text):
            return kind
    return None


# ---------------------------------------------------------------- buying moment
_PRICE = re.compile(r"\b(pric(e|es|ing|ed)|costs?|quote|quotation|how much|rate card|per (record|contact|lead|email|name)|payment terms|"
                    r"invoice|discount)\b", re.I)
_UNITS = (r"contacts?|records?|leads?|e-?mails?|e-?mail addresses|names|companies|accounts|physicians|doctors|nurses|dentists|hospitals|"
          r"clinics|decision[- ]makers|prospects|rows|profiles|phone numbers|mobile numbers|executives|ctos?|ceos?|cfos?|cmos?|it managers")
_VOLUME = re.compile(r"(?<![\w$€£₹])(\d[\d,.]*\s*(k|m|mm|thousand|million|lakhs?|crores?)?)\s*(\+\s*)?([a-z][a-z-]*\s+){0,2}?(" + _UNITS + r")\b", re.I)
_DAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|eod|end of (the )?(day|week|month|quarter)|next (week|month)"
# the date itself first ("by Friday"), so the email says when; a bare "need it by" only when no date is named
_TIMELINE_DATE = re.compile(r"\b((by|before|until) (" + _DAYS + r"|the \d+(st|nd|rd|th)?|\d{1,2}(st|nd|rd|th)? of \w+)|"
                            r"within \d+ (days?|weeks?)|in (\d+|two|three) (days|weeks)|end of (the )?(week|month|quarter)|"
                            r"this week|next week|this month|asap|urgent(ly)?|right away|immediately)\b", re.I)
_TIMELINE = re.compile(r"\b(deadline|need (it|them|this|the (data|list|lists|file)) (by|before|within|in)|"
                       r"(campaign|launch|event|conference|trade ?show) (starts|launches|goes live|is on|is in|next))\b", re.I)
_AMOUNT = re.compile(r"([$€£₹]\s?\d[\d,.]*\s*(k|m)?\b|\b\d[\d,.]*\s*(k\s)?(usd|dollars|eur|euros|gbp|pounds|inr|rupees|lakhs?)\b)", re.I)
_BUDGET = re.compile(r"\bbudget\b", re.I)   # the amount itself is preferred for the email (_kinds)
_DECISION = re.compile(r"\b((we|i)('re| are| am)? (ready|looking|planning) to (buy|purchase|order|get started|sign up|move forward|start)|"
                       r"(want|like|need) to (buy|purchase|order|place an order|get started|sign up|subscribe)|(place|placing) an order|"
                       r"sign (the )?(contract|agreement)|(send|share|email) (me |us )?(a |the |your )?(proposal|quote|quotation|contract|"
                       r"invoice|sample|samples|sample file)|free sample|sample (file|data|records|list)|"
                       r"for our (campaign|outreach|sales team|launch|event|abm|email campaign)|our (sales )?team (needs|wants|is looking))\b", re.I)
_KINDS = (("price", _PRICE), ("volume", _VOLUME), ("timeline", _TIMELINE), ("budget", _BUDGET), ("decision", _DECISION))
KIND_TEXT = {"price": "asked about price", "volume": "named a volume", "timeline": "has a deadline", "budget": "mentioned a budget",
             "decision": "is ready to buy"}


def _kinds(text: str) -> dict[str, str]:
    """{kind: the words that showed it}"""
    out = {}
    for kind, rx in _KINDS:
        first = _TIMELINE_DATE if kind == "timeline" else _AMOUNT if kind == "budget" else None
        m = (first and first.search(text or "")) or rx.search(text or "")
        if m and kind == "volume" and not m.group(2):   # "our 2 companies" is not an order: a volume is 100 or more
            n = re.sub(r"[^\d.]", "", m.group(1).replace(",", ""))
            try:
                if float(n or 0) < 100:
                    continue
            except ValueError:
                continue
        if m:
            out[kind] = re.sub(r"\s+", " ", m.group(0)).strip(" ,.")
    return out


def buying(message: str, earlier: list[str]) -> dict[str, Any] | None:
    """`earlier`: the visitor's earlier messages in this chat, oldest first. None unless the new message shows a buying
    sign and the chat two different ones. details keeps the most recent words for each kind."""
    now = _kinds(message)
    if not now:
        return None
    details: dict[str, str] = {}
    for t in list(earlier)[-12:]:
        details.update(_kinds(t))
    details.update(now)
    if len(details) < 2:
        return None
    kinds = [k for k, _ in _KINDS if k in details]
    why = "; ".join(f"{KIND_TEXT[k]} ({details[k]})" if k in ("volume", "timeline", "budget") else KIND_TEXT[k] for k in kinds)
    return {"kinds": kinds, "details": details, "why": why}


# ---------------------------------------------------------------- switches (console: Detections)
SWITCHES = {
    "frustration": ("Frustration", "Notice an annoyed visitor: a kinder answer and, once per chat, offer Email Deep or a call.", None),
    "wrong_fit": ("Wrong-fit visitors", "Job seekers, students and people selling to us are pointed elsewhere, not to Deep's calendar.",
                  "wrong_fit_detection"),
    "buying": ("Buying moment", "A visitor talking price, volume, deadline or budget is offered a call while they are still here.",
               "buying_detection"),
    "buying_alerts": ("Email Deep at a buying moment", "\"Hot visitor on the site now\" to the host, at most "
                      f"{BUYING_ALERTS_PER_HOUR} an hour.", "buying_alerts"),
}
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: str, fn):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _env_on(name: str) -> bool:
    attr = SWITCHES[name][2]
    return bool(getattr(settings, attr)) if attr else True


def enabled(name: str) -> bool:
    """On when .env allows it and the console has not switched it off. Never raises: a database hiccup keeps the default."""
    if not _env_on(name):
        return False

    def read() -> bool:
        try:
            return (get_setting(f"detect:{name}") or "on") != "off"
        except Exception as e:
            log.warning("detection switch read failed: %s", e)
            return True
    return _cached("sw:" + name, read)


def route(kind: str) -> dict[str, str]:
    """Where a wrong-fit visitor is sent: {"link", "label"} from the console (empty link: no button, the reply says it in words)."""
    def read() -> dict[str, str]:
        try:
            return {"link": (get_setting(f"fit:{kind}_link") or "").strip(),
                    "label": (get_setting(f"fit:{kind}_label") or "").strip() or FIT_DEFAULT_BUTTON[kind]}
        except Exception as e:
            log.warning("route read failed: %s", e)
            return {"link": "", "label": FIT_DEFAULT_BUTTON[kind]}
    return _cached("route:" + kind, read)


def _counts(days: int) -> dict[str, int]:
    with conn() as c:
        rows = c.execute("""SELECT kind, count(DISTINCT session_id) FROM events WHERE kind IN ('frustration', 'wrong_fit', 'buying')
                            AND ts > now() - make_interval(days => %s) GROUP BY kind""", (days,)).fetchall()
        alerts = c.execute("""SELECT count(*) FROM events WHERE kind = 'buying' AND detail->>'alerted' = 'true'
                              AND ts > now() - make_interval(days => %s)""", (days,)).fetchone()[0]
    out = {k: int(n) for k, n in rows}
    return {"frustration": out.get("frustration", 0), "wrong_fit": out.get("wrong_fit", 0), "buying": out.get("buying", 0),
            "buying_alerts": int(alerts)}


def state(days: int = 30) -> dict[str, Any]:
    """For the console: every switch, the routes and how often each fired in the last `days` days."""
    try:
        counts = _counts(days)
    except Exception as e:
        log.warning("detection counts failed: %s", e)
        counts = {}
    return {"days": days,
            "switches": [{"key": k, "name": v[0], "about": v[1], "on": enabled(k), "env_on": _env_on(k),
                          "env": (v[2] or "").upper(), "count": counts.get(k, 0)} for k, v in SWITCHES.items()],
            "routes": [{"kind": k, "label_default": FIT_DEFAULT_BUTTON[k], **route(k)} for k in FIT_KINDS]}


def set_switch(name: str, on: bool) -> dict[str, Any]:
    if name not in SWITCHES:
        raise LookupError(name)
    set_setting(f"detect:{name}", None if on else "off")
    clear_cache()
    return state()


def set_route(kind: str, link: str, label: str) -> dict[str, Any]:
    if kind not in FIT_KINDS:
        raise LookupError(kind)
    link = (link or "").strip()
    if link and not re.match(r"^(https?://\S+|mailto:\S+@\S+|[^\s@]+@[^\s@]+\.[^\s@]{2,})$", link, re.I):
        raise ValueError("a link starts with https:// or is an email address")
    if link and "@" in link and not link.lower().startswith(("mailto:", "http")):
        link = "mailto:" + link
    set_setting(f"fit:{kind}_link", link or None)
    set_setting(f"fit:{kind}_label", (label or "").strip()[:40] or None)
    clear_cache()
    return state()


# ---------------------------------------------------------------- the chat's calls
def _flagged(session_id: str, kind: str) -> bool:
    with conn() as c:
        return c.execute("SELECT 1 FROM events WHERE session_id = %s AND kind = %s LIMIT 1", (session_id, kind)).fetchone() is not None


def is_wrong_fit(session_id: str | None) -> bool:
    """This chat was flagged wrong fit (used by the buying ping and the hot-lead alert). Never raises."""
    if not session_id:
        return False
    try:
        return _flagged(session_id, "wrong_fit")
    except Exception:
        return False


def check_fit(session_id: str | None, message: str) -> dict[str, Any] | None:
    """{"kind", "label", "link", "button"} when the message reads as wrong fit; the event is logged once per kind per chat."""
    if not enabled("wrong_fit"):
        return None
    kind = wrong_fit(message)
    if not kind:
        return None
    r = route(kind)
    try:
        if session_id:
            with conn() as c:
                seen = c.execute("SELECT 1 FROM events WHERE session_id = %s AND kind = 'wrong_fit' AND detail->>'kind' = %s LIMIT 1",
                                 (session_id, kind)).fetchone()
            if not seen:
                log_event("wrong_fit", session_id, {"kind": kind, "message": (message or "")[:300]})
    except Exception as e:
        log.warning("wrong-fit log failed: %s", e)
    return {"kind": kind, "label": FIT_LABEL[kind], "link": r["link"], "button": r["label"]}


def _earlier_visitor_texts(session_id: str) -> list[str]:
    with conn() as c:
        rows = c.execute("""SELECT text FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id DESC LIMIT 13""",
                         (session_id,)).fetchall()
    texts = [r[0] or "" for r in reversed(rows)]
    return texts[:-1] if texts else texts   # the newest is this message, stored before the reply starts


def _already_with_deep(session_id: str) -> bool:
    """Booked, or already wrote to Deep from this chat: the card and the ping add nothing."""
    with conn() as c:
        return c.execute("""SELECT 1 FROM leads WHERE session_id = %s AND status IN ('booked', 'handover') LIMIT 1""",
                         (session_id,)).fetchone() is not None


def check_buying(session_id: str | None, message: str) -> dict[str, Any] | None:
    """{"kinds", "details", "why", "offer"} at a buying moment, else None. "offer" is True the first time in the chat (the card
    and the ping); later buying turns still get the model note. Never raises."""
    if not session_id or not enabled("buying"):
        return None
    try:
        m = buying(message, _earlier_visitor_texts(session_id))
        if not m or _flagged(session_id, "wrong_fit") or _already_with_deep(session_id):
            return None
        m["offer"] = not _flagged(session_id, "buying")
        if m["offer"]:
            log_event("buying", session_id, {"kinds": m["kinds"], "details": m["details"], "why": m["why"],
                                             "message": (message or "")[:300], "alerted": False})
        return m
    except Exception as e:
        log.warning("buying check failed: %s", e)
        return None


# ---------------------------------------------------------------- the ping to Deep
def _alerts_last_hour() -> int:
    with conn() as c:
        return int(c.execute("""SELECT count(*) FROM events WHERE kind = 'buying' AND detail->>'alerted' = 'true'
                                AND ts > now() - interval '1 hour'""").fetchone()[0])


def _visit(session_id: str) -> dict[str, Any]:
    with conn() as c:
        row = c.execute("""SELECT page, city, country, channel, referrer_host, net_org, user_name, user_email, verified_email
                           FROM sessions WHERE session_id = %s""", (session_id,)).fetchone()
        qs = [r[0] for r in c.execute("""SELECT text FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id DESC LIMIT 8""",
                                      (session_id,)).fetchall()]
    keys = ["page", "city", "country", "channel", "referrer_host", "net_org", "user_name", "user_email", "verified_email"]
    out = dict(zip(keys, row)) if row else {}
    out["questions"] = list(reversed(qs))
    return out


def render_alert(m: dict[str, Any], v: dict[str, Any]) -> tuple[str, str]:
    d = m["details"]
    head = " · ".join(x for x in (d.get("volume"), ("needs it " + d["timeline"]) if d.get("timeline") else "",
                                   ("budget " + d["budget"]) if d.get("budget") and d["budget"].lower() != "budget" else "") if x)
    who = v.get("user_name") or v.get("verified_email") or v.get("user_email") or "An anonymous visitor"
    subject = f"Hot visitor on the site now: {head or m['why']}"
    where = ", ".join(x for x in (v.get("city"), v.get("country")) if x)
    lines = ["Someone chatting with the assistant right now is showing real buying signs. The assistant has offered them a call;",
             "nothing is booked yet.", "", "BUYING SIGNS"]
    lines += [f"  - {KIND_TEXT[k]}" + (f": \"{d[k]}\"" if k in d else "") for k in m["kinds"]]
    lines += ["", "WHO", f"  {who}"]
    if v.get("net_org"):
        lines.append(f"  Network: {v['net_org']} (a guess from their connection)")
    if where:
        lines.append(f"  Location: {where}")
    if v.get("page"):
        lines.append(f"  Page: {v['page']}")
    if v.get("channel") or v.get("referrer_host"):
        lines.append("  Came from: " + " / ".join(x for x in (v.get("channel"), v.get("referrer_host")) if x))
    if v.get("questions"):
        lines += ["", "WHAT THEY ASKED"] + [f"  - {q[:200]}" for q in v["questions"]]
    lines += ["", "Volumes, budgets and dates are what the visitor typed: they do not change the lead score.",
              "The chat is in the console under Conversations; their details arrive by email if they book or write to you."]
    return subject, "\n".join(lines)


def alert_async(session_id: str, m: dict[str, Any]) -> None:
    """The "Hot visitor on the site now" email, on a worker thread so the reply is not held up. Never raises."""
    if not (m.get("offer") and session_id and settings.host_email and enabled("buying_alerts")):
        return
    threading.Thread(target=_alert, args=(session_id, m), daemon=True, name="buying-alert").start()


def _alert(session_id: str, m: dict[str, Any], mailer=None) -> bool:
    try:
        if _alerts_last_hour() >= BUYING_ALERTS_PER_HOUR:
            log.info("buying alert skipped: %d already this hour", BUYING_ALERTS_PER_HOUR)
            return False
        from app import mailer as mm
        from app import templates

        subject, body = render_alert(m, _visit(session_id))
        brand = templates.get_templates().get("brand_default") or "Champions Group"
        subject = f"[{brand}] {subject}"
        body = templates._tidy(body)
        (mailer or mm.default).enqueue(settings.host_email, subject, body,
                                       html=templates.html_wrap(subject, body, None, audience="host"), kind="buying_alert")
        with conn() as c:
            c.execute("""UPDATE events SET detail = jsonb_set(detail, '{alerted}', 'true') WHERE id = (
                           SELECT id FROM events WHERE session_id = %s AND kind = 'buying' ORDER BY id DESC LIMIT 1)""", (session_id,))
            c.commit()
        return True
    except Exception as e:
        log.warning("buying alert failed: %s", e)
        return False


# ---------------------------------------------------------------- prompt notes and replies
BUYING_NOTE = ("\nThe visitor is showing buying intent ({why}). Answer their question as usual from the sources; then, in one short "
               "sentence, offer a call with Deep to work out exact options and pricing for what they need (the interface shows the "
               "booking buttons). Do not invent prices, volumes or delivery times.")
STUDENT_NOTE = ("\nThe visitor seems to be a student (a project or assignment), not a customer: answer their questions from the "
                "sources as usual, but do not offer a call with Deep or the booking tools.")

_FIT_REPLY = {
    "job": ("Thanks for your interest in working with the team! This chat is for questions about Deep's companies and their "
            "services, so I can't help with jobs or applications here.", "You can see open roles here: {link}",
            "The best route is the careers page of the company you're interested in."),
    "seller": ("Thanks for reaching out. This chat is for customers asking about Deep's companies and their services, so I "
               "can't take service offers or partnership pitches here.", "You can send your proposal here: {link}",
               "The team isn't looking for new suppliers through this chat."),
}
FIT_WRITE = ("You are Deep's website assistant. The visitor's message reads as {what}. Reply in 2 short sentences, warmly and "
             "plainly: this chat is for customers with questions about Deep's companies and their services, so it can't help "
             "with that here. {route} Do not offer a call or a meeting with Deep, do not ask follow-up questions, no exclamation "
             "marks beyond one, no lists.{lang}")
_FIT_WHAT = {"job": "a job or internship enquiry", "seller": "someone offering their own services to the company"}


def fit_reply_fixed(kind: str, link: str = "") -> str:
    first, with_link, without = _FIT_REPLY[kind]
    return first + " " + (with_link.format(link=link.removeprefix("mailto:")) if link else without)


def fit_messages(kind: str, message: str, link: str, lang_note: str = "") -> list[dict[str, str]]:
    route_line = (f"Point them to: {link.removeprefix('mailto:')} (write it out exactly)." if link
                  else "Do not give an email address or link; say the careers page of the company is the best route." if kind == "job"
                  else "Do not give an email address or link.")
    return [{"role": "system", "content": FIT_WRITE.format(what=_FIT_WHAT[kind], route=route_line, lang=lang_note)},
            {"role": "user", "content": message[:600]}]
