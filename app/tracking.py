"""Session origin tracking: who opened a chat session, from where (IP -> city/country) and how they arrived.

Flow
  chat opens    -> POST /track {session_id, visitor_id, page, referrer, tz, lang, screen}
                   the server adds the client IP + user agent, upserts `sessions`, and geolocates the IP
                   on a background thread so the beacon returns immediately; the same lookup names the network
                   (ASN, owner, kind: app/network.py), cached per /24 in ip_net
  every 10 min  -> retry_pending(): lookups still pending or failed are tried again
  each /chat    -> ensure_session(): last_seen + message count (creates the row if the beacon never fired); /chat and
                   /booking/confirm also carry the beacon fields while the widget has no confirmed /track
  bookings etc. -> confirm, hand-over, reschedule and cancel call ensure_session too; inbox.log_message inserts a bare
                   row as a last resort, so every session with messages, bookings or leads has a sessions row
  book_slot     -> the lead carries session_id and a one-line origin summary for the host brief
  daily         -> purge(): IPs and user agents older than TRACK_RETENTION_DAYS are nulled, and so is the city unless
                   the network is an organisation's; country and network owner stay;
                   backfill_orphans() repairs any session a write path missed

The visitor id is a random UUID the widget keeps in the site's own localStorage (first party, no cookie), so
returning visitors are recognised across sessions. Nothing here fingerprints the browser.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

import httpx

from app import network
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
_FWD_HEADERS = ("cf-connecting-ip", "x-real-ip", "x-forwarded-for")
_trusted: tuple[str, list] = ("", [])
_ignored_warned: float | None = None  # monotonic time of the last 'headers ignored' warning


def _trusted_nets() -> list:
    global _trusted
    raw = settings.trusted_proxies or ""
    if _trusted[0] != raw:
        nets = []
        for part in raw.split(","):
            try:
                nets.append(ipaddress.ip_network(part.strip(), strict=False))
            except ValueError:
                if part.strip():
                    log.warning("TRUSTED_PROXIES: ignoring %r", part.strip())
        _trusted = (raw, nets)
    return _trusted[1]


def is_trusted_proxy(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a.version == n.version and a in n for n in _trusted_nets())


def client_ip(headers: Mapping[str, str], peer: str | None, trust_proxy: bool | None = None) -> str:
    """The visitor's IP. Behind Cloudflare / nginx the socket peer is the proxy and the real address is in a header;
    headers are believed only when TRUST_PROXY is on and the peer is in TRUSTED_PROXIES (else anyone could forge one).
    X-Forwarded-For is walked right to left past trusted hops: the first untrusted address is the client."""
    global _ignored_warned
    trust = settings.trust_proxy if trust_proxy is None else trust_proxy
    peer = (peer or "").strip()
    if trust and is_trusted_proxy(peer):
        for h in ("cf-connecting-ip", "x-real-ip"):
            v = (headers.get(h) or "").strip()
            if _valid_ip(v):
                return v
        hops = [h.strip() for h in (headers.get("x-forwarded-for") or "").split(",") if _valid_ip(h.strip())]
        for h in reversed(hops):
            if not is_trusted_proxy(h):
                return h
        if hops:
            return hops[0]
    elif trust and any(headers.get(h) for h in _FWD_HEADERS) and (
            _ignored_warned is None or time.monotonic() - _ignored_warned > 3600):
        _ignored_warned = time.monotonic()
        log.warning("forwarding headers ignored; add your proxy/CDN ranges to TRUSTED_PROXIES")
    return peer if _valid_ip(peer) else "unknown"


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


# ---------------------------------------------------------------- geolocation + network (cached per /24 or /48)
_HTTP_TIMEOUT = 2.5
_COOLDOWN_S = 15 * 60       # after a 429 without a usable Retry-After, or after _MAX_ERRORS errors in a row
_MAX_ERRORS = 5
# in-process state; enough because the app runs one uvicorn worker (Dockerfile --workers 1)
_state_lock = threading.Lock()
_cooldown: dict[str, float] = {}           # provider -> time.time() until which it is skipped
_errors: dict[str, int] = {}               # provider -> consecutive errors
_quota: dict[tuple[str, str], int] = {}    # (provider, UTC date) -> outbound lookups today
_mmdb: dict[str, Any] = {}                 # opened GeoLite2 readers, or {"missing": reason}
_rdns_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rdns")
_ASN_RE = re.compile(r"^AS(\d+)\s*(.*)$", re.I)
_GEO_STR = ("country", "country_code", "region", "city", "isp", "geo_tz", "as_org", "org", "net_domain", "type", "rdns_domain")


def _asn(text: Any) -> tuple[int | None, str | None]:
    """'AS15169 Google LLC' -> (15169, 'Google LLC'); a bare number works too."""
    if isinstance(text, int):
        return text, None
    m = _ASN_RE.match(str(text or "").strip())
    if not m:
        return (int(text), None) if str(text or "").strip().isdigit() else (None, None)
    return int(m.group(1)), (m.group(2).strip() or None)


def _flag(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def _any_flag(*vs: Any) -> bool | None:
    vals = [v for v in vs if isinstance(v, bool)]
    return any(vals) if vals else None


def _rdns_fields(host: str | None) -> dict[str, Any]:
    """What a reverse-DNS name says about the network. The name itself (it often embeds the IP) is never kept."""
    host = (host or "").strip().rstrip(".").lower()
    if not host or "." not in host:
        return {}
    return {"rdns_domain": network.registrable(host), "rdns_dynamic": bool(network.RDNS_DYNAMIC_RE.search(host))}


def normalise_geo(provider: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Map a provider payload onto our columns. Unknown or failed lookups come back with status='failed'.
    Network keys: asn, as_org (AS owner), org (netblock holder when the provider has one; org_scope says which),
    net_domain, type (provider-given kind), flags {mobile, proxy, hosting}, rdns_domain/rdns_dynamic. Never an IP
    or a hostname."""
    g: dict[str, Any] = {"country": None, "country_code": None, "region": None, "city": None,
                         "lat": None, "lon": None, "isp": None, "geo_tz": None, "status": "failed",
                         "asn": None, "as_org": None, "org": None, "org_scope": None, "net_domain": None, "type": None,
                         "flags": {"mobile": None, "proxy": None, "hosting": None}, "rdns_domain": None,
                         "rdns_dynamic": None, "provider": provider}
    try:
        if provider == "ipwho" and data.get("success", True) and data.get("country"):
            cx = data.get("connection") or {}
            g.update(country=data.get("country"), country_code=data.get("country_code"), region=data.get("region"),
                     city=data.get("city"), lat=data.get("latitude"), lon=data.get("longitude"),
                     isp=(cx.get("isp") or cx.get("org")), geo_tz=(data.get("timezone") or {}).get("id"), status="ok",
                     asn=_asn(cx.get("asn"))[0], as_org=cx.get("org"), net_domain=cx.get("domain"), org_scope="asn")
        elif provider == "ipinfo" and data.get("country") and not data.get("bogon"):
            lat, _, lon = (data.get("loc") or ",").partition(",")
            asn, as_org = _asn(data.get("org"))
            a, co, pv = data.get("asn"), data.get("company"), data.get("privacy")  # paid plans only
            a, co, pv = (a if isinstance(a, dict) else {}), (co if isinstance(co, dict) else {}), (pv if isinstance(pv, dict) else {})
            g.update(country=data.get("country"), country_code=data.get("country"), region=data.get("region"),
                     city=data.get("city"), lat=float(lat) if lat else None, lon=float(lon) if lon else None,
                     isp=data.get("org"), geo_tz=data.get("timezone"), status="ok",
                     asn=_asn(a.get("asn"))[0] or asn, as_org=a.get("name") or as_org, net_domain=a.get("domain"),
                     type=co.get("type") or a.get("type"), org_scope="asn",
                     flags={"mobile": None, "proxy": _any_flag(pv.get("vpn"), pv.get("proxy"), pv.get("tor"), pv.get("relay")),
                            "hosting": _flag(pv.get("hosting"))})
            if co.get("name"):
                g.update(org=co["name"], org_scope="netblock")
            g.update(_rdns_fields(data.get("hostname")))
        elif provider == "ipapi" and data.get("status") == "success":
            asn, as_text = _asn(data.get("as"))
            g.update(country=data.get("country"), country_code=data.get("countryCode"), region=data.get("regionName"),
                     city=data.get("city"), lat=data.get("lat"), lon=data.get("lon"), isp=data.get("isp"),
                     geo_tz=data.get("timezone"), status="ok",
                     asn=asn, as_org=as_text or data.get("asname"), org=data.get("org") or None, org_scope="netblock",
                     flags={"mobile": _flag(data.get("mobile")), "proxy": _flag(data.get("proxy")),
                            "hosting": _flag(data.get("hosting"))})
        elif provider == "ipapiis" and (data.get("location") or {}).get("country"):
            loc, a, co = data.get("location") or {}, data.get("asn") or {}, data.get("company") or {}
            g.update(country=loc.get("country"), country_code=(loc.get("country_code") or "").upper() or None,
                     region=loc.get("state"), city=loc.get("city"), lat=loc.get("latitude"), lon=loc.get("longitude"),
                     geo_tz=loc.get("timezone"), isp=a.get("org") or co.get("name"), status="ok",
                     asn=_asn(a.get("asn"))[0], as_org=a.get("org"), net_domain=a.get("domain"),
                     org=co.get("name"), org_scope="netblock" if co.get("name") else None,
                     type=co.get("type") or a.get("type"),
                     flags={"mobile": _flag(data.get("is_mobile")),
                            "proxy": _any_flag(data.get("is_vpn"), data.get("is_proxy"), data.get("is_tor")),
                            "hosting": _flag(data.get("is_datacenter"))})
        elif provider == "mmdb" and data.get("country"):  # already flat, from _mmdb_lookup
            g.update({k: data.get(k) for k in ("country", "country_code", "region", "city", "lat", "lon", "geo_tz", "asn", "as_org")},
                     isp=data.get("as_org"), org_scope="asn", status="ok")
    except (TypeError, ValueError, AttributeError):
        pass
    for k in _GEO_STR:
        if g[k] is not None:
            g[k] = str(g[k])[:120]
    if g["type"]:
        g["type"] = g["type"].lower()
    return g


