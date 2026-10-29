"""Vector retrieval with a confidence floor. Below the floor the caller must refuse, not guess."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.config import settings
from app.db import conn
from app.embeddings import embed_query

log = logging.getLogger("retrieve")


@dataclass
class Hit:
    url: str
    title: str
    section: str | None
    text: str
    score: float  # cosine similarity in [0,1]
    metadata: dict


_DAY_RE = re.compile(r"\bday\s*#?\s*(\d{1,4})\b", re.I)


def _day_hits(c, query: str) -> list[Hit]:
    """Embeddings are poor at numbers: 'day 338' must return that entry, so fetch it by metadata directly."""
    m = _DAY_RE.search(query)
    if not m:
        return []
    rows = c.execute(
        """SELECT ch.url, p.title, ch.section, ch.text, ch.metadata
           FROM chunks ch JOIN pages p ON p.url = ch.url
           WHERE ch.metadata->>'day' = %s ORDER BY ch.position LIMIT 3""",
        (m.group(1),),
    ).fetchall()
    return [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=1.0, metadata=r[4] or {}) for r in rows]


# Questions a vector search answers badly on this site (measured 2026-10-16: "who is Deep?" ranked the privacy page
# first at 0.565, "latest log entry" the home page, "what tools does he use" the toolkit fourth). Each rule names the
# page that answers it; those chunks come first with score 1.0, like a day number does.
_ABOUT_DEEP = re.compile(
    r"\b(who('?s| is)( this)? (deep|sreedeep|he|the (founder|owner|author))|(about|tell me about|introduce) (deep|sreedeep|him)"
    r"|where('?s| is| does)? (deep|sreedeep|he)\b.*\b(based|live|located|from|work)|(based|located) (in|where)"
    r"|(deep|sreedeep|he)('?s| is) (based|located|from)|what does (deep|sreedeep|he) do"
    r"|(his|deep'?s|sreedeep'?s) (role|roles|job|title|titles|background|bio|position|companies|location|city)"
    r"|sreedeep|surapaneni)\b", re.I)
_TOOLS = re.compile(r"\b(tools?|toolkit|tool stack|stack|software|tech stack|uses? to build|ai stack)\b", re.I)
_NOW = re.compile(r"\b(working on|focus(ed|ing)? on|right now|currently|these days|at the moment|up to|now page|hiring|launching)\b", re.I)
_LATEST = re.compile(r"\b(latest|newest|most recent|recent|last|today|yesterday|this week)\b.{0,30}\b(entry|entries|post|posts|"
                     r"log|update|updates|day|days|note|notes|shipped|ship|build|built)\b"
                     r"|\bwhat (did|has) (he|deep) (ship|shipped|build|built|do|done)\b.{0,20}\b(today|yesterday|lately|recently|this week)\b",
                     re.I)

# "which companies does Champions Group own?" got 4 of 12: each company is its own small page and only the top 6 chunks
# come back. The pillars page names all twelve, grouped.
_COMPANIES = re.compile(
    r"\b(which|what|list|all|name|how many|every|each|show)\b.{0,40}\b(compan(y|ies)|ventures?|businesses|brands|portfolio|subsidiar(y|ies)|pillars?)\b"
    r"|\b(portfolio|pillars?|subsidiaries)\b|\bcompanies (does|do|under|in|of|are)\b", re.I)

PINNED_PAGES = {  # rule -> (url, how many leading chunks)
    "about": [("https://deependhq.com/", 1), ("https://deependhq.com/now", 1)],
    "tools": [("https://deependhq.com/toolkit", 3)],
    "now": [("https://deependhq.com/now", 1)],
    "companies": [("https://deependhq.com/pillars", 5)],
}

# ---------------------------------------------------------------- date-scoped questions
# "what did he learn this month?" cited a July entry. A question that names a period gets the log entries dated in it.
_MONTHS = {m: i for i, names in enumerate([("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
                                            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
                                            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
                                            ("dec", "december")], start=1) for m in names}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_IN_MONTH = re.compile(rf"\b(in|during|for|of|from|over|through(out)?)\s+({_MONTH_NAMES})\b\.?(\s+(20\d\d))?"
                       rf"|\b({_MONTH_NAMES})\s+(20\d\d)\b", re.I)
_ON_DAY = re.compile(rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(st|nd|rd|th)?\b(,?\s+(20\d\d))?|\b(\d{{1,2}})(st|nd|rd|th)?\s+(of\s+)?({_MONTH_NAMES})\b(\s+(20\d\d))?"
                     r"|\b(20\d\d)-(\d\d)-(\d\d)\b", re.I)
_LAST_N = re.compile(r"\b(last|past|previous)\s+(\d{1,2})\s+days\b", re.I)


@dataclass
class DateRange:
    start: date
    end: date
    label: str


def _month_range(year: int, month: int, today: date) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return first, min(nxt - timedelta(days=1), today)


def date_range(query: str, today: date) -> DateRange | None:
    """The period a question names, in the visitor's calendar, or None (pure, unit-tested)."""
    q = (query or "").lower()
    if re.search(r"\btoday\b|\btonight\b", q):
        return DateRange(today, today, "today")
    if re.search(r"\byesterday\b|\blast night\b", q):
        d = today - timedelta(days=1)
        return DateRange(d, d, "yesterday")
    m = _LAST_N.search(q)
    if m:
        n = max(1, min(int(m.group(2)), 90))
        return DateRange(today - timedelta(days=n - 1), today, f"the last {n} days")
    if re.search(r"\b(last|previous) week\b", q):
        monday = today - timedelta(days=today.weekday() + 7)
        return DateRange(monday, monday + timedelta(days=6), "last week")
    if re.search(r"\b(this|his|the|current|past) week\b|\bweek so far\b|\bweekly\b", q):
        monday = today - timedelta(days=today.weekday())
        return DateRange(monday, today, "this week")
    if re.search(r"\b(last|previous|past) month\b", q):
        prev = today.replace(day=1) - timedelta(days=1)
        s, e = _month_range(prev.year, prev.month, today)
        return DateRange(s, e, "last month")
    if re.search(r"\b(this|his|the|current) month\b|\bmonth so far\b", q):
        s, e = _month_range(today.year, today.month, today)
        return DateRange(s, e, "this month")
    m = _ON_DAY.search(q)
    if m:
        try:
            if m.group(12):
                d = date(int(m.group(12)), int(m.group(13)), int(m.group(14)))
            elif m.group(1):
                d = date(int(m.group(5) or today.year), _MONTHS[m.group(1).lower()], int(m.group(2)))
            else:
                d = date(int(m.group(11) or today.year), _MONTHS[m.group(9).lower()], int(m.group(6)))
            if d > today and not (m.group(5) or m.group(11) or m.group(12)):
                d = d.replace(year=d.year - 1)
            return DateRange(d, d, f"{d:%B} {d.day}, {d.year}")
        except ValueError:
            pass
    m = _IN_MONTH.search(q)
    if m:
        name, year = (m.group(3), m.group(5)) if m.group(3) else (m.group(6), m.group(7))
        month = _MONTHS[name.lower()]
        y = int(year) if year else (today.year if month <= today.month else today.year - 1)
        s, e = _month_range(y, month, today)
        if s <= today:
            return DateRange(s, e, f"{s:%B %Y}")
    return None


