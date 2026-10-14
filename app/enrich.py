"""Lead enrichment from the email domain: which company is this visitor from?

No paid API and no third party. A business domain's homepage is fetched once (two URL attempts, 3 s each,
300 KB cap) and its <title>, meta description and og:site_name are kept in the `companies` cache table for
30 days; free-mail domains (gmail, outlook, ...) are marked 'personal' without any request. The result lands on
the lead (leads.company / leads.enrichment), in the host brief as {company}, in the console and in the weekly digest.

lookup() never raises and never holds a booking for more than LOOKUP_BUDGET seconds: when the homepage is slow
the fetch finishes on its own thread and the cache fills for next time.

domain_proof() says what proves a business email's domain is real (the lead score's "checked" evidence): a homepage
read ('web'), a server that answered the homepage fetch with an HTTP status ('a'), or a DNS MX / A record kept in the
domain_dns table ('mx', 'a'); 'dead' for NXDOMAIN or no MX and no address, else 'unknown'. ensure_checked() runs the
DNS check (dnspython) on worker threads only (app/precall.py), never on a request the visitor waits on.
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from typing import Any, Callable

import httpx

from app.config import settings

log = logging.getLogger("enrich")

FETCH_TIMEOUT = 3.0
LOOKUP_BUDGET = 5.0
MAX_BYTES = 300_000
CACHE_DAYS = 30

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.co.uk", "ymail.com", "rocketmail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "live.co.uk", "msn.com", "icloud.com", "me.com",
    "mac.com", "aol.com", "protonmail.com", "proton.me", "pm.me", "zoho.com", "zohomail.com", "gmx.com", "gmx.de",
    "gmx.net", "web.de", "mail.com", "mail.ru", "yandex.com", "yandex.ru", "rediffmail.com", "fastmail.com",
    "hey.com", "tutanota.com", "tuta.io", "qq.com", "163.com", "126.com", "naver.com", "daum.net", "seznam.cz",
    "libero.it", "orange.fr", "wanadoo.fr", "free.fr", "laposte.net", "t-online.de", "btinternet.com", "sky.com",
    "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "cox.net", "charter.net", "duck.com",
}
FREE_ROOTS = {"gmail", "yahoo", "hotmail", "outlook", "live", "icloud", "protonmail", "proton", "gmx", "yandex", "mail"}
GENERIC_TITLE_PARTS = {"home", "homepage", "home page", "welcome", "official site", "official website", "login",
                       "sign in", "index", "start", "main"}

_mem: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- pure helpers
def domain_of(email: str | None) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return ""
    d = e.rsplit("@", 1)[1].strip(". ")
    return d if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d) else ""


def registrable_root(domain: str | None) -> str:
    """'mail.company.com' -> 'company', 'yahoo.com.au' -> 'yahoo', 'infilect.co.in' -> 'infilect'."""
    from app.network import domain_root

    return domain_root(domain)


def is_free_mail(domain: str) -> bool:
    d = (domain or "").lower()
    return d in FREE_MAIL or registrable_root(d) in FREE_ROOTS


# throwaway inboxes: nobody books a real call from one
DISPOSABLE = {
    "mailinator.com", "yopmail.com", "guerrillamail.com", "guerrillamail.net", "sharklasers.com", "grr.la", "10minutemail.com",
    "10minutemail.net", "temp-mail.org", "temp-mail.io", "tempmail.com", "tempmail.net", "tempmailo.com", "trashmail.com",
    "trashmail.de", "getnada.com", "nada.email", "dispostable.com", "maildrop.cc", "mailnesia.com", "throwawaymail.com",
    "fakeinbox.com", "emailondeck.com", "mintemail.com", "mohmal.com", "spamgourmet.com", "burnermail.io", "moakt.com",
    "tmail.ws", "discard.email", "mail.tm", "mailcatch.com", "spambox.us", "jetable.org", "mytemp.email",
}
EDU_RE = re.compile(r"(^|\.)edu(\.[a-z]{2})?$|(^|\.)ac\.[a-z]{2}$")
_EDU_NAME = re.compile(r"universit|college|deemed|polytechnic|\bIIT\b", re.I)


def is_disposable(domain: str | None) -> bool:
    d = (domain or "").lower()
    return d in DISPOSABLE or ".".join(d.split(".")[-2:]) in DISPOSABLE


def is_education(domain: str | None, data: dict[str, Any] | None = None) -> bool:
    """A university or college: .edu / .ac.xx / edu.xx domains, or a homepage company or title that says so. The
    description is never read: EdTech companies describe schools and colleges all day."""
    d = data or {}
    return bool(EDU_RE.search((domain or "").lower()) or _EDU_NAME.search(f"{d.get('company') or ''} {d.get('title') or ''}"))


def _distance(a: str, b: str) -> int:
    """Edit distance with adjacent swaps counted as one edit (gmial -> gmail)."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def typo_of_free_mail(domain: str | None) -> str | None:
    """The free-mail domain this one is a likely typo of ('gmial.com' -> 'gmail.com'), else None. Same first letter and
    within 1 edit (2 for 8+ characters), so real companies one letter off a short provider (aon.com, skf.com) stay business."""
    d = (domain or "").lower()
    if not d or d in FREE_MAIL or is_free_mail(d):
        return None
    best = None
    for f in sorted(FREE_MAIL):
        if f[0] != d[0] or len(f.split(".")[0]) < 5:
            continue
        dist = _distance(d, f)
        if dist <= (2 if len(d) >= 8 else 1) and (best is None or dist < best[0]):
            best = (dist, f)
    return best[1] if best else None