def _failed(provider: str, reason: str) -> dict[str, Any]:
    return normalise_geo(provider, {}) | {"reason": reason}


def _mmdb_lookup(ip: str) -> dict[str, Any]:
    """Local MaxMind GeoLite2 files (GEOIP_MMDB_DIR): place and AS, no domain. Optional `pip install maxminddb`."""
    if not _mmdb:
        try:
            import maxminddb  # type: ignore[import-not-found]
            from pathlib import Path

            d = Path(settings.geoip_mmdb_dir or ".")
            _mmdb["city"] = maxminddb.open_database(str(d / "GeoLite2-City.mmdb"))
            _mmdb["asn"] = maxminddb.open_database(str(d / "GeoLite2-ASN.mmdb"))
        except Exception as e:  # ImportError, missing files
            _mmdb.clear()
            _mmdb["missing"] = str(e)[:200]
            log.warning("mmdb geo provider unavailable: %s", _mmdb["missing"])
    if "missing" in _mmdb:
        return _failed("mmdb", "unavailable")
    try:
        city = _mmdb["city"].get(ip) or {}
        asn = _mmdb["asn"].get(ip) or {}
    except Exception as e:
        log.warning("mmdb lookup failed: %s", e)
        return _failed("mmdb", "error")
    en = lambda rec: ((rec or {}).get("names") or {}).get("en")  # noqa: E731
    flat = {"country": en(city.get("country")), "country_code": (city.get("country") or {}).get("iso_code"),
            "region": en((city.get("subdivisions") or [{}])[0]), "city": en(city.get("city")),
            "lat": (city.get("location") or {}).get("latitude"), "lon": (city.get("location") or {}).get("longitude"),
            "geo_tz": (city.get("location") or {}).get("time_zone"),
            "asn": asn.get("autonomous_system_number"), "as_org": asn.get("autonomous_system_organization")}
    g = normalise_geo("mmdb", flat)
    return g if g["status"] == "ok" else g | {"reason": "no_data"}


