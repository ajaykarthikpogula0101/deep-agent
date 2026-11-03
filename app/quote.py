"""Quote request: the visitor describes what data they need in a short form inside the chat, and Deep gets one tidy request
he can price, instead of a vague "how much?".

options()                 -> the form's choices (data types, volumes, timelines, budgets).
prefill(session_id)       -> what the chat already says, so the visitor only checks it: the data types it talked about,
                             the volume, deadline and budget the visitor typed (app/intent.py reads them), the job titles
                             behind a volume ("20,000 IT managers" -> "IT managers") and the countries named. Rules only.
submit(session_id, form)  -> stored as a lead (status 'quote', with the request as its reason), the event 'quote' with every
                             field, Deep's email "[Quote request] ..." (reply-to the visitor, with the questions they asked),
                             and a line in the chat ("Quote request sent to Deep: ..."). The bot never quotes a price itself.
Limits: only the browser's own chats (POST /quote checks app/conversations.owns), MAX_PER_SESSION_DAY per chat and
MAX_PER_EMAIL_DAY per address. Switch: QUOTE_ENABLED.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.db import conn, log_event

log = logging.getLogger("quote")

MAX_PER_SESSION_DAY = 3
MAX_PER_EMAIL_DAY = 5
DATA_TYPES = ["Contact data / email lists", "Intent data", "Technographics", "Healthcare data", "Demand generation / campaigns",
              "Data enrichment / cleansing", "Something else"]
VOLUMES = ["Under 5,000", "5,000 – 25,000", "25,000 – 100,000", "100,000+", "Not sure yet"]
TIMELINES = ["ASAP", "Within 2 weeks", "This month", "Next quarter", "Just exploring"]
BUDGETS = ["Under $2,000", "$2,000 – $10,000", "$10,000 – $50,000", "$50,000+", "Prefer not to say"]

_TYPE_WORDS = [("Intent data", r"\bintent\b"), ("Technographics", r"\btechnograph\w*|\btech stack|\btech install"),
               ("Healthcare data", r"\b(physicians?|doctors?|nurses?|hospitals?|clinics?|healthcare|dentists?|pharma\w*)\b"),
               ("Demand generation / campaigns", r"\b(demand gen\w*|campaigns?|abm|lead gen\w*|appointment setting)\b"),
               ("Data enrichment / cleansing", r"\b(enrich\w*|cleans\w*|append\w*|verif\w* my|clean (my|our) (data|crm|list))\b"),
               ("Contact data / email lists", r"\b(email lists?|mailing lists?|contacts?|contact data|emails? of|leads? list|b2b data)\b")]
_COUNTRIES = ["United States", "USA", "US", "UK", "United Kingdom", "Canada", "India", "Australia", "Germany", "France", "Spain", "Italy",
              "Netherlands", "Singapore", "UAE", "Dubai", "Saudi Arabia", "Japan", "Brazil", "Mexico", "South Africa", "Ireland",
              "New Zealand", "Europe", "EMEA", "APAC", "North America", "LATAM", "Texas", "California", "New York", "Florida",
              "Illinois", "Ohio", "Iceland"]
_TITLE_FROM_VOLUME = re.compile(r"\d[\d,.]*\s*(?:k|m|mm|thousand|million|lakhs?)?\s*(?:\+\s*)?((?:[A-Za-z][A-Za-z-]*\s+){0,3}?[A-Za-z-]+)$", re.I)
_GENERIC_UNITS = {"contacts", "contact", "records", "record", "leads", "lead", "emails", "email", "names", "rows", "profiles", "prospects",
                  "companies", "accounts", "email addresses", "phone numbers", "mobile numbers"}


def options() -> dict[str, Any]:
    return {"enabled": settings.quote_enabled, "data_types": DATA_TYPES, "volumes": VOLUMES, "timelines": TIMELINES, "budgets": BUDGETS}


def _volume_bucket(text: str) -> str:
    m = re.search(r"(\d[\d,.]*)\s*(k|m|mm|thousand|million|lakhs?)?", text or "", re.I)
    if not m:
        return ""
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return ""
    mult = (m.group(2) or "").lower()
    n *= 1_000 if mult in ("k", "thousand") else 1_000_000 if mult in ("m", "mm", "million") else 100_000 if mult.startswith("lakh") else 1
    return VOLUMES[0] if n < 5_000 else VOLUMES[1] if n <= 25_000 else VOLUMES[2] if n <= 100_000 else VOLUMES[3]


def _timeline_bucket(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"asap|urgent|right away|immediately|today|tomorrow|tonight|this week|by (monday|tuesday|wednesday|thursday|friday|saturday|sunday)|eod", t):
        return TIMELINES[0]
    if re.search(r"next week|within (1|2|one|two) weeks?|in (\d+|two|three) days", t):
        return TIMELINES[1]
    if re.search(r"this month|end of (the )?month|within \d+ weeks?", t):
        return TIMELINES[2]
    if re.search(r"next (month|quarter)|end of (the )?quarter", t):
        return TIMELINES[3]
    return ""


def _budget_bucket(text: str) -> str:
    m = re.search(r"(\d[\d,.]*)\s*(k)?", (text or "").replace("$", ""), re.I)
    if not m or not re.search(r"[$€£]|usd|dollar", text or "", re.I):
        return ""
    n = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    return BUDGETS[0] if n < 2_000 else BUDGETS[1] if n <= 10_000 else BUDGETS[2] if n <= 50_000 else BUDGETS[3]


def from_texts(texts: list[str]) -> dict[str, Any]:
    """The form, filled from what the visitor typed (oldest first). Pure."""
    from app import intent

    joined = "\n".join(texts)
    details: dict[str, str] = {}
    for t in texts:
        details.update(intent._kinds(t))
    types = [name for name, rx in _TYPE_WORDS if re.search(rx, joined, re.I)]
    titles = ""
    if details.get("volume"):
        m = _TITLE_FROM_VOLUME.search(details["volume"])
        unit = (m.group(1).strip() if m else "")
        if unit and unit.lower() not in _GENERIC_UNITS:
            titles = re.sub(r"^(verified|targeted|b2b)\s+", "", unit, flags=re.I)
    regions = [c for c in _COUNTRIES if re.search(r"(?<![A-Za-z])" + re.escape(c) + r"(?![A-Za-z])", joined, 0 if c.isupper() else re.I)]
    regions = [c for c in regions if not (c == "US" and ("USA" in regions or "United States" in regions))]
    return {"data_types": types[:3], "titles": titles, "regions": ", ".join(dict.fromkeys(regions))[:200],
            "volume": _volume_bucket(details.get("volume", "")), "timeline": _timeline_bucket(details.get("timeline", "")),
            "budget": _budget_bucket(details.get("budget", "")),
            "notes": ("From the chat: " + "; ".join(f"{k} {v}" if k != "price" else "asked about price"
                                                    for k, v in details.items() if k in ("volume", "timeline", "budget", "price"))
                      if details else "")}


def prefill(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return from_texts([])
    try:
        with conn() as c:
            rows = c.execute("SELECT text FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id DESC LIMIT 15",
                             (session_id,)).fetchall()
        return from_texts([r[0] or "" for r in reversed(rows)])
    except Exception as e:
        log.warning("quote prefill failed: %s", e)
        return from_texts([])


# ---------------------------------------------------------------- the request
class Limited(Exception):
    """Too many quote requests for this chat or this address."""


def clean(form: dict[str, Any]) -> dict[str, Any]:
    """The submitted form, trimmed and limited to the known choices. Raises ValueError with a visitor-facing message."""
    def s(k: str, n: int) -> str:
        return re.sub(r"\s+", " ", str(form.get(k) or "")).strip()[:n]

    out = {"name": s("name", 120), "email": s("email", 200).lower(), "company": s("company", 120), "titles": s("titles", 200),
           "industry": s("industry", 120), "regions": s("regions", 200), "notes": str(form.get("notes") or "").strip()[:1500],
           "data_types": [t for t in (form.get("data_types") or []) if t in DATA_TYPES][:7],
           "volume": s("volume", 40) if s("volume", 40) in VOLUMES else "", "timeline": s("timeline", 40) if s("timeline", 40) in TIMELINES else "",
           "budget": s("budget", 40) if s("budget", 40) in BUDGETS else ""}
    if len(out["name"]) < 2:
        raise ValueError("Please enter your name.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", out["email"]):
        raise ValueError("Please enter a valid email address.")
    if not out["data_types"] and not out["titles"] and len(out["notes"]) < 5:
        raise ValueError("Tell us what data you need: pick a type, add job titles or write a note.")
    return out


def headline(q: dict[str, Any]) -> str:
    """"20,000+ IT managers · United States · As soon as possible"-style summary for subjects and the chat line."""
    what = q["titles"] or (", ".join(q["data_types"][:2]) if q["data_types"] else "data")
    parts = [f"{q['volume']} {what}".strip() if q["volume"] and q["volume"] != "Not sure yet" else what,
             q["regions"], q["timeline"] if q["timeline"] and q["timeline"] != "Just exploring" else ""]
    return " · ".join(p for p in parts if p)[:160]


def render_host(q: dict[str, Any], questions: list[str]) -> tuple[str, str]:
    who = q["name"] + (f" ({q['company']})" if q["company"] else "")
    subject = f"[Quote request] {who}: {headline(q)}"
    lines = [f"{q['name']} asked for a quote from the website chat. Reply to this email to answer them directly.", "", "WHAT THEY NEED"]
    rows = [("Data", ", ".join(q["data_types"]) or "-"), ("Job titles", q["titles"] or "-"), ("Industry", q["industry"] or "-"),
            ("Regions", q["regions"] or "-"), ("Volume", q["volume"] or "-"), ("Needed by", q["timeline"] or "-"), ("Budget", q["budget"] or "-")]
    lines += [f"• {k}: {v}" for k, v in rows]
    if q["notes"]:
        lines += ["", "THEIR NOTE", q["notes"]]
    lines += ["", "WHO", f"• {q['name']} <{q['email']}>" + (f", {q['company']}" if q["company"] else "")]
    if questions:
        lines += ["", "WHAT THEY ASKED IN THE CHAT"] + [f"• {t[:200]}" for t in questions[-8:]]
    lines += ["", "The assistant never quotes prices; this request is waiting for your reply."]
    return subject, "\n".join(lines)


def chat_line(q: dict[str, Any]) -> str:
    host = settings.host_name_short or "Deep"
    return f"Quote request sent to {host}: {headline(q)}. {host} will reply to {q['email']} with options and pricing."


def _counts(session_id: str, email: str) -> tuple[int, int]:
    with conn() as c:
        a = c.execute("""SELECT count(*) FROM events WHERE kind = 'quote' AND session_id = %s AND ts > now() - interval '1 day'""",
                      (session_id,)).fetchone()[0]
        b = c.execute("""SELECT count(*) FROM events WHERE kind = 'quote' AND lower(detail->>'email') = %s
                         AND ts > now() - interval '1 day'""", (email,)).fetchone()[0]
    return int(a), int(b)


def submit(session_id: str, form: dict[str, Any], mailer=None) -> dict[str, Any]:
    from app import inbox
    from app import mailer as mm
    from app import templates

    q = clean(form)
    per_chat, per_mail = _counts(session_id, q["email"])
    if per_chat >= MAX_PER_SESSION_DAY or per_mail >= MAX_PER_EMAIL_DAY:
        raise Limited()
    with conn() as c:
        qs = [r[0] for r in c.execute("SELECT text FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id DESC LIMIT 8",
                                      (session_id,)).fetchall()][::-1]
        lead_id = c.execute("""INSERT INTO leads(name, email, reason, status, session_id, company) VALUES (%s, %s, %s, 'quote', %s, %s)
                               RETURNING id""", (q["name"], q["email"], "Quote request: " + headline(q), session_id, q["company"] or None)).fetchone()[0]
        c.commit()
    subject, body = render_host(q, qs)
    sent = False
    if settings.host_email:
        try:
            body = templates._tidy(body)
            (mailer or mm.default).enqueue(settings.host_email, subject, body, html=templates.html_wrap(subject, body, None, audience="host"),
                                           reply_to=q["email"], kind="quote", ref=lead_id)
            sent = True
        except Exception as e:
            log.error("quote email failed: %s", e)
    log_event("quote", session_id, {**q, "lead_id": int(lead_id), "emailed": sent})
    line = chat_line(q)
    inbox.log_message(session_id, "assistant", line, outcome="quote", question="Quote request")
    return {"ok": True, "lead_id": int(lead_id), "chat_line": line, "headline": headline(q), "to": q["email"]}


