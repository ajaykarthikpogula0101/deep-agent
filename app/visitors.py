"""Visits by devices that may never open the chat, so a later visit can be recognised and given context. Keyed by the
device id (localStorage dh_vid). The IP is never stored and never links rows: it only looks up the CURRENT network
through the tracking ip_net /24 cache. Visitor-facing context always comes from the current network. The remembered
company_key is host-side only.

observe()        the /outreach/check path: one connection, at most 5 primary-key or indexed statements, no external call.
                 A cache miss queues one background lookup (_warm); this check has no network context, the next one does.
org_identity()   the organisation a network belongs to, only when it is one (kind, flags, name and domain checks).
company_context  whether a pop-up may name that organisation: an 'auto' kind seen on COMPANY_MIN_VISITS visits from this
                 device, or approved by the owner in the console.
country_context  the country phrase, never for VPN, relay or cloud exits or when the browser timezone disagrees.
list_orgs() / update_org()   the console's "Organisations visiting" list and the owner's edits.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping
from urllib.parse import urlsplit

from app import network, tracking
from app.config import settings
from app.db import conn

log = logging.getLogger("visitors")

BOT_RE = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|python-requests|curl|wget", re.I)
GENERIC_ORG_RE = re.compile(r"^(private|reserved|unknown|n/?a|none|static|dynamic)\b|customer|subscriber|\bpool\b|residential", re.I)
ORG_OK_RE = re.compile(r"^[^\W\d_][\w&.,'()+ -]{1,59}$")
ORG_BAD_RE = re.compile(r"\d{3,}|www\.|https?:|@|\.(com|net|io)\b", re.I)
INTERNAL_ORG_KEYS = ("champions group", "lakeb2b", "lake b2b", "ampliz", "span global")
PRIVACY_TZ_PREFIX = "Europe/"
COMPANY_MIN_VISITS = 2
THE_COUNTRIES = {"United States", "United Kingdom", "Netherlands", "United Arab Emirates", "Philippines", "Czech Republic",
                 "Bahamas", "Maldives"}
COUNTRY_KINDS = ("corporate", "consumer", "education", "government", "unknown")
ORG_KINDS = ("corporate", "education", "government", "unknown")
STATUSES = ("auto", "candidate", "approved", "off")
MAX_PAGES = 30
ORG_CACHE_S = 60
_COUNTRY_RE = re.compile(r"^[^\W\d_][\w .,'()-]{1,59}$")
_INDUSTRY_RE = re.compile(r"^[a-z &/-]{2,40}$")
_URL_RE = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|ai|co|in)\b", re.I)

_vexec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="visitor-geo")  # never the session geo executor
_inflight: set[str] = set()
_inflight_lock = threading.Lock()
MAX_INFLIGHT = 50
_orgs: dict[str, tuple[float, dict[str, Any] | None]] = {}
_orgs_lock = threading.Lock()

INDUSTRY_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("healthcare", re.compile(r"health|hospital|clinic|pharma|medical|biotech|life science", re.I)),
    ("software", re.compile(r"software|saas|platform|\bapps?\b|cloud", re.I)),
    ("IT services", re.compile(r"it services|consult|outsourc|digital transformation|systems integrat", re.I)),
    ("financial services", re.compile(r"bank|fintech|insurance|financ|payments|lending", re.I)),
    ("manufacturing", re.compile(r"manufactur|industrial|automotive|engineering", re.I)),
    ("marketing", re.compile(r"marketing|advertis|agency|media", re.I)),
    ("retail", re.compile(r"retail|e-?commerce|consumer goods", re.I)),
    ("logistics", re.compile(r"logistic|shipping|freight|supply chain", re.I)),
    ("telecom", re.compile(r"telecom", re.I)),
    ("real estate", re.compile(r"real estate|property", re.I)),
]


# ---------------------------------------------------------------- pure helpers (unit-tested)
def _csv_upper(s: str | None) -> set[str]:
    return {x.strip().upper() for x in (s or "").split(",") if x.strip()}


def _no_personalise() -> set[str]:
    return _csv_upper(settings.outreach_no_personalise_countries)


def _company_kinds() -> set[str]:
    return {x.strip().lower() for x in (settings.outreach_company_kinds or "").split(",") if x.strip()}


def _local_db() -> bool:
    return "@localhost" in settings.database_url or "@127.0.0.1" in settings.database_url


def ip_context_on() -> bool:
    """The env hard switches and the console's soft switch (cached 15 s)."""
    from app import outreach

    return bool(settings.tracking_enabled and settings.outreach_ip_context and outreach.ip_context_enabled())