def mmdb_problem() -> str | None:
    """Why the mmdb provider cannot work here (None when it can). For the startup warning."""
    try:
        import maxminddb  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return "the maxminddb package is not installed (pip install maxminddb)"
    from pathlib import Path

    d = Path(settings.geoip_mmdb_dir or ".")
    missing = [f for f in ("GeoLite2-City.mmdb", "GeoLite2-ASN.mmdb") if not (d / f).is_file()]
    return f"missing in GEOIP_MMDB_DIR={settings.geoip_mmdb_dir!r}: {', '.join(missing)}" if missing else None


def _retry_in(headers: Mapping[str, str]) -> int:
    for h in ("retry-after", "x-ttl"):  # x-ttl: ip-api's seconds until the window resets
        v = (headers.get(h) or "").strip()
        if v.isdigit() and int(v) > 0:
            return min(int(v), 24 * 3600)
    return _COOLDOWN_S


def _fetch_one(provider: str, ip: str) -> dict[str, Any]:
    """One provider, one lookup: the normalised geo, or a failure with `reason` (and `retry_in` seconds on a 429)."""
    if provider == "mmdb":
        return _mmdb_lookup(ip)
    if provider == "ipwho":
        url, params = f"https://ipwho.is/{ip}", {}
    elif provider == "ipinfo":
        url, params = f"https://ipinfo.io/{ip}/json", ({"token": settings.geoip_token} if settings.geoip_token else {})
    elif provider == "ipapi":  # plain HTTP and non-commercial only: main warns at startup; 'reverse' is never requested
        url, params = f"http://ip-api.com/json/{ip}", {
            "fields": "status,message,country,countryCode,regionName,city,lat,lon,timezone,isp,org,as,asname,mobile,proxy,hosting"}
    elif provider == "ipapiis":
        url, params = "https://api.ipapi.is/", {"q": ip}
    else:
        log.warning("unknown GEOIP_PROVIDER %r", provider)
        return _failed(provider, "unknown provider")
    try:
        r = httpx.get(url, params=params, timeout=_HTTP_TIMEOUT, headers={"User-Agent": settings.crawl_user_agent})
        if r.status_code == 429:
            return _failed(provider, "rate_limited") | {"retry_in": _retry_in(r.headers)}
        r.raise_for_status()
        g = normalise_geo(provider, r.json())
        return g if g["status"] == "ok" else g | {"reason": "no_data"}
    except (httpx.HTTPError, ValueError) as e:
        log.warning("geo lookup via %s failed: %s", provider, e)
        return _failed(provider, "error")


def providers() -> list[str]:
    return [p.strip() for p in (settings.geoip_provider or "").split(",") if p.strip() and p.strip() != "none"]


def _take_slot(provider: str) -> str | None:
    """None when the provider may be called now (and counts the call), else why not: 'cooldown' or 'quota'."""
    with _state_lock:
        if _cooldown.get(provider, 0) > time.time():
            return "cooldown"
        if provider == "mmdb":  # local files: no quota
            return None
        today = datetime.now(timezone.utc).date().isoformat()
        for k in [k for k in _quota if k[1] != today]:
            del _quota[k]
        if _quota.get((provider, today), 0) >= settings.geoip_daily_cap:
            return "quota"
        _quota[(provider, today)] = _quota.get((provider, today), 0) + 1
        return None