def from_domain(domain: str) -> str:
    """'lakeb2b.com' -> 'Lakeb2b'; 'span-global.co.uk' -> 'Span Global'."""
    root = (domain or "").split(".")[0]
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", root) if w)


def clean_title(title: str | None, domain: str) -> str:
    """Company name from a page title: drop generic parts ('Home', 'Welcome') and taglines, keep the brand."""
    t = html.unescape(re.sub(r"\s+", " ", title or "")).strip()
    if not t:
        return from_domain(domain)
    parts = [p.strip() for p in re.split(r"\s+[|\-–—·:»]\s+|\s*\|\s*", t) if p.strip()]
    parts = [p for p in parts if p.lower() not in GENERIC_TITLE_PARTS]
    if not parts:
        return from_domain(domain)
    root = domain.split(".")[0].replace("-", "")
    for p in parts:  # the part that looks like the domain wins ("LakeB2B" for lakeb2b.com)
        if root and root in re.sub(r"[^a-z0-9]", "", p.lower()):
            return p[:80]
    parts.sort(key=len)  # else the shortest meaningful part (brands are short, taglines are long)
    return parts[0][:80]


def _meta(doc: str, *names: str) -> str:
    for n in names:
        m = re.search(r'<meta[^>]+(?:name|property)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']{1,500})', doc, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']{1,500})["\'][^>]*(?:name|property)=["\']' + re.escape(n) + r'["\']', doc, re.I)
        if m:
            return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return ""


def parse_homepage(doc: str, domain: str) -> dict[str, Any]:
    doc = doc[:MAX_BYTES]
    m = re.search(r"<title[^>]*>(.*?)</title>", doc, re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    site = _meta(doc, "og:site_name", "application-name")
    desc = _meta(doc, "description", "og:description", "twitter:description")
    company = site or clean_title(title, domain)
    return {"company": company[:80], "title": title[:200], "description": desc[:300]}


def summary(data: dict[str, Any] | None) -> str:
    """One line for emails and the console: 'LakeB2B (lakeb2b.com) · B2B data and intent signals'."""
    if not data or data.get("kind") != "business":
        return ""
    domain = data.get("domain") or ""
    name = data.get("company") or from_domain(domain)
    line = f"{name} ({domain})" if domain and name.lower() != domain.lower() else (name or domain)
    desc = (data.get("description") or "").strip()
    if desc:
        line += " · " + (desc[:137] + "…" if len(desc) > 140 else desc)
    return line


# ---------------------------------------------------------------- fetch + cache
def fetch_homepage(domain: str, timeout: float = FETCH_TIMEOUT) -> dict[str, Any]:
    headers = {"User-Agent": settings.crawl_user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}
    last = ""
    for url in (f"https://{domain}", f"https://www.{domain}"):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as c:
                with c.stream("GET", url) as r:
                    if r.status_code >= 400 or "html" not in (r.headers.get("content-type") or ""):
                        last = f"{r.status_code} {r.headers.get('content-type', '')}".strip()
                        continue
                    buf = b""
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) >= MAX_BYTES:
                            break
                    data = parse_homepage(buf.decode(r.encoding or "utf-8", errors="replace"), domain)
                    data.update({"website": str(r.url), "source": "homepage"})
                    return data
        except (httpx.HTTPError, ValueError) as e:
            last = str(e)[:120]
    return {"company": from_domain(domain), "source": "unreachable", "error": last}