def privacy_region(tz: str | None) -> bool:
    """A browser timezone under Europe/ while the no-personalise list is set: no row, no lookup, nothing."""
    return bool(_no_personalise()) and (tz or "").startswith(PRIVACY_TZ_PREFIX)


def _blocked_domains() -> set[str]:
    return {network.registrable(d) for d in f"{settings.score_internal_domains},{settings.score_competitor_domains}".split(",")
            if d.strip()}


def org_identity(geo: Mapping[str, Any], net: Mapping[str, Any]) -> tuple[str, str, str | None] | None:
    """(key, org, domain) of the organisation behind this network, or None. The key is a registrable domain the
    organisation itself owns, else 'org:' + its org_key; a carrier's domain (the ASN of a netblock sub-allocation) is
    never used, so two companies on one carrier keep two keys."""
    from app.rag import prompts

    if net.get("net_kind") not in ORG_KINDS:
        return None
    flags = net.get("net_flags") or {}
    if flags.get("proxy") or flags.get("hosting"):
        return None
    org = network.clean_org(net.get("net_org") or "")
    if (not ORG_OK_RE.match(org) or ORG_BAD_RE.search(org) or GENERIC_ORG_RE.search(org)
            or prompts.looks_like_injection(org)):
        return None
    key = network.org_key(org)
    if not key or key.startswith(INTERNAL_ORG_KEYS):
        return None
    blocked = _blocked_domains()
    dom = geo.get("org_domain") or net.get("net_domain") or ""
    if dom and network.registrable(dom) in blocked:
        return None
    if any(network.same_company(key, network.org_key(network.domain_root(d))) for d in blocked):
        return None
    # the domain must belong to the organisation ('lovelace-labs.example' for Lovelace Labs), never its carrier's
    own = dom if dom and network.same_company(key, network.org_key(network.domain_root(dom))) else None
    reg = network.registrable(own) if own else None
    return (reg or "org:" + key), org, reg


def country_context(geo: Mapping[str, Any], net: Mapping[str, Any], client_tz: str | None) -> tuple[str, str]:
    """(country code, phrase for {country}) or ('', ''): never on VPN, relay or cloud networks, in the no-personalise
    list, or when the browser timezone disagrees with the IP's (travel, VPN)."""
    if not settings.outreach_country or net.get("net_kind") not in COUNTRY_KINDS:
        return "", ""
    flags = net.get("net_flags") or {}
    if flags.get("proxy") or flags.get("hosting"):
        return "", ""
    code, name = (geo.get("country_code") or "").upper(), str(geo.get("country") or "").strip()
    if not code or not _COUNTRY_RE.match(name) or code in _no_personalise():
        return "", ""
    if network.tz_mismatch(client_tz, geo.get("geo_tz")):
        return "", ""
    return code, ("the " + name if name in THE_COUNTRIES else name)


def company_context(ident: tuple[str, str, str | None] | None, org_row: Mapping[str, Any] | None, company_visits: int,
                    country_code: str | None) -> dict[str, Any] | None:
    """What a pop-up may say about the organisation, or None: an 'auto' row of a kind in OUTREACH_COMPANY_KINDS seen on
    COMPANY_MIN_VISITS visits of this device, or a row the owner approved."""
    if not ip_context_on() or not ident or not org_row:
        return None
    if (country_code or "").upper() in _no_personalise():
        return None
    status = org_row.get("status")
    if status in ("off", "candidate"):
        return None
    if status == "auto" and org_row.get("net_kind") not in _company_kinds():
        return None
    if int(company_visits or 0) < COMPANY_MIN_VISITS and status != "approved":
        return None
    return {"key": ident[0], "org": org_row.get("org") or ident[1], "kind": org_row.get("net_kind") or "corporate",
            "industry": org_row.get("industry") or "", "line": org_row.get("line") or None, "approved": status == "approved"}


def industry_hint(site: Mapping[str, Any] | None) -> str:
    """The first INDUSTRY_HINTS label matching the homepage title and description, else ''."""
    text = f"{(site or {}).get('title') or ''} {(site or {}).get('description') or ''}"
    return next((label for label, rx in INDUSTRY_HINTS if rx.search(text)), "")