def _note_result(provider: str, g: dict[str, Any]) -> None:
    """A 429 pauses the provider (Retry-After / X-Ttl, else 15 min); so do 5 errors in a row."""
    retry_in = g.pop("retry_in", None)
    pause = 0
    with _state_lock:
        if g.get("reason") == "rate_limited":
            pause = retry_in or _COOLDOWN_S
        elif g.get("reason") == "error":
            _errors[provider] = _errors.get(provider, 0) + 1
            pause = _COOLDOWN_S if _errors[provider] >= _MAX_ERRORS else 0
        if pause or g.get("reason") != "error":
            _errors[provider] = 0
        if pause:
            _cooldown[provider] = time.time() + pause
    if pause:
        log.warning("geo provider %s paused for %s s (%s)", provider, pause, g.get("reason"))


def _fetch_geo(ip: str) -> dict[str, Any]:
    """The provider chain (GEOIP_PROVIDER, e.g. 'mmdb,ipwho'): the first 'ok' wins. A provider in cooldown or over
    GEOIP_DAILY_CAP is skipped."""
    chain = providers()
    if not chain:
        return normalise_geo("none", {}) | {"status": "disabled"}
    last: dict[str, Any] = {}
    for p in chain:
        skip = _take_slot(p)
        if skip:
            last = _failed(p, skip)
            continue
        g = _fetch_one(p, ip)
        _note_result(p, g)
        if g.get("status") == "ok":
            return g
        last = g
    return last


def _dev_ip(ip: str) -> str | None:
    """GEOIP_DEV_IP stands in for a private address, only against a local database (same guard as main._origin_ok)."""
    dev = (settings.geoip_dev_ip or "").strip()
    local_db = "@localhost" in settings.database_url or "@127.0.0.1" in settings.database_url
    return dev if dev and local_db and _valid_ip(ip) and is_public(dev) else None


def _dev_tag(geo: Mapping[str, Any], dev: bool) -> dict[str, Any]:
    g = dict(geo)
    if dev:
        g["flags"] = dict(g.get("flags") or {}, dev=True)
    return g


def geolocate(ip: str) -> dict[str, Any]:
    """Cached per /24 (/48): private/loopback addresses are never sent anywhere, and the cache holds no IP."""
    dev = False
    if not is_public(ip):
        alt = _dev_ip(ip)
        if not alt:
            return normalise_geo("none", {}) | {"status": "unknown" if ip == "unknown" else "private"}
        ip, dev = alt, True
    net = mask_ip(ip)
    with conn() as c:
        row = c.execute(
            """SELECT data, (status = 'ok' AND fetched_at > now() - make_interval(days => %s))
                            OR (status = 'failed' AND retry_after > now())
               FROM ip_net WHERE net = %s""", (GEO_CACHE_DAYS, net)).fetchone()
    if row and row[1]:
        return _dev_tag(row[0], dev)
    geo = _fetch_geo(ip)
    if geo.get("status") in ("ok", "failed"):  # 'disabled' (GEOIP_PROVIDER=none) is not cached
        with conn() as c:
            c.execute(
                """INSERT INTO ip_net(net, provider, data, status, retry_after, fetched_at)
                   VALUES (%(net)s, %(p)s, %(d)s::jsonb, %(s)s,
                           CASE WHEN %(s)s = 'failed' THEN now() + make_interval(mins => %(m)s) END, now())
                   ON CONFLICT (net) DO UPDATE SET provider = EXCLUDED.provider, data = EXCLUDED.data, status = EXCLUDED.status,
                       retry_after = EXCLUDED.retry_after, fetched_at = now()""",
                {"net": net, "p": geo.get("provider"), "d": json.dumps(geo), "s": geo["status"], "m": settings.geoip_fail_retry_min})
            c.commit()
    return _dev_tag(geo, dev)


# ---------------------------------------------------------------- session rows
_SID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
_VID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def valid_sid(s: str | None) -> bool:
    """Same rule as TrackIn.session_id. Ids that fail it (API callers' 's1') never get a sessions row."""
    return bool(_SID_RE.fullmatch(s or ""))


def clean_vid(s: str | None) -> str | None:
    """The visitor id if it has the TrackIn.visitor_id shape, else None (a junk header is never stored)."""
    s = (s or "").strip()
    return s if _VID_RE.fullmatch(s) else None


