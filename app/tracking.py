"""Session origin tracking: who opened a chat session, from where (IP -> city/country) and how they arrived.

Flow
  chat opens    -> POST /track {session_id, visitor_id, page, referrer, tz, lang, screen}
                   the server adds the client IP + user agent, upserts `sessions`, and geolocates the IP
                   on a background thread so the beacon returns immediately
  each /chat    -> touch(): last_seen + message count (creates the row if the beacon never fired)
  book_slot     -> the lead carries session_id and a one-line origin summary for the host brief
  daily         -> purge(): IPs and user agents older than TRACK_RETENTION_DAYS are nulled; geo stays

The visitor id is a random UUID the widget keeps in the site's own localStorage (first party, no cookie), so
returning visitors are recognised across sessions. Nothing here fingerprints the browser.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

import httpx

from app.config import settings
from app.db import conn

log = logging.getLogger("tracking")

GEO_CACHE_DAYS = 30
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="geo")

SEARCH_HOSTS = ("google.", "bing.com", "duckduckgo.com", "yahoo.", "baidu.com", "yandex.", "ecosia.org", "brave.com")
SOCIAL_HOSTS = ("linkedin.com", "lnkd.in", "twitter.com", "x.com", "t.co", "facebook.com", "fb.com", "instagram.com",
                "youtube.com", "youtu.be", "reddit.com", "threads.net", "whatsapp.com", "telegram.")
AI_HOSTS = ("chatgpt.com", "openai.com", "perplexity.ai", "claude.ai", "gemini.google.com", "copilot.microsoft.com",
            "bing.com/chat", "you.com", "phind.com")


# ---------------------------------------------------------------- request helpers (pure, unit-tested)
def client_ip(headers: Mapping[str, str], peer: str | None, trust_proxy: bool | None = None) -> str:
    """The visitor's IP as seen by the first proxy we trust. Behind Cloudflare / nginx the socket peer is the
    proxy, so the real address is in a header; those headers are only honoured when TRUST_PROXY is on."""
    trust = settings.trust_proxy if trust_proxy is None else trust_proxy
    candidates: list[str] = []
    if trust:
        for h in ("cf-connecting-ip", "x-real-ip"):
            if headers.get(h):
                candidates.append(headers[h])
        fwd = headers.get("x-forwarded-for")
        if fwd:
            candidates.append(fwd.split(",")[0])
    candidates.append(peer or "")
    for c in candidates:
        c = c.strip()
        if _valid_ip(c):
            return c
    return "unknown"


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified)


def mask_ip(ip: str) -> str:
    """Coarsen an address for storage: IPv4 keeps /24, IPv6 keeps /48. Geo lookups happen before masking."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if a.version == 4:
        return str(ipaddress.ip_network(f"{a}/24", strict=False).network_address)
    return str(ipaddress.ip_network(f"{a}/48", strict=False).network_address)


def parse_utm(page_url: str | None) -> dict[str, str]:
    if not page_url:
        return {}
    try:
        q = parse_qs(urlsplit(page_url).query)
    except ValueError:
        return {}
    out = {}
    for k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "gclid", "fbclid", "li_fat_id"):
        if k in q and q[k] and q[k][0]:
            out[k] = q[k][0][:120]
    return out


def referrer_host(referrer: str | None) -> str:
    if not referrer:
        return ""
    try:
        host = urlsplit(referrer).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def classify_channel(referrer: str | None, utm: Mapping[str, str], site_host: str | None = None) -> str:
    """direct | internal | search | social | ai | email | paid | referral"""
    site = (site_host or referrer_host(settings.site_base_url)).lower()
    medium = (utm.get("utm_medium") or "").lower()
    if medium in ("email", "newsletter"):
        return "email"
    if medium in ("cpc", "ppc", "paid", "paidsocial") or utm.get("gclid") or utm.get("fbclid") or utm.get("li_fat_id"):
        return "paid"
    host = referrer_host(referrer).lower()
    if not host:
        return "direct" if not utm.get("utm_source") else "campaign"
    if site and (host == site or host.endswith("." + site)):
        return "internal"
    if any(host == h or host.endswith("." + h) or host.endswith(h) for h in AI_HOSTS):
        return "ai"
    if any(host == h or host.endswith("." + h) or host.startswith(h) for h in SEARCH_HOSTS):
        return "search"
    if any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS):
        return "social"
    return "referral"