def template(kind: str | None, industry: str | None) -> str:
    """The {company_line}: truthful, and it says nothing about the visitor."""
    if kind == "education":
        return "Ask how LakeB2B's data and Deep's team work with institutions like {company}."
    if kind == "government":
        return "Ask how LakeB2B works with public-sector teams like {company}."
    if industry:
        return "LakeB2B helps {industry} teams reach the right decision makers with B2B data. Want ideas for {company}?"
    return "Want to see how LakeB2B's B2B data could help {company} reach the right buyers?"


def validate_line(text: str | None) -> str:
    """An owner-written pop-up line. Raises ValueError with a message the console shows."""
    from app import outreach
    from app.rag import prompts

    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not 20 <= len(t) <= 170:
        raise ValueError("the line needs 20 to 170 characters")
    if "{company}" not in t:
        raise ValueError("the line must contain {company}")
    if _URL_RE.search(t):
        raise ValueError("no links in the line")
    if prompts.looks_like_injection(t):
        raise ValueError("the line reads like instructions to the assistant")
    if outreach.RULE_BANNED.search(t):
        raise ValueError("the line must not say how we know (no 'we noticed', 'your IP', 'welcome back', ...)")
    return t


def _page_path(page: str | None, site_host: str | None) -> str | None:
    """The site path of a page view, or None for the assistant's own pages (/demo, /site) unless the database is local."""
    from app import outreach

    page = (page or "").strip()
    if not page:
        return None
    if "://" in page and not _local_db():
        try:
            host = (urlsplit(page).netloc or "").lower()
        except ValueError:
            return None
        if site_host and host == site_host.strip().lower():
            return None
    return outreach.path_of(page)[:300]


# ---------------------------------------------------------------- the request path
# t: SET LOCAL statement_timeout for the statements after this one (folded in to save a round trip), and no wait for
# the WAL flush at commit: a page-view counter lost in a crash is harmless, an fsync on every page view is not.
# old: the row locked FOR UPDATE before the insert (it is joined into the insert's source, so it runs first). Under READ
# COMMITTED the lock waits for a concurrent check of the same device (two tabs) and then reads the row that check
# committed, not the statement's snapshot, so only the check that really advanced visits sees a new visit. No row and
# not inserted = another check inserted it first: not a new visit either.
_UPSERT = """
WITH t AS (SELECT set_config('statement_timeout', '250ms', true) AS st, set_config('synchronous_commit', 'off', true) AS sc),
     old AS (SELECT visits FROM visitors WHERE visitor_id = %(vid)s FOR UPDATE),
     e AS (SELECT CASE WHEN EXISTS (SELECT 1 FROM bookings b JOIN sessions s ON s.session_id = b.session_id WHERE s.visitor_id = %(vid)s) THEN 'booked'
                       WHEN EXISTS (SELECT 1 FROM sessions WHERE visitor_id = %(vid)s AND messages > 0) THEN 'chatted' END AS eng)
INSERT INTO visitors AS v (visitor_id, first_page, referrer_host, channel, utm_source, pages, engaged)
SELECT %(vid)s, %(path)s, %(rh)s, %(ch)s, %(utm)s,
       CASE WHEN %(path)s::text IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(%(path)s::text) END, e.eng
FROM e CROSS JOIN t LEFT JOIN old ON true
ON CONFLICT (visitor_id) DO UPDATE SET
  visits = v.visits + (v.last_seen < now() - make_interval(mins => %(gap)s))::int,
  pages = CASE WHEN %(path)s::text IS NULL OR v.pages ? %(path)s::text OR jsonb_array_length(v.pages) >= 30 THEN v.pages
               ELSE v.pages || jsonb_build_array(%(path)s::text) END,
  engaged = COALESCE(EXCLUDED.engaged, v.engaged), last_seen = now()
RETURNING visits, engaged, (xmax = 0) AS inserted, (xmax = 0) OR COALESCE(visits <> (SELECT visits FROM old), false) AS new_visit,
          company_key, company_visits, net_kind, country_code"""
_ROW = ("visits", "engaged", "inserted", "new_visit", "company_key", "company_visits", "net_kind", "country_code")