def _range_hits(c, rng: DateRange) -> list[Hit]:
    """Log entries dated in the period (newest first, one chunk each) and the weekly essays published in it."""
    span = (rng.end - rng.start).days + 1
    n_days, n_essays = (7, 1) if span <= 10 else (5, 4)
    days = c.execute(
        """SELECT DISTINCT ON ((ch.metadata->>'day')::int) ch.url, p.title, ch.section, ch.text, ch.metadata
           FROM chunks ch JOIN pages p ON p.url = ch.url
           WHERE ch.metadata->>'date' BETWEEN %s AND %s AND ch.metadata->>'day' ~ '^[0-9]+$'
           ORDER BY (ch.metadata->>'day')::int DESC, ch.position LIMIT %s""",
        (rng.start.isoformat(), rng.end.isoformat(), n_days)).fetchall()
    # a weekly essay is dated at the end of its week: for a short period, the essay of the week it falls in
    essay_end = rng.end + timedelta(days=6) if span <= 10 else rng.end
    essays = c.execute(
        """SELECT ch.url, ch.metadata->>'title', ch.section, ch.text, ch.metadata, substring(ch.text from '^\\s*(\\d{4}-\\d{2}-\\d{2})') AS d
           FROM chunks ch
           WHERE ch.metadata->>'kind' = 'essay' AND ch.position = 0
             AND substring(ch.text from '^\\s*(\\d{4}-\\d{2}-\\d{2})') BETWEEN %s AND %s
           ORDER BY d DESC LIMIT %s""",
        (rng.start.isoformat(), essay_end.isoformat(), n_essays)).fetchall()
    out = [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=1.0, metadata={**(r[4] or {}), "in_period": True}) for r in days]
    out += [Hit(url=r[0], title=r[1] or "Weekly essay", section=r[2], text=r[3], score=1.0,
                metadata={**(r[4] or {}), "date": r[5], "in_period": True}) for r in essays]
    return out