# ---------------------------------------------------------------- geolocation (cached per IP)
def normalise_geo(provider: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Map a provider payload onto our columns. Unknown or failed lookups come back with status='failed'."""
    g: dict[str, Any] = {"country": None, "country_code": None, "region": None, "city": None,
                         "lat": None, "lon": None, "isp": None, "geo_tz": None, "status": "failed"}
    try:
        if provider == "ipwho" and data.get("success", True) and data.get("country"):
            g.update(country=data.get("country"), country_code=data.get("country_code"), region=data.get("region"),
                     city=data.get("city"), lat=data.get("latitude"), lon=data.get("longitude"),
                     isp=((data.get("connection") or {}).get("isp") or (data.get("connection") or {}).get("org")),
                     geo_tz=(data.get("timezone") or {}).get("id"), status="ok")
        elif provider == "ipinfo" and data.get("country") and not data.get("bogon"):
            lat, _, lon = (data.get("loc") or ",").partition(",")
            g.update(country=data.get("country"), country_code=data.get("country"), region=data.get("region"),
                     city=data.get("city"), lat=float(lat) if lat else None, lon=float(lon) if lon else None,
                     isp=data.get("org"), geo_tz=data.get("timezone"), status="ok")
        elif provider == "ipapi" and data.get("status") == "success":
            g.update(country=data.get("country"), country_code=data.get("countryCode"), region=data.get("regionName"),
                     city=data.get("city"), lat=data.get("lat"), lon=data.get("lon"), isp=data.get("isp"),
                     geo_tz=data.get("timezone"), status="ok")
    except (TypeError, ValueError):
        pass
    for k in ("country", "country_code", "region", "city", "isp", "geo_tz"):
        if g[k] is not None:
            g[k] = str(g[k])[:120]
    return g


def _fetch_geo(ip: str) -> dict[str, Any]:
    provider = settings.geoip_provider
    if provider == "none":
        return normalise_geo(provider, {}) | {"status": "disabled"}
    if provider == "ipwho":
        url, params = f"https://ipwho.is/{ip}", {}
    elif provider == "ipinfo":
        url, params = f"https://ipinfo.io/{ip}/json", ({"token": settings.geoip_token} if settings.geoip_token else {})
    elif provider == "ipapi":
        url, params = f"http://ip-api.com/json/{ip}", {"fields": "status,country,countryCode,regionName,city,lat,lon,isp,timezone"}
    else:
        log.warning("unknown GEOIP_PROVIDER %r", provider)
        return normalise_geo("none", {}) | {"status": "disabled"}
    try:
        r = httpx.get(url, params=params, timeout=4.0, headers={"User-Agent": settings.crawl_user_agent})
        r.raise_for_status()
        return normalise_geo(provider, r.json())
    except (httpx.HTTPError, ValueError) as e:
        log.warning("geo lookup failed for %s: %s", ip, e)
        return normalise_geo(provider, {})


def geolocate(ip: str) -> dict[str, Any]:
    """Cached lookup. Private/loopback addresses are never sent anywhere."""
    if not is_public(ip):
        return normalise_geo("none", {}) | {"status": "private"}
    with conn() as c:
        row = c.execute("SELECT data FROM ip_geo WHERE ip = %s AND fetched_at > now() - make_interval(days => %s)",
                        (ip, GEO_CACHE_DAYS)).fetchone()
    if row:
        return row[0]
    geo = _fetch_geo(ip)
    if geo["status"] == "ok":  # only cache successes; a transient failure should be retried next time
        with conn() as c:
            c.execute("""INSERT INTO ip_geo(ip, data, fetched_at) VALUES (%s, %s::jsonb, now())
                         ON CONFLICT (ip) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()""",
                      (ip, json.dumps(geo)))
            c.commit()
    return geo


# ---------------------------------------------------------------- session rows
def start_session(session_id: str, visitor_id: str | None, ip: str, user_agent: str | None, page: str | None,
                  referrer: str | None, client_tz: str | None, lang: str | None, screen: str | None) -> dict[str, Any]:
    """Called by the /track beacon when the chat opens. Idempotent per session: the landing page, referrer and
    UTM parameters are kept from the first call; last_seen moves on every call."""
    if not settings.tracking_enabled:
        return {"ok": True, "tracked": False}
    utm = parse_utm(page)
    channel = classify_channel(referrer, utm)
    with conn() as c:
        c.execute(
            """INSERT INTO sessions(session_id, visitor_id, ip, user_agent, page, referrer, referrer_host, channel, utm,
                                    client_tz, lang, screen, geo_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'pending')
               ON CONFLICT (session_id) DO UPDATE SET
                   last_seen   = now(),
                   visitor_id  = COALESCE(sessions.visitor_id, EXCLUDED.visitor_id),
                   ip          = COALESCE(sessions.ip, EXCLUDED.ip),
                   user_agent  = COALESCE(sessions.user_agent, EXCLUDED.user_agent),
                   page        = COALESCE(sessions.page, EXCLUDED.page),
                   referrer    = COALESCE(sessions.referrer, EXCLUDED.referrer),
                   referrer_host = COALESCE(sessions.referrer_host, EXCLUDED.referrer_host),
                   channel     = COALESCE(sessions.channel, EXCLUDED.channel),
                   utm         = CASE WHEN sessions.utm = '{}'::jsonb THEN EXCLUDED.utm ELSE sessions.utm END,
                   client_tz   = COALESCE(sessions.client_tz, EXCLUDED.client_tz),
                   lang        = COALESCE(sessions.lang, EXCLUDED.lang),
                   screen      = COALESCE(sessions.screen, EXCLUDED.screen)""",
            (session_id, visitor_id, ip, (user_agent or "")[:300] or None, (page or "")[:500] or None,
             (referrer or "")[:500] or None, referrer_host(referrer) or None, channel, json.dumps(utm),
             (client_tz or "")[:64] or None, (lang or "")[:16] or None, (screen or "")[:16] or None),
        )
        visits = c.execute("SELECT count(*) FROM sessions WHERE visitor_id = %s", (visitor_id,)).fetchone()[0] if visitor_id else 1
        c.commit()
    _executor.submit(_enrich, session_id, ip)
    return {"ok": True, "tracked": True, "channel": channel, "visit_number": int(visits)}


def touch(session_id: str, ip: str, user_agent: str | None) -> None:
    """Every chat message: bump the counters, and create the row if the beacon never fired (API callers, old
    cached widget). Never raises; tracking must not take the chat down."""
    if not settings.tracking_enabled:
        return
    try:
        with conn() as c:
            row = c.execute(
                """INSERT INTO sessions(session_id, ip, user_agent, channel, messages, geo_status)
                   VALUES (%s, %s, %s, 'direct', 1, 'pending')
                   ON CONFLICT (session_id) DO UPDATE SET last_seen = now(), messages = sessions.messages + 1
                   RETURNING (xmax = 0) AS inserted""",
                (session_id, ip, (user_agent or "")[:300] or None),
            ).fetchone()
            c.commit()
        if row and row[0]:
            _executor.submit(_enrich, session_id, ip)
    except Exception as e:
        log.warning("touch failed for %s: %s", session_id, e)


def _enrich(session_id: str, ip: str) -> None:
    try:
        geo = geolocate(ip)
        stored_ip = mask_ip(ip) if settings.track_ip_mode == "masked" else ip
        with conn() as c:
            c.execute(
                """UPDATE sessions SET country=%s, country_code=%s, region=%s, city=%s, lat=%s, lon=%s, isp=%s,
                                       geo_tz=%s, geo_status=%s, ip=%s
                   WHERE session_id = %s""",
                (geo["country"], geo["country_code"], geo["region"], geo["city"], geo["lat"], geo["lon"], geo["isp"],
                 geo["geo_tz"], geo["status"], stored_ip, session_id),
            )
            c.commit()
    except Exception as e:
        log.warning("geo enrich failed for %s: %s", session_id, e)


def attach_visitor(session_id: str | None, visitor_id: str | None) -> None:
    """Make sure the session carries the browser's visitor id even if the /track beacon never fired."""
    if not session_id or not visitor_id:
        return
    try:
        with conn() as c:
            c.execute(
                """INSERT INTO sessions(session_id, visitor_id, channel, geo_status) VALUES (%s, %s, 'direct', 'pending')
                   ON CONFLICT (session_id) DO UPDATE SET visitor_id = COALESCE(sessions.visitor_id, EXCLUDED.visitor_id)""",
                (session_id, visitor_id[:64]),
            )
            c.commit()
    except Exception as e:
        log.warning("attach_visitor failed: %s", e)


def attach_user(session_id: str | None, user: Mapping[str, Any] | None) -> None:
    """Signed-in visitor (verified token): remember who the session belongs to. Never raises."""
    if not session_id or not user or not user.get("sub"):
        return
    try:
        with conn() as c:
            c.execute(
                """INSERT INTO sessions(session_id, user_id, user_name, user_email, channel, geo_status)
                   VALUES (%s, %s, %s, %s, 'direct', 'pending')
                   ON CONFLICT (session_id) DO UPDATE SET user_id = EXCLUDED.user_id,
                       user_name = COALESCE(EXCLUDED.user_name, sessions.user_name),
                       user_email = COALESCE(EXCLUDED.user_email, sessions.user_email)""",
                (session_id, str(user["sub"])[:200], (user.get("name") or "")[:120] or None, (user.get("email") or "")[:200] or None),
            )
            c.commit()
    except Exception as e:
        log.warning("attach_user failed: %s", e)


def attach_lead(session_id: str | None, lead_id: int) -> None:
    if not session_id:
        return
    try:
        with conn() as c:
            c.execute("UPDATE sessions SET leads = leads + 1, last_seen = now() WHERE session_id = %s", (session_id,))
            c.execute("UPDATE leads SET session_id = %s WHERE id = %s", (session_id, lead_id))
            c.commit()
    except Exception as e:
        log.warning("attach_lead failed: %s", e)


# ---------------------------------------------------------------- read side
def format_origin(row: Mapping[str, Any]) -> str:
    """One line for humans: 'Bengaluru, Karnataka, IN · Jio · via linkedin.com (social) · visit 2 · 4 messages'."""
    place = ", ".join(p for p in (row.get("city"), row.get("region"), row.get("country_code") or row.get("country")) if p)
    status = row.get("geo_status")
    if not place:
        place = {"private": "local/private network", "pending": "location pending", "disabled": "geo lookup off"}.get(
            status or "", "location unknown")
    parts = [place]
    if row.get("isp"):
        parts.append(str(row["isp"]))
    ref = row.get("referrer_host")
    channel = row.get("channel") or "direct"
    utm = row.get("utm") or {}
    if isinstance(utm, str):
        try:
            utm = json.loads(utm)
        except ValueError:
            utm = {}
    if utm.get("utm_source"):
        parts.append(f"campaign {utm['utm_source']}/{utm.get('utm_medium', '-')}/{utm.get('utm_campaign', '-')}")
    elif ref:
        parts.append(f"via {ref} ({channel})")
    else:
        parts.append(channel)
    if row.get("page"):
        parts.append(f"on {urlsplit(str(row['page'])).path or '/'}")
    if row.get("visit_number"):
        parts.append(f"visit {row['visit_number']}")
    if row.get("messages") is not None:
        parts.append(f"{row['messages']} message{'s' if row['messages'] != 1 else ''}")
    return " · ".join(parts)


def describe_session(session_id: str | None) -> str:
    """Human summary for the host brief; empty string if nothing is known."""
    if not session_id or not settings.tracking_enabled:
        return ""
    try:
        with conn() as c:
            row = c.execute(
                """SELECT s.city, s.region, s.country, s.country_code, s.isp, s.referrer_host, s.channel, s.utm, s.page,
                          s.messages, s.geo_status, s.client_tz,
                          (SELECT count(*) FROM sessions v WHERE v.visitor_id = s.visitor_id AND s.visitor_id IS NOT NULL
                             AND v.first_seen <= s.first_seen) AS visit_number
                   FROM sessions s WHERE s.session_id = %s""",
                (session_id,),
            ).fetchone()
        if not row:
            return ""
        keys = ["city", "region", "country", "country_code", "isp", "referrer_host", "channel", "utm", "page",
                "messages", "geo_status", "client_tz", "visit_number"]
        return format_origin(dict(zip(keys, row)))
    except Exception as e:
        log.warning("describe_session failed: %s", e)
        return ""


def recent_sessions(days: int = 7, limit: int = 200) -> dict[str, Any]:
    days, limit = max(1, min(days, 365)), max(1, min(limit, 1000))
    with conn() as c:
        rows = c.execute(
            """SELECT s.session_id, s.visitor_id, s.first_seen, s.last_seen, s.ip, s.country, s.country_code, s.region,
                      s.city, s.lat, s.lon, s.isp, s.geo_status, s.channel, s.referrer_host, s.referrer, s.page, s.utm,
                      s.client_tz, s.lang, s.screen, s.user_agent, s.messages, s.leads,
                      (SELECT count(*) FROM sessions v WHERE v.visitor_id = s.visitor_id AND s.visitor_id IS NOT NULL) AS visits,
                      s.user_id, s.user_name, s.user_email
               FROM sessions s WHERE s.first_seen > now() - make_interval(days => %s)
               ORDER BY s.first_seen DESC LIMIT %s""",
            (days, limit),
        ).fetchall()
        cols = ["session_id", "visitor_id", "first_seen", "last_seen", "ip", "country", "country_code", "region", "city",
                "lat", "lon", "isp", "geo_status", "channel", "referrer_host", "referrer", "page", "utm", "client_tz",
                "lang", "screen", "user_agent", "messages", "leads", "visits", "user_id", "user_name", "user_email"]
        items = [dict(zip(cols, r)) for r in rows]
        by_country = c.execute(
            """SELECT COALESCE(country, '(unknown)'), count(*) FROM sessions
               WHERE first_seen > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", (days,)).fetchall()
        by_channel = c.execute(
            """SELECT COALESCE(channel, 'direct'), count(*) FROM sessions
               WHERE first_seen > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 2 DESC""", (days,)).fetchall()
        totals = c.execute(
            """SELECT count(*), count(DISTINCT visitor_id), COALESCE(sum(messages), 0), COALESCE(sum(leads), 0)
               FROM sessions WHERE first_seen > now() - make_interval(days => %s)""", (days,)).fetchone()
    return {
        "days": days,
        "summary": {"sessions": int(totals[0]), "visitors": int(totals[1]), "messages": int(totals[2]), "leads": int(totals[3]),
                    "countries": [{"country": r[0], "sessions": int(r[1])} for r in by_country],
                    "channels": [{"channel": r[0], "sessions": int(r[1])} for r in by_channel]},
        "items": items,
    }


def purge() -> dict[str, int]:
    """Retention: drop IPs and user agents after TRACK_RETENTION_DAYS; keep the geo/channel aggregate forever."""
    with conn() as c:
        a = c.execute(
            """UPDATE sessions SET ip = NULL, user_agent = NULL
               WHERE first_seen < now() - make_interval(days => %s) AND (ip IS NOT NULL OR user_agent IS NOT NULL)""",
            (settings.track_retention_days,)).rowcount
        b = c.execute("DELETE FROM ip_geo WHERE fetched_at < now() - make_interval(days => %s)", (GEO_CACHE_DAYS,)).rowcount
        c.commit()
    log.info("tracking purge: %s sessions scrubbed, %s geo cache rows dropped", a, b)
    return {"sessions_scrubbed": int(a), "geo_cache_dropped": int(b)}


def new_session_id() -> str:
    return str(uuid.uuid4())


if __name__ == "__main__":  # python -m app.tracking 8.8.8.8
    ip = sys.argv[1] if len(sys.argv) > 1 else "8.8.8.8"
    print(json.dumps(_fetch_geo(ip) if is_public(ip) else {"status": "private"}, indent=2))