def observe(visitor_id: str | None, ip: str | None, user_agent: str | None, payload: Mapping[str, Any],
            site_host: str | None) -> dict[str, Any]:
    """Record this page view for the device and return what the pop-up may use: {visits, returning, engaged,
    net_kind, country_code, country, company}. {} when off, without a device id, for bots, GPC/DNT and (while the
    no-personalise list is set) a Europe/ browser timezone. Never raises; never calls out."""
    if not (settings.tracking_enabled and settings.outreach_visitors and visitor_id):
        return {}
    if BOT_RE.search(user_agent or "") or (settings.outreach_honor_gpc and payload.get("gpc")) or privacy_region(payload.get("tz")):
        return {}
    try:
        return _observe(visitor_id, ip or "", payload, site_host)
    except Exception as e:
        log.warning("visitor observe failed: %s", e)
        return {}


def _observe(vid: str, ip: str, payload: Mapping[str, Any], site_host: str | None) -> dict[str, Any]:
    referrer = payload.get("referrer") if isinstance(payload.get("referrer"), str) else ""
    first = payload.get("first_page") if isinstance(payload.get("first_page"), str) else ""
    utm = tracking.parse_utm(first)
    params = {"vid": vid, "path": _page_path(payload.get("page") or payload.get("path"), site_host),
              "rh": tracking.referrer_host(referrer)[:200] or None, "ch": tracking.classify_channel(referrer, utm),
              "utm": (utm.get("utm_source") or "")[:120] or None, "gap": max(0, int(settings.outreach_visit_gap_min))}
    tz = payload.get("tz") if isinstance(payload.get("tz"), str) else None
    later = None
    net: dict[str, Any] = {}
    code, phrase, company = "", "", None
    with conn() as c:
        row = dict(zip(_ROW, c.execute(_UPSERT, params).fetchone()), vid=vid)
        if ip_context_on() and tracking._valid_ip(ip):
            geo = tracking.cached_geo(ip, c)
            if geo is None:
                _enqueue(vid, ip)
            else:
                res = _apply_network(c, row, geo, bool(row["new_visit"]))
                net, later = res["net"], res["fill"]
                code, phrase = country_context(geo, net, tz)
                company = company_context(res["ident"], res["org_row"], res["company_visits"], geo.get("country_code"))
        c.commit()
    if later:
        _vexec.submit(_fill_industry, *later)
    try:
        legacy = int(payload.get("visits") or 0)
    except (TypeError, ValueError):
        legacy = 0
    return {"visits": int(row["visits"]), "returning": int(row["visits"]) > 1 or (bool(row["inserted"]) and legacy > 1),
            "engaged": row["engaged"] or "never", "net_kind": net.get("net_kind") or "",
            "country_code": code, "country": phrase, "company": company}


def _apply_network(c: Any, row: Mapping[str, Any], geo: Mapping[str, Any], new_visit: bool) -> dict[str, Any]:
    """Shared by the inline path and the background path: the visitor's network columns and the organisation row.
    Returns {net, ident, org_row, company_visits, fill}; fill = (key, domain) for the industry job, run after commit."""
    net = tracking.net_columns(geo)
    out: dict[str, Any] = {"net": net, "ident": None, "org_row": None, "company_visits": int(row.get("company_visits") or 0), "fill": None}
    if not net.get("net_kind"):  # a failed or disabled lookup says nothing: keep what we had
        return out
    cc = (geo.get("country_code") or "").upper() or None
    ident = None if (cc or "") in _no_personalise() else org_identity(geo, net)
    key = ident[0] if ident else None
    if key and key == row.get("company_key"):
        cv = int(row.get("company_visits") or 0) + int(new_visit)
    else:
        cv = 1 if key else 0
    if (net["net_kind"], cc, key, cv) != (row.get("net_kind"), row.get("country_code"), row.get("company_key"), int(row.get("company_visits") or 0)):
        c.execute("""UPDATE visitors SET net_kind = %s, country_code = %s, company_key = %s, company_visits = %s, net_at = now()
                     WHERE visitor_id = %s""", (net["net_kind"], cc, key, cv, row["vid"]))
    org_row = None
    if key and (new_visit or key != row.get("company_key")):
        r = c.execute(
            """INSERT INTO org_networks(key, org, domain, net_kind, status)
               VALUES (%(k)s, %(o)s, %(d)s, %(kind)s, CASE WHEN %(kind)s = ANY(%(kinds)s) THEN 'auto' ELSE 'candidate' END)
               ON CONFLICT (key) DO UPDATE SET last_seen = now(), domain = COALESCE(org_networks.domain, EXCLUDED.domain),
                   net_kind = CASE WHEN org_networks.net_kind = 'unknown' THEN EXCLUDED.net_kind ELSE org_networks.net_kind END,
                   status = CASE WHEN org_networks.status = 'candidate' AND EXCLUDED.status = 'auto' THEN 'auto' ELSE org_networks.status END
               RETURNING org, net_kind, status, industry, line, domain, (xmax = 0)""",
            {"k": key, "o": ident[1], "d": ident[2], "kind": net["net_kind"], "kinds": sorted(_company_kinds())}).fetchone()
        org_row = {"key": key, "org": r[0], "net_kind": r[1], "status": r[2], "industry": r[3] or "", "line": r[4], "domain": r[5]}
        _cache_org(key, org_row)
        if r[6] and r[5] and not r[3]:
            out["fill"] = (key, r[5])
    elif key:
        org_row = get_org(key, c)
    out.update(ident=ident, org_row=org_row, company_visits=cv)
    return out