def _cache_get(domain: str) -> dict[str, Any] | None:
    with _lock:
        hit = _mem.get(domain)
    if hit and time.time() - hit[0] < CACHE_DAYS * 86400:
        return hit[1]
    try:
        from app.db import conn

        with conn() as c:
            row = c.execute("SELECT data FROM companies WHERE domain = %s AND fetched_at > now() - make_interval(days => %s)",
                            (domain, CACHE_DAYS)).fetchone()
        if row:
            data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            with _lock:
                _mem[domain] = (time.time(), data)
            return data
    except Exception as e:  # cache is an optimisation only
        log.debug("company cache read failed: %s", e)
    return None


def cached(domain: str | None) -> dict[str, Any] | None:
    """The cached enrichment of a domain, or None. Never fetches."""
    return _cache_get(domain) if domain else None


def _cache_put(domain: str, data: dict[str, Any]) -> None:
    with _lock:
        _mem[domain] = (time.time(), data)
    try:
        from app.db import conn

        with conn() as c:
            c.execute("""INSERT INTO companies(domain, data, fetched_at) VALUES (%s, %s::jsonb, now())
                         ON CONFLICT (domain) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()""",
                      (domain, json.dumps(data)))
            c.commit()
    except Exception as e:
        log.debug("company cache write failed: %s", e)


def lookup(email: str | None, budget: float = LOOKUP_BUDGET) -> dict[str, Any]:
    """Enrichment for an email address: {} when disabled or not an email; 'personal' for free mail; else the
    company data (from cache or a bounded homepage fetch). Never raises."""
    domain = domain_of(email)
    if not domain or not settings.enrich_enabled:
        return {}
    if is_free_mail(domain):
        return {"domain": domain, "kind": "personal", "company": "", "source": "freemail"}
    cached = _cache_get(domain)
    if cached:
        return cached
    result: dict[str, Any] = {}

    def work() -> None:
        try:
            data = fetch_homepage(domain)
        except Exception as e:  # pragma: no cover - fetch_homepage already catches httpx errors
            data = {"company": from_domain(domain), "source": "error", "error": str(e)[:120]}
        data.update({"domain": domain, "kind": "business"})
        result.update(data)
        _cache_put(domain, data)

    t = threading.Thread(target=work, name=f"enrich-{domain}", daemon=True)
    t.start()
    t.join(budget)
    if result:
        return dict(result)
    log.info("enrichment for %s still running after %.1fs; cached for next time", domain, budget)
    return {"domain": domain, "kind": "business", "company": from_domain(domain), "source": "pending"}


def lookup_domain(domain: str | None) -> dict[str, Any]:
    """The domain half of lookup(), for background threads only (app/visitors.py: an organisation's homepage for its
    industry): {} when enrichment is off, the domain is empty or free mail; else the cache, or a direct fetch on the
    calling thread that then fills the cache. Never raises."""
    domain = (domain or "").strip().lower()
    if not domain or not settings.enrich_enabled or is_free_mail(domain):
        return {}
    hit = _cache_get(domain)
    if hit:
        return hit
    try:
        data = fetch_homepage(domain)
    except Exception as e:  # fetch_homepage already catches httpx errors
        data = {"company": from_domain(domain), "source": "error", "error": str(e)[:120]}
    data.update({"domain": domain, "kind": "business"})
    _cache_put(domain, data)
    return data


# ---------------------------------------------------------------- DNS proof of a business email's domain
# Its own table (domain_dns), so the 30-day homepage cache filter never hides a result. Only the domain is ever queried
# or stored, never the address or a person. Worker threads only: never on a request the visitor waits on.
DNS_QUERY_TIMEOUT = 1.5   # seconds per query, and never past the caller's deadline
DNS_RETRY_MIN = 10        # an 'error' row is retried after this many minutes
DNS_OK_DAYS = 30          # mx / a stay proof this long
DNS_DEAD_DAYS = 3         # nxdomain / none count as dead this long, then are checked again
_MIN_LEFT = 0.3           # a resolver set is only tried with at least this much time left
_HTTP_STATUS = re.compile(r"^\d{3}\b")


class NoSuchDomain(Exception):
    """The domain does not exist (NXDOMAIN)."""


def _dns_resolve(domain: str, qtype: str, nameservers: list[str] | None, lifetime: float) -> list[str]:
    """One query: the MX exchange hosts (trailing '.' stripped, so a null MX reads '') or the addresses; [] for no answer."""
    import dns.resolver

    r = dns.resolver.Resolver(configure=nameservers is None)
    if nameservers:
        r.nameservers = nameservers
    r.timeout = r.lifetime = lifetime
    try:
        ans = r.resolve(domain, qtype, raise_on_no_answer=False, search=False)
    except dns.resolver.NXDOMAIN as e:
        raise NoSuchDomain(domain) from e
    if qtype == "MX":
        return [x.exchange.to_text().rstrip(".") for x in ans]
    return [x.to_text() for x in ans]