def _latest_rows(c, n: int = 3):
    return c.execute(
        """SELECT DISTINCT ON ((ch.metadata->>'day')::int) ch.url, p.title, ch.section, ch.text, ch.metadata
           FROM chunks ch JOIN pages p ON p.url = ch.url
           WHERE ch.metadata ? 'day' AND ch.metadata->>'day' ~ '^[0-9]+$'
           ORDER BY (ch.metadata->>'day')::int DESC, ch.position LIMIT %s""", (n,)).fetchall()


def company_names() -> list[str]:
    """Every company with its own page on the site (the authoritative list and count); [] when the index is unreachable."""
    try:
        with conn() as c:
            rows = c.execute("SELECT title FROM pages WHERE url LIKE %s ORDER BY title", ("%/company/%",)).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        log.warning("company list failed: %s", e)
        return []


def pinned_rules(query: str, today: date | None = None) -> list[str]:
    """Which pinned pages a question needs (pure, unit-tested). A named period ('this week') replaces 'latest'."""
    q = query or ""
    out = []
    if today is not None and date_range(q, today):
        out.append("period")
    elif _LATEST.search(q):
        out.append("latest")
    if _COMPANIES.search(q):
        out.append("companies")
    if _ABOUT_DEEP.search(q):
        out.append("about")
    if _TOOLS.search(q):
        out.append("tools")
    if _NOW.search(q) and "about" not in out:
        out.append("now")
    return out


def _pinned_hits(c, query: str, today: date | None = None) -> list[Hit]:
    hits: list[Hit] = []
    for rule in pinned_rules(query, today):
        if rule == "period":
            found = _range_hits(c, date_range(query, today))
            hits += found
            # nothing in the period yet ("yesterday" before tonight's entry): the newest entries, so the model can say so
            rows = [] if found else _latest_rows(c)
        elif rule == "latest":
            rows = _latest_rows(c)
        else:
            rows = []
            for url, n in PINNED_PAGES[rule]:
                rows += c.execute(
                    """SELECT ch.url, p.title, ch.section, ch.text, ch.metadata FROM chunks ch JOIN pages p ON p.url = ch.url
                       WHERE ch.url = %s ORDER BY ch.position LIMIT %s""", (url, n)).fetchall()
        hits += [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=1.0, metadata=r[4] or {}) for r in rows]
    return hits


def search(query: str, k: int | None = None, vec: list[float] | None = None, today: date | None = None) -> list[Hit]:
    """`today` is the visitor's date: 'this week' or 'yesterday' then fetch the entries dated in that period."""
    k = k or settings.retrieval_top_k
    vec = vec if vec is not None else embed_query(query)
    with conn() as c:
        exact = _day_hits(c, query)
        try:
            exact += [h for h in _pinned_hits(c, query, today) if h.text not in {e.text for e in exact}]
        except Exception as e:  # a pinned page missing from the index must never break the search
            log.warning("pinned pages failed: %s", e)
        rows = c.execute(
            """
            SELECT ch.url, p.title, ch.section, ch.text, 1 - (ch.embedding <=> %s::vector) AS score, ch.metadata
            FROM chunks ch JOIN pages p ON p.url = ch.url
            ORDER BY ch.embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, vec, k),
        ).fetchall()
    hits = [Hit(url=r[0], title=r[1], section=r[2], text=r[3], score=float(r[4]), metadata=r[5] or {}) for r in rows]
    if settings.help_enabled:  # help articles written for the assistant or by the owner (app/help.py) compete on score
        try:
            from app import help as help_center

            arts = [Hit(url=a["url"], title=a["title"], section=None, text=a["text"], score=a["score"], metadata=a["metadata"])
                    for a in help_center.retrieval_hits(vec) if a["score"] >= settings.help_answer_min_score]
            if arts:
                hits = sorted(hits + arts, key=lambda h: h.score, reverse=True)[:k]
        except Exception as e:
            log.warning("help articles skipped: %s", e)
    seen = {h.url for h in exact}
    return exact + [h for h in hits if h.url not in seen]


def confident(hits: list[Hit], floor: float | None = None) -> bool:
    """Pure decision rule (unit-tested): the best hit must clear the floor."""
    floor = settings.retrieval_min_score if floor is None else floor
    return bool(hits) and hits[0].score >= floor