def _enqueue(vid: str, ip: str) -> bool:
    """One background lookup per /24 at a time (at most MAX_INFLIGHT); the IP lives only in the job's closure."""
    net = tracking.mask_ip(ip)
    with _inflight_lock:
        if net in _inflight or len(_inflight) >= MAX_INFLIGHT:
            return False
        _inflight.add(net)
    try:
        _vexec.submit(_warm, vid, ip)
    except Exception:
        with _inflight_lock:
            _inflight.discard(net)
        raise
    return True


def _warm(vid: str, ip: str) -> None:
    """Background: look the network up (purpose='visitor', capped) and apply it to the device's row."""
    try:
        geo = tracking.geolocate(ip, purpose="visitor")
        if geo.get("status") not in ("ok", "private"):
            return
        fill = None
        with conn() as c:
            r = c.execute("SELECT company_key, company_visits, net_kind, country_code FROM visitors WHERE visitor_id = %s",
                          (vid,)).fetchone()
            if r:
                row = {"vid": vid, "company_key": r[0], "company_visits": r[1], "net_kind": r[2], "country_code": r[3]}
                fill = _apply_network(c, row, geo, False)["fill"]
            c.commit()
        if fill:
            _fill_industry(*fill)
    except Exception as e:
        log.warning("visitor network lookup failed: %s", e)
    finally:
        with _inflight_lock:
            _inflight.discard(tracking.mask_ip(ip))


def _fill_industry(key: str, domain: str) -> None:
    """Background: the industry from the organisation's homepage (keywords, no model). An owner's value is kept."""
    from app import enrich

    try:
        site = enrich.lookup_domain(domain)
        with conn() as c:
            c.execute("""UPDATE org_networks SET industry = %s, industry_source = 'homepage', updated_at = now()
                         WHERE key = %s AND industry_source IS DISTINCT FROM 'owner'""", (industry_hint(site), key))
            c.commit()
    except Exception as e:
        log.warning("industry for %s failed: %s", key, e)
    invalidate(key)


# ---------------------------------------------------------------- organisation rows (60 s in-process cache)
_ORG_COLS = "key, org, net_kind, status, industry, line, domain"


def _org_dict(r: tuple) -> dict[str, Any]:
    return {"key": r[0], "org": r[1], "net_kind": r[2], "status": r[3], "industry": r[4] or "", "line": r[5], "domain": r[6]}


def _cache_org(key: str, row: dict[str, Any] | None) -> None:
    with _orgs_lock:
        if len(_orgs) > 2000:
            _orgs.clear()
        _orgs[key] = (time.monotonic(), row)


def get_org(key: str, c: Any = None) -> dict[str, Any] | None:
    with _orgs_lock:
        hit = _orgs.get(key)
    if hit and time.monotonic() - hit[0] < ORG_CACHE_S:
        return hit[1]
    sql = f"SELECT {_ORG_COLS} FROM org_networks WHERE key = %s"
    if c is None:
        with conn() as c2:
            r = c2.execute(sql, (key,)).fetchone()
    else:
        r = c.execute(sql, (key,)).fetchone()
    row = _org_dict(r) if r else None
    _cache_org(key, row)
    return row


def invalidate(key: str | None = None) -> None:
    with _orgs_lock:
        if key is None:
            _orgs.clear()
        else:
            _orgs.pop(key, None)