# Every writer goes through this one statement. ip only fills a row that never had one ('unknown', or 'pending'
# from attach_user/attach_visitor): a row purged after geo keeps its original place and is never re-geolocated.
_ENSURE_SQL = """
WITH old AS (SELECT ip FROM sessions WHERE session_id = %(sid)s)
INSERT INTO sessions(session_id, visitor_id, ip, user_agent, page, referrer, referrer_host, channel, utm,
                     client_tz, lang, screen, messages, leads, geo_status)
VALUES (%(sid)s, %(vid)s, %(ip)s, %(ua)s, %(page)s, %(ref)s, %(ref_host)s, %(channel)s, %(utm)s::jsonb,
        %(tz)s, %(lang)s, %(screen)s, %(msg)s, %(lead)s, %(geo)s)
ON CONFLICT (session_id) DO UPDATE SET
    last_seen   = now(),
    visitor_id  = COALESCE(sessions.visitor_id, EXCLUDED.visitor_id),
    ip          = CASE WHEN sessions.ip IS NULL AND COALESCE(sessions.geo_status, 'unknown') IN ('unknown', 'pending')
                       THEN EXCLUDED.ip ELSE sessions.ip END,
    geo_status  = CASE WHEN sessions.ip IS NULL AND COALESCE(sessions.geo_status, 'unknown') IN ('unknown', 'pending')
                        AND EXCLUDED.ip IS NOT NULL THEN 'pending' ELSE sessions.geo_status END,
    user_agent  = COALESCE(sessions.user_agent, EXCLUDED.user_agent),
    channel     = CASE WHEN sessions.page IS NULL AND EXCLUDED.page IS NOT NULL THEN EXCLUDED.channel
                       ELSE COALESCE(sessions.channel, EXCLUDED.channel) END,
    page        = COALESCE(sessions.page, EXCLUDED.page),
    referrer    = COALESCE(sessions.referrer, EXCLUDED.referrer),
    referrer_host = COALESCE(sessions.referrer_host, EXCLUDED.referrer_host),
    utm         = CASE WHEN sessions.utm = '{}'::jsonb THEN EXCLUDED.utm ELSE sessions.utm END,
    client_tz   = COALESCE(sessions.client_tz, EXCLUDED.client_tz),
    lang        = COALESCE(sessions.lang, EXCLUDED.lang),
    screen      = COALESCE(sessions.screen, EXCLUDED.screen),
    messages    = sessions.messages + EXCLUDED.messages,
    leads       = sessions.leads + EXCLUDED.leads
RETURNING (xmax = 0) AS inserted,
          ((SELECT ip FROM old) IS NULL AND sessions.ip IS NOT NULL AND sessions.geo_status = 'pending') AS got_ip"""


def ensure_session(session_id: str | None, *, visitor_id: str | None = None, ip: str | None = None,
                   user_agent: str | None = None, page: str | None = None, referrer: str | None = None,
                   client_tz: str | None = None, lang: str | None = None, screen: str | None = None,
                   message: bool = False, lead: bool = False) -> bool | None:
    """Create or update the session row: True when created, False when updated, None when skipped or failed.
    First values win (COALESCE). With TRACKING_ENABLED off only the visitor id and the counters are stored.
    Never raises; tracking must not take the chat or a booking down."""
    if not valid_sid(session_id):
        return None
    on = settings.tracking_enabled
    if not on:
        ip = user_agent = page = referrer = client_tz = lang = screen = None
    elif ip is not None and not _valid_ip(ip):
        ip = None  # 'unknown' from client_ip is never stored
    utm = parse_utm(page)
    params = {
        "sid": session_id, "vid": (visitor_id or "")[:64] or None, "ip": ip, "ua": (user_agent or "")[:300] or None,
        "page": (page or "")[:500] or None, "ref": (referrer or "")[:500] or None, "ref_host": referrer_host(referrer) or None,
        "channel": classify_channel(referrer, utm), "utm": json.dumps(utm), "tz": (client_tz or "")[:64] or None,
        "lang": (lang or "")[:16] or None, "screen": (screen or "")[:16] or None, "msg": int(message), "lead": int(lead),
        "geo": "disabled" if not on else ("pending" if ip else "unknown"),
    }
    try:
        with conn() as c:
            inserted, got_ip = c.execute(_ENSURE_SQL, params).fetchone()
            c.commit()
    except Exception as e:
        log.warning("ensure_session failed for %s: %s", session_id, e)
        return None
    if got_ip and on and ip:
        _executor.submit(_enrich, session_id, ip)
    return bool(inserted)


def start_session(session_id: str, visitor_id: str | None, ip: str, user_agent: str | None, page: str | None,
                  referrer: str | None, client_tz: str | None, lang: str | None, screen: str | None) -> dict[str, Any]:
    """Called by the /track beacon when the chat opens. Idempotent per session: the landing page, referrer and
    UTM parameters are kept from the first call; last_seen moves on every call."""
    if not settings.tracking_enabled:
        return {"ok": True, "tracked": False}
    visitor_id = clean_vid(visitor_id)
    r = ensure_session(session_id, visitor_id=visitor_id, ip=ip, user_agent=user_agent, page=page, referrer=referrer,
                       client_tz=client_tz, lang=lang, screen=screen)
    if r is None:
        return {"ok": False, "tracked": False}  # the widget retries
    visits = 1
    if visitor_id:
        with conn() as c:
            visits = c.execute("SELECT count(*) FROM sessions WHERE visitor_id = %s", (visitor_id,)).fetchone()[0]
    return {"ok": True, "tracked": True, "channel": classify_channel(referrer, parse_utm(page)), "visit_number": int(visits)}