def dns_status(domain: str, deadline: float | None = None, resolve: Callable[..., list[str]] | None = None) -> str:
    """'mx' | 'a' | 'none' | 'nxdomain' | 'error' for a domain. `deadline` is a time.monotonic() value; every query's
    lifetime is capped by it. The system resolver first, then DOMAIN_CHECK_FALLBACK_NS while time remains. Never raises."""
    if resolve is None:
        if not settings.domain_check:
            return "error"
        resolve = _dns_resolve
    deadline = time.monotonic() + 4.0 if deadline is None else deadline
    fallback = [x.strip() for x in (settings.domain_check_fallback_ns or "").split(",") if x.strip()]
    for ns in [None] + ([fallback] if fallback else []):
        if deadline - time.monotonic() < _MIN_LEFT:
            break

        def ask(qtype: str) -> list[str]:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("domain check deadline passed")
            return resolve(domain, qtype, ns, min(DNS_QUERY_TIMEOUT, left))

        try:
            mx = ask("MX")
            if mx:
                return "none" if all(h in ("", ".") for h in mx) else "mx"
            return "a" if ask("A") or ask("AAAA") else "none"
        except NoSuchDomain:
            return "nxdomain"
        except Exception as e:  # DNSException, ValueError for over-long labels, ImportError without dnspython
            log.debug("dns check of %s via %s failed: %s", domain, ns or "system resolver", e)
    return "error"


def _recent(at: Any, days: float) -> bool:
    from datetime import datetime, timedelta, timezone

    return isinstance(at, datetime) and datetime.now(timezone.utc) - at < timedelta(days=days)


def domain_proof(source: str | None, error: str | None, status: str | None, checked_at: Any) -> str:
    """'web' | 'mx' | 'a' | 'dead' | 'unknown': what proves the domain is real. A homepage read is 'web'; a homepage
    fetch that got an HTTP status back means a server answered ('a'); else the DNS result while it is fresh."""
    if source in ("homepage", "test"):
        return "web"
    if source == "unreachable" and _HTTP_STATUS.match(error or ""):
        return "a"
    if status in ("mx", "a") and _recent(checked_at, DNS_OK_DAYS):
        return status
    if status in ("nxdomain", "none") and _recent(checked_at, DNS_DEAD_DAYS):
        return "dead"
    return "unknown"


PROOF_SQL = """SELECT x.d, n.status, n.checked_at, c.data->>'source', c.data->>'error',
                      extract(epoch FROM now() - n.checked_at) / 60
               FROM unnest(%s::text[]) AS x(d)
               LEFT JOIN domain_dns n ON n.domain = x.d
               LEFT JOIN companies c ON c.domain = x.d AND c.fetched_at > now() - interval '30 days'"""


def ensure_checked(domains: list[str], deadline: float) -> dict[str, str]:
    """Check the domains that nothing proves yet (no homepage, no fresh DNS result), in turn until `deadline`
    (time.monotonic()), and store each result. Free, disposable and typo domains are skipped. {domain: status} for the
    domains checked now. Never raises; does nothing with DOMAIN_CHECK off."""
    out: dict[str, str] = {}
    ds = list(dict.fromkeys(d for d in (x.strip().lower() for x in domains or []) if d))
    ds = [d for d in ds if not is_free_mail(d) and not is_disposable(d) and not typo_of_free_mail(d)]
    if not ds or not settings.domain_check:
        return out
    try:
        from app.db import conn

        with conn() as c:
            rows = c.execute(PROOF_SQL, (ds,)).fetchall()
        for d, status, at, source, error, age_min in rows:
            if domain_proof(source, error, status, at) != "unknown":
                continue
            if status == "error" and age_min is not None and float(age_min) < DNS_RETRY_MIN:
                continue
            if time.monotonic() >= deadline:
                break
            st = dns_status(d, deadline)
            out[d] = st
            with conn() as c:
                c.execute("""INSERT INTO domain_dns(domain, status, checked_at) VALUES (%s, %s, now())
                             ON CONFLICT (domain) DO UPDATE SET status = EXCLUDED.status, checked_at = now()""", (d, st))
                c.commit()
    except Exception as e:
        log.warning("domain check failed for %s: %s", ", ".join(ds), e)
    return out