# ---------------------------------------------------------------- retention and erase
def purge(only: Mapping[str, list] | None = None) -> dict[str, int]:
    """After TRACK_RETENTION_DAYS: idle visitors rows and unreviewed org_networks rows go, and old outreach_events lose
    their visitor id and context. `only` ({visitors, orgs, events}: id lists) limits each step to those rows (tests on a
    shared database)."""
    p = {"days": settings.track_retention_days, "v": list((only or {}).get("visitors") or []),
         "o": list((only or {}).get("orgs") or []), "e": list((only or {}).get("events") or [])}
    scoped = only is not None
    with conn() as c:
        a = c.execute("DELETE FROM visitors WHERE last_seen < now() - make_interval(days => %(days)s)"
                      + (" AND visitor_id = ANY(%(v)s)" if scoped else ""), p).rowcount
        b = c.execute("DELETE FROM org_networks WHERE last_seen < now() - make_interval(days => %(days)s) AND reviewed_at IS NULL"
                      + (" AND key = ANY(%(o)s)" if scoped else ""), p).rowcount
        e = c.execute("""UPDATE outreach_events SET visitor_id = NULL, context = '{}'::jsonb
                         WHERE fired_at < now() - make_interval(days => %(days)s) AND (visitor_id IS NOT NULL OR context <> '{}'::jsonb)"""
                      + (" AND id = ANY(%(e)s)" if scoped else ""), p).rowcount
        c.commit()
    invalidate()
    return {"visitors_dropped": int(a), "orgs_dropped": int(b), "events_scrubbed": int(e)}


def erase(visitor_id: str | None) -> dict[str, int]:
    """Forget a device: its visitors row, and the visitor id and context on its pop-up firings."""
    vid = tracking.clean_vid(visitor_id)
    if not vid:
        return {"visitors": 0, "events": 0}
    with conn() as c:
        a = c.execute("DELETE FROM visitors WHERE visitor_id = %s", (vid,)).rowcount
        b = c.execute("UPDATE outreach_events SET visitor_id = NULL, context = '{}'::jsonb WHERE visitor_id = %s", (vid,)).rowcount
        c.commit()
    return {"visitors": int(a), "events": int(b)}


# ---------------------------------------------------------------- console
def summary(days: int = 30) -> dict[str, Any]:
    days = max(1, min(int(days), 365))
    with conn() as c:
        r = c.execute(
            """SELECT count(*), count(*) FILTER (WHERE visits > 1 AND engaged IS NULL), count(*) FILTER (WHERE company_key IS NOT NULL),
                      (SELECT jsonb_object_agg(k, n) FROM (SELECT COALESCE(net_kind, 'unknown') AS k, count(*) AS n FROM visitors
                         WHERE last_seen > now() - make_interval(days => %(d)s) GROUP BY 1) x)
               FROM visitors WHERE last_seen > now() - make_interval(days => %(d)s)""", {"d": days}).fetchone()
    by_kind = r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}")
    return {"days": days, "devices": int(r[0]), "returning_never_engaged": int(r[1]), "on_org_networks": int(r[2]), "by_kind": by_kind}


_ORGS_SQL = """
WITH v AS (SELECT company_key AS key, count(DISTINCT visitor_id) AS devices, sum(visits) AS visits,
                  count(*) FILTER (WHERE engaged IS NOT NULL) AS engaged
           FROM visitors WHERE company_key IS NOT NULL AND last_seen > now() - make_interval(days => %(d)s) GROUP BY 1),
     p AS (SELECT key, (array_agg(page ORDER BY n DESC, page))[1:5] AS pages FROM (
               SELECT v.company_key AS key, x.page, count(*) AS n FROM visitors v, jsonb_array_elements_text(v.pages) AS x(page)
               WHERE v.company_key IS NOT NULL AND v.last_seen > now() - make_interval(days => %(d)s) GROUP BY 1, 2) t GROUP BY key),
     e AS (SELECT e.org_key AS key, count(*) AS shown, count(e.opened_at) AS opened, count(e.dismissed_at) AS dismissed,
                  count(*) FILTER (WHERE s.messages > 0) AS chatted,
                  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM bookings b WHERE b.session_id = e.session_id AND b.status <> 'cancelled')
                                      OR EXISTS (SELECT 1 FROM leads l WHERE l.session_id = e.session_id AND l.status IN ('booked', 'handoff'))) AS booked
           FROM outreach_events e LEFT JOIN sessions s ON s.session_id = e.session_id
           WHERE e.org_key IS NOT NULL AND e.fired_at > now() - make_interval(days => %(d)s) GROUP BY 1)
SELECT o.key, o.org, o.domain, o.net_kind, o.status, o.industry, o.industry_source, o.line, o.first_seen, o.last_seen, o.reviewed_at,
       COALESCE(v.devices, 0), COALESCE(v.visits, 0), COALESCE(v.engaged, 0), COALESCE(p.pages, '{}'),
       COALESCE(e.shown, 0), COALESCE(e.opened, 0), COALESCE(e.dismissed, 0), COALESCE(e.chatted, 0), COALESCE(e.booked, 0)
FROM org_networks o LEFT JOIN v ON v.key = o.key LEFT JOIN p ON p.key = o.key LEFT JOIN e ON e.key = o.key
WHERE (%(st)s::text = '' OR o.status = %(st)s::text) AND (o.last_seen > now() - make_interval(days => %(d)s) OR o.reviewed_at IS NOT NULL)
ORDER BY 12 DESC, o.last_seen DESC LIMIT 200"""