def touch(session_id: str, ip: str, user_agent: str | None) -> None:
    """Every chat message: bump the counters, and create the row if the beacon never fired. Never raises."""
    ensure_session(session_id, ip=ip, user_agent=user_agent, message=True)


def net_columns(geo: Mapping[str, Any]) -> dict[str, Any]:
    """The sessions network columns for a geo result. No lookup (failed, disabled) means no verdict: net_kind stays
    NULL and the retry job tries again."""
    kind, why, mobile = network.classify(geo)
    if geo.get("status") not in ("ok", "private"):
        kind = None
    gf = geo.get("flags") or {}
    flags = {"mobile": mobile, "proxy": gf.get("proxy"), "hosting": gf.get("hosting"), "why": why if kind else None,
             "provider": geo.get("provider"), "dev": bool(gf.get("dev"))}
    return {"asn": geo.get("asn"), "net_org": network.org_of(geo, kind) if kind not in (None, "local") else None,
            "net_domain": geo.get("net_domain"), "net_kind": kind, "net_flags": flags}


def _enrich(session_id: str, ip: str) -> None:
    """Background: geo and network in one UPDATE, so wait_enriched() sees both at once. Reverse DNS (NET_RDNS) only
    refines the kind afterwards."""
    try:
        geo = geolocate(ip)
        net = net_columns(geo)
        stored_ip = mask_ip(ip) if settings.track_ip_mode == "masked" else ip
        with conn() as c:
            c.execute(
                """UPDATE sessions SET country=%s, country_code=%s, region=%s, city=%s, lat=%s, lon=%s, isp=%s,
                                       geo_tz=%s, geo_status=%s, ip=%s, asn=%s, net_org=%s, net_domain=%s, net_kind=%s,
                                       net_flags=%s::jsonb, geo_at=now()
                   WHERE session_id = %s""",
                (geo["country"], geo["country_code"], geo["region"], geo["city"], geo["lat"], geo["lon"], geo["isp"],
                 geo["geo_tz"], geo["status"], stored_ip, net["asn"], net["net_org"], net["net_domain"], net["net_kind"],
                 json.dumps(net["net_flags"]), session_id),
            )
            c.commit()
        if settings.net_rdns and geo.get("status") == "ok" and not net["net_flags"]["dev"]:
            _rdns_refine(session_id, ip, geo, net["net_kind"])
    except Exception as e:
        log.warning("geo enrich failed for %s: %s", session_id, e)


def _rdns_refine(session_id: str, ip: str, geo: Mapping[str, Any], kind: str | None) -> None:
    """NET_RDNS: a PTR lookup (1 s cap). Only the registrable domain and a 'looks dynamic' flag are derived; the
    hostname is discarded. A second UPDATE only when the kind changes."""
    try:
        host = _rdns_executor.submit(socket.gethostbyaddr, ip).result(timeout=1.0)[0]
    except Exception:
        return
    extra = _rdns_fields(host)
    if not extra:
        return
    net = net_columns(dict(geo, **extra))
    if net["net_kind"] == kind:
        return
    with conn() as c:
        c.execute("""UPDATE sessions SET net_kind = %s, net_org = %s, net_flags = net_flags || %s::jsonb
                     WHERE session_id = %s""",
                  (net["net_kind"], net["net_org"], json.dumps({"why": net["net_flags"]["why"], **extra}), session_id))
        c.commit()