def list_orgs(status: str | None = None, days: int = 30) -> dict[str, Any]:
    """The console's "Organisations visiting": devices, visits, engaged devices and top pages from visitors whose last
    organisation network was this one, and the pop-up counts by org_key. `preview` is the line a pop-up would show,
    with {company} left for the console to fill."""
    days = max(1, min(int(days), 365))
    st = status if status in STATUSES else ""
    with conn() as c:
        rows = c.execute(_ORGS_SQL, {"d": days, "st": st}).fetchall()
        counts = dict(c.execute("SELECT status, count(*) FROM org_networks GROUP BY 1").fetchall())
    items = []
    for r in rows:
        industry = r[5] or ""
        items.append({"key": r[0], "org": r[1], "domain": r[2], "net_kind": r[3], "status": r[4], "industry": industry,
                      "industry_source": r[6], "line": r[7], "first_seen": r[8], "last_seen": r[9], "reviewed_at": r[10],
                      "devices": int(r[11]), "visits": int(r[12]), "engaged": int(r[13]), "pages": list(r[14] or []),
                      "preview": (r[7] or template(r[3], industry)).replace("{industry}", industry),
                      "stats": {"shown": int(r[15]), "opened": int(r[16]), "dismissed": int(r[17]), "chatted": int(r[18]), "booked": int(r[19])}})
    return {"days": days, "status": st, "items": items, "counts": {k: int(v) for k, v in counts.items()}}


def candidates() -> int:
    with conn() as c:
        return int(c.execute("SELECT count(*) FROM org_networks WHERE status = 'candidate'").fetchone()[0])


def update_org(key: str, data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Owner edits: org (name), industry, line (null clears it), status approved | off | auto. Raises ValueError."""
    sets, vals = [], []
    if data.get("org") is not None:
        org = re.sub(r"\s+", " ", str(data["org"])).strip()
        if len(org) > 60 or not ORG_OK_RE.match(org):
            raise ValueError("the organisation name needs 2 to 60 letters, digits or simple punctuation")
        sets.append("org = %s")
        vals.append(org)
    if data.get("industry") is not None:
        ind = str(data["industry"]).strip().lower()
        if ind and not _INDUSTRY_RE.match(ind):
            raise ValueError("the industry is 2 to 40 lowercase letters (spaces, & / - allowed)")
        sets += ["industry = %s", "industry_source = 'owner'"]
        vals.append(ind)
    if "line" in data:
        line = data.get("line")
        sets.append("line = %s")
        vals.append(validate_line(line) if line not in (None, "") else None)
    if data.get("status") is not None:
        if data["status"] not in ("approved", "off", "auto"):
            raise ValueError("status is approved, off or auto")
        sets.append("status = %s")
        vals.append(data["status"])
    if not sets:
        raise ValueError("nothing to change")
    with conn() as c:
        r = c.execute(f"UPDATE org_networks SET {', '.join(sets)}, reviewed_at = now(), updated_at = now() WHERE key = %s RETURNING {_ORG_COLS}",
                      (*vals, key)).fetchone()
        c.commit()
    invalidate(key)
    return _org_dict(r) if r else None


def provider_note() -> str:
    """Why few organisations are named automatically with this provider chain ('' when a provider gives company data)."""
    if any(p in ("ipapiis", "ipapi") for p in tracking.providers()):
        return ""
    return ("company detection is weak with this provider chain: organisations show up as candidates to approve below, "
            "or add ipapiis once its terms are checked")