def wait_enriched(session_id: str | None, timeout: float = 4.0) -> bool:
    """Worker threads only: poll (0.25 s) until the session's lookup is done. True when it is (or there is no row),
    False on timeout or error."""
    if not session_id:
        return True
    deadline = time.monotonic() + timeout
    while True:
        try:
            with conn() as c:
                row = c.execute("SELECT geo_status FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
        except Exception as e:
            log.warning("wait_enriched failed: %s", e)
            return False
        if not row or row[0] != "pending":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def retry_pending() -> int:
    """Every 10 minutes: re-run the lookup for recent sessions still pending or failed (provider down, quota hit, a row
    that got its IP late). The ip_net failure cache stops a provider being called again inside GEOIP_FAIL_RETRY_MIN."""
    if not settings.tracking_enabled or not providers():
        return 0
    with conn() as c:
        rows = c.execute(
            """SELECT session_id, ip FROM sessions
               WHERE geo_status IN ('pending', 'failed') AND ip IS NOT NULL AND ip <> 'unknown'
                 AND first_seen > now() - interval '2 days'
                 AND COALESCE(geo_at, first_seen) < now() - interval '5 minutes'
               ORDER BY first_seen DESC LIMIT 50""").fetchall()
    for sid, ip in rows:
        _executor.submit(_enrich, sid, ip)
    if rows:
        log.info("geo retry: %s sessions re-submitted", len(rows))
    return len(rows)


def attach_visitor(session_id: str | None, visitor_id: str | None) -> None:
    """Make sure the session carries the browser's visitor id even if the /track beacon never fired."""
    vid = clean_vid(visitor_id)
    if vid:
        ensure_session(session_id, visitor_id=vid)


def attach_user(session_id: str | None, user: Mapping[str, Any] | None) -> None:
    """Signed-in visitor (verified token): remember who the session belongs to. Never raises."""
    if not valid_sid(session_id) or not user or not user.get("sub"):
        return
    try:
        with conn() as c:
            c.execute(
                """INSERT INTO sessions(session_id, user_id, user_name, user_email, channel, geo_status)
                   VALUES (%s, %s, %s, %s, 'direct', 'unknown')
                   ON CONFLICT (session_id) DO UPDATE SET user_id = EXCLUDED.user_id,
                       user_name = COALESCE(EXCLUDED.user_name, sessions.user_name),
                       user_email = COALESCE(EXCLUDED.user_email, sessions.user_email)""",
                (session_id, str(user["sub"])[:200], (user.get("name") or "")[:120] or None, (user.get("email") or "")[:200] or None),
            )
            c.commit()
    except Exception as e:
        log.warning("attach_user failed: %s", e)


def attach_lead(session_id: str | None, lead_id: int) -> None:
    """Count the lead against its session (creating the row if needed) and link the lead to it."""
    if not session_id:
        return
    if valid_sid(session_id):
        ensure_session(session_id, lead=True)
    try:
        with conn() as c:
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


def _flags(v: Any) -> dict[str, Any]:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def format_network(row: Mapping[str, Any], match_text: str | None = None) -> str:
    """One line about the network: 'Reliance Jio · home broadband', 'Infosys · company network · matches their company'.
    Empty when there is no verdict. format_origin() stays as it was; this is a separate line."""
    kind = row.get("net_kind")
    if not kind:
        return ""
    if kind == "local":
        return "local test network (no lookup)"
    flags = _flags(row.get("net_flags"))
    org = network.clean_org(row.get("net_org") or row.get("isp") or "")
    parts = [p for p in (org, network.label(kind, flags.get("mobile")), match_text) if p]
    return " · ".join(parts) + (" [dev test IP]" if flags.get("dev") else "")


_NET_COLS = ["asn", "net_org", "net_domain", "net_kind", "net_flags", "isp", "geo_tz", "client_tz", "geo_status"]


def describe_network(session_id: str | None) -> dict[str, Any]:
    """The session's network fields ({} when unknown or tracking is off)."""
    if not session_id or not settings.tracking_enabled:
        return {}
    try:
        with conn() as c:
            row = c.execute(f"SELECT {', '.join(_NET_COLS)} FROM sessions WHERE session_id = %s", (session_id,)).fetchone()
    except Exception as e:
        log.warning("describe_network failed: %s", e)
        return {}
    if not row:
        return {}
    d = dict(zip(_NET_COLS, row))
    d["net_flags"] = _flags(d["net_flags"])
    return d


def recent_sessions(days: int = 7, limit: int = 200) -> dict[str, Any]:
    days, limit = max(1, min(days, 365)), max(1, min(limit, 1000))
    with conn() as c:
        rows = c.execute(
            """SELECT s.session_id, s.visitor_id, s.first_seen, s.last_seen, s.ip, s.country, s.country_code, s.region,
                      s.city, s.lat, s.lon, s.isp, s.geo_status, s.channel, s.referrer_host, s.referrer, s.page, s.utm,
                      s.client_tz, s.lang, s.screen, s.user_agent, s.messages, s.leads,
                      (SELECT count(*) FROM sessions v WHERE v.visitor_id = s.visitor_id AND s.visitor_id IS NOT NULL) AS visits,
                      s.user_id, s.user_name, s.user_email, s.asn, s.net_org, s.net_domain, s.net_kind, s.net_flags
               FROM sessions s WHERE s.first_seen > now() - make_interval(days => %s)
               ORDER BY s.first_seen DESC LIMIT %s""",
            (days, limit),
        ).fetchall()
        cols = ["session_id", "visitor_id", "first_seen", "last_seen", "ip", "country", "country_code", "region", "city",
                "lat", "lon", "isp", "geo_status", "channel", "referrer_host", "referrer", "page", "utm", "client_tz",
                "lang", "screen", "user_agent", "messages", "leads", "visits", "user_id", "user_name", "user_email",
                "asn", "net_org", "net_domain", "net_kind", "net_flags"]
        items = [dict(zip(cols, r)) for r in rows]
        by_country = c.execute(
            """SELECT COALESCE(country, '(unknown)'), count(*) FROM sessions
               WHERE first_seen > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", (days,)).fetchall()
        by_channel = c.execute(
            """SELECT COALESCE(channel, 'direct'), count(*) FROM sessions
               WHERE first_seen > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 2 DESC""", (days,)).fetchall()
        by_kind = c.execute(
            """SELECT COALESCE(net_kind, 'unknown'), count(*) FROM sessions
               WHERE first_seen > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 2 DESC""", (days,)).fetchall()
        totals = c.execute(
            """SELECT count(*), count(DISTINCT visitor_id), COALESCE(sum(messages), 0), COALESCE(sum(leads), 0)
               FROM sessions WHERE first_seen > now() - make_interval(days => %s)""", (days,)).fetchone()
    return {
        "days": days,
        "summary": {"sessions": int(totals[0]), "visitors": int(totals[1]), "messages": int(totals[2]), "leads": int(totals[3]),
                    "countries": [{"country": r[0], "sessions": int(r[1])} for r in by_country],
                    "channels": [{"channel": r[0], "sessions": int(r[1])} for r in by_channel],
                    "by_kind": [{"kind": r[0], "sessions": int(r[1])} for r in by_kind]},
        "items": items,
    }


# location survives retention only where it describes an organisation, not a person's home
_KEEP_PLACE = ("corporate", "education", "government", "hosting")


def purge(session_ids: list[str] | None = None) -> dict[str, int]:
    """Retention, after TRACK_RETENTION_DAYS: IPs and user agents are dropped, and city/region/coordinates too unless the
    network is a company, university, government or cloud one (unknown is mostly residential). Country, channel and
    net_org stay. Old ip_net rows and the legacy ip_geo table go. `session_ids` limits the session scrub to those rows
    and skips the cache and backfill steps (tests on a shared database)."""
    only = "AND session_id = ANY(%(ids)s)" if session_ids is not None else ""
    p = {"days": settings.track_retention_days, "ids": session_ids or [], "keep": list(_KEEP_PLACE)}
    b = d = 0
    with conn() as c:
        a = c.execute(
            f"""UPDATE sessions SET ip = NULL, user_agent = NULL
                WHERE first_seen < now() - make_interval(days => %(days)s) AND (ip IS NOT NULL OR user_agent IS NOT NULL) {only}""",
            p).rowcount
        e = c.execute(
            f"""UPDATE sessions SET city = NULL, region = NULL, lat = NULL, lon = NULL
                WHERE first_seen < now() - make_interval(days => %(days)s)
                  AND COALESCE(net_kind, 'unknown') <> ALL(%(keep)s)
                  AND (city IS NOT NULL OR region IS NOT NULL OR lat IS NOT NULL OR lon IS NOT NULL) {only}""",
            p).rowcount
        if session_ids is None:
            b = c.execute("DELETE FROM ip_net WHERE fetched_at < now() - make_interval(days => %s)", (GEO_CACHE_DAYS,)).rowcount
            d = c.execute("DELETE FROM ip_geo").rowcount  # legacy per-IP cache, no longer written
        c.commit()
    log.info("tracking purge: %s sessions scrubbed, %s places dropped, %s geo cache rows dropped", a, e, b + d)
    return {"sessions_scrubbed": int(a), "places_scrubbed": int(e), "geo_cache_dropped": int(b + d),
            "orphans_backfilled": backfill_orphans() if session_ids is None else 0}


def backfill_orphans() -> int:
    """Give every session that has messages, bookings or leads but no sessions row a minimal one. Idempotent; runs at
    startup and from purge(). A non-zero count means some write path skipped ensure_session. -1 on error."""
    try:
        with conn() as c:
            n = c.execute(
                """INSERT INTO sessions(session_id, first_seen, last_seen, channel, geo_status, messages, leads)
                   SELECT x.sid, min(x.ts), max(x.ts), 'direct', 'unknown', sum(x.m), sum(x.l) FROM (
                       SELECT session_id AS sid, ts, (role = 'user')::int AS m, 0 AS l FROM messages
                       UNION ALL SELECT session_id, created_at, 0, 0 FROM bookings WHERE session_id IS NOT NULL
                       UNION ALL SELECT session_id, ts, 0, 1 FROM leads WHERE session_id IS NOT NULL) x
                   WHERE x.sid ~ '^[A-Za-z0-9_-]{8,64}$'
                     AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.session_id = x.sid)
                   GROUP BY x.sid
                   ON CONFLICT (session_id) DO NOTHING""").rowcount
            c.commit()
    except Exception as e:
        log.warning("backfill_orphans failed: %s", e)
        return -1
    if n > 0:
        log.warning("tracking: %s orphan sessions backfilled", n)
    return int(n)


def new_session_id() -> str:
    return str(uuid.uuid4())


def _cli(argv: list[str]) -> int:
    """python -m app.tracking <ip> [typed company] [email]: the provider chain, classify() and match(), with no
    database. The main way to try the network rules locally, where every session is 127.0.0.1."""
    from app import enrich

    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m app.tracking <ip> [typed company] [email]")
        return 2
    ip, typed, email = argv[0], (argv[1] if len(argv) > 1 else ""), (argv[2] if len(argv) > 2 else "")
    geo = _fetch_geo(ip) if is_public(ip) else normalise_geo("none", {}) | {"status": "private"}
    net = net_columns(geo)
    domain = enrich.domain_of(email)
    kind_of_email = "" if not domain else ("personal" if enrich.is_free_mail(domain) else "business")
    m = network.match({"kind": net["net_kind"] or "unknown", "net_org": net["net_org"], "net_domain": net["net_domain"]},
                      typed, domain, kind_of_email)
    print(json.dumps({"geo": geo, "network": net, "label": network.label(net["net_kind"], net["net_flags"]["mobile"]),
                      "match": m, "line": format_network(net, m["text"])}, indent=2, default=str))
    return 0


if __name__ == "__main__":  # python -m app.tracking 49.207.200.10 'Apple.INC' a@gmail.com
    sys.exit(_cli(sys.argv[1:]))
