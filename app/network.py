"""Which network is behind a visit: who owns it and what kind it is, checked against the company the visitor typed and
their email domain. Pure functions over a normalised geo dict (tracking.normalise_geo); no I/O, unit-tested offline.

classify(geo)  -> (net_kind, why, mobile)   corporate | consumer | hosting | privacy | coworking | education | government
                                            | unknown | local. `why` names orgs, AS numbers and rules only, never an IP
                                            or a hostname. The type is never guessed: no evidence means 'unknown'.
match(net, company_typed, email_domain, email_kind) -> {match, text}   claim | email | mismatch | other_company | <kind>
label(kind, mobile) -> the host-facing words ('home broadband', 'VPN, relay or security proxy', ...)

KNOWN_ASN and the regexes need curation: add an ASN when a real lookup lands in the wrong kind. Tata Communications
(AS4755) and Verizon Business (AS701) are deliberately absent because they carry many enterprise leased lines.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

KINDS = ("corporate", "consumer", "hosting", "privacy", "coworking", "education", "government", "unknown", "local")

# asn -> (kind, mobile_only)
KNOWN_ASN: dict[int, tuple[str, bool]] = {
    **{a: ("hosting", False) for a in (16509, 14618, 15169, 396982, 8075, 14061, 16276, 24940, 63949, 20473, 31898, 45102,
                                       9009, 60068, 212238)},
    # VPNs, relays and enterprise security gateways (iCloud Private Relay, Cloudflare WARP, Zscaler, Netskope)
    **{a: ("privacy", False) for a in (13335, 36183, 54113, 53813, 62044, 55256, 136787, 209854)},
    **{a: ("consumer", True) for a in (45609, 38266, 55410)},  # Airtel mobile, Vodafone Idea
    # Jio (mobile and JioFiber), Airtel broadband, BSNL, ACT, Hathway, Comcast, AT&T, BT, Deutsche Telekom
    **{a: ("consumer", False) for a in (55836, 24560, 9829, 24309, 18209, 17488, 7922, 7018, 2856, 3320)},
}

PRIVACY_RE = re.compile(r"\bvpn\b|proxy|tor exit|private internet access|nordvpn|surfshark|expressvpn|mullvad|proton ?vpn|"
                        r"zscaler|netskope|private relay", re.I)
HOSTING_RE = re.compile(r"hosting|cloud|data ?cent(er|re)|\bservers?\b|\bvps\b|colo(cation)?\b|datacamp|digitalocean|amazon|"
                        r"\baws\b|azure|linode|ovh|hetzner|vultr|choopa", re.I)
EDU_RE = re.compile(r"university|college|institute of technology|\bschool\b|academy|\.edu\b|\.ac\.[a-z]{2}\b|\biit\b|ernet", re.I)
GOV_RE = re.compile(r"government|ministry|\.gov\b|\.gov\.[a-z]{2}\b|\bnic\.in\b|national informatics", re.I)
# deliberately no 'networks?', bare 'communications', 'internet', 'wireless' or bare 'cable': Palo Alto Networks,
# Juniper Networks and Verizon Communications are buyers, not home broadband
CONSUMER_RE = re.compile(r"broadband|fibernet|fibre|fiber|\bdsl\b|\bisp\b|internet service provider|"
                         r"cable (tv|net|broadband|communications)|cellular|\bmobile\b|\bgprs\b|telecom|telekom|"
                         r"telecommunications?|\bjio\b|airtel|vodafone|\bidea cellular|bsnl|mtnl|hathway|excitel|"
                         r"convergence technologies|tikona|spectra|you broadband|alliance broadband", re.I)
COWORK_RE = re.compile(r"wework|regus|awfis|91springboard|smartworks|innov8|cowork", re.I)
RDNS_DYNAMIC_RE = re.compile(r"\d{1,3}[-.]\d{1,3}[-.]\d{1,3}|dynamic|dyn|pool|dsl|broadband|cust|subscriber", re.I)

_REGEX_ORDER = (("privacy", PRIVACY_RE), ("hosting", HOSTING_RE), ("coworking", COWORK_RE), ("education", EDU_RE),
                ("government", GOV_RE), ("consumer", CONSUMER_RE))
_TYPE_KIND = {"business": "corporate", "isp": "consumer", "hosting": "hosting", "education": "education",
              "government": "government"}

_LEGAL = {"inc", "incorporated", "ltd", "limited", "llc", "llp", "plc", "pvt", "private", "corp", "corporation", "co",
          "company", "gmbh", "ag", "sa", "bv", "nv", "pte", "pty"}
_TLDISH = {"com", "net", "org", "io", "in", "co"}
_SLD2 = {"co.uk", "co.in", "com.au", "co.jp", "ac.in", "ac.uk", "gov.in", "com.sg", "com.br", "net.in", "org.in"}
_SLD2_LABELS = {"co", "com", "net", "org", "ac", "gov", "edu", "ltd", "plc"}  # <label>.<2-letter country>: yahoo.com.au, live.com.mx


# ---------------------------------------------------------------- names and domains
def org_key(name: str | None) -> str:
    """Comparable form of an organisation name: 'Apple.INC' -> 'apple', 'Tech Mahindra Ltd' -> 'tech mahindra'.
    Only trailing legal suffixes (then trailing com/net/...) go; descriptive words stay. The first word is never dropped."""
    t = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split()
    while len(t) > 1 and t[-1] in _LEGAL:
        t.pop()
    while len(t) > 1 and t[-1] in _TLDISH:
        t.pop()
    return " ".join(t)


_LEGAL_TAIL = re.compile(r"[\s,.]+(?:" + "|".join(sorted(_LEGAL, key=len, reverse=True)) + r")\.?[\s,.]*$", re.I)


def clean_org(name: str | None) -> str:
    """Display form: 'Atria Convergence Technologies Pvt. Ltd.' -> 'Atria Convergence Technologies'. ALL-CAPS words longer
    than 3 letters are title-cased; short acronyms (ACT, IBM) stay."""
    s = re.sub(r"\s+", " ", (name or "")).strip()
    while True:
        t = _LEGAL_TAIL.sub("", s)
        if t == s or not t.strip(" ,."):
            break
        s = t
    s = s.strip(" ,")
    if s.isupper():
        s = " ".join(w.title() if len(w) > 3 else w for w in s.split())
    return s


def registrable(domain: str | None) -> str:
    """'mail.infosys.co.in' -> 'infosys.co.in' (two-level suffixes such as co.xx or com.xx, not the full public suffix list)."""
    d = (domain or "").strip().lower().rsplit("@", 1)[-1].strip(".")
    parts = [p for p in d.split(".") if p]
    if len(parts) < 2:
        return ".".join(parts)
    two = ".".join(parts[-2:]) in _SLD2 or (parts[-2] in _SLD2_LABELS and len(parts[-1]) == 2)
    n = 3 if len(parts) >= 3 and two else 2
    return ".".join(parts[-n:])


def domain_root(domain: str | None) -> str:
    """'mail.infosys.co.in' -> 'infosys'."""
    r = registrable(domain)
    return r.split(".")[0] if r else ""


def same_company(a: str | None, b: str | None) -> bool:
    """Two org_key()s name the same company: equal, equal without spaces, or one's words lead the other's and the first
    word has 4+ letters ('tata consultancy' ~ 'tata consultancy services'; 'mahindra' !~ 'tech mahindra')."""
    if not a or not b:
        return False
    if a == b or a.replace(" ", "") == b.replace(" ", ""):
        return True
    short, long_ = sorted((a.split(), b.split()), key=len)
    return long_[:len(short)] == short and len(short[0]) >= 4


# ---------------------------------------------------------------- classification
def _rx_kind(text: str) -> str | None:
    for kind, rx in _REGEX_ORDER:
        if rx.search(text):
            return kind
    return None


def classify(geo: Mapping[str, Any] | None) -> tuple[str, str, bool | None]:
    """(net_kind, why, mobile). The checks run in a fixed order; the first that fires wins."""
    g = geo or {}
    flags = g.get("flags") or {}
    mobile = flags.get("mobile")
    if g.get("status") == "private":
        return "local", "private or loopback address", None
    if flags.get("proxy"):
        return "privacy", "provider flags a VPN, proxy or Tor exit", mobile
    t = str(g.get("type") or "").lower()
    if t in _TYPE_KIND:
        return _TYPE_KIND[t], f"provider type {t}", mobile
    if flags.get("hosting"):
        return "hosting", "provider flags a data centre", mobile
    if mobile:
        return "consumer", "provider flags a mobile network", True
    org, as_org = g.get("org") or "", g.get("as_org") or ""
    if (g.get("org_scope") == "netblock" and org and not same_company(org_key(org), org_key(as_org))
            and not _rx_kind(org)):
        return "corporate", f"netblock registered to {clean_org(org)} on {clean_org(as_org) or 'its carrier'}", mobile
    asn = g.get("asn")
    if isinstance(asn, int) and asn in KNOWN_ASN:
        kind, mobile_only = KNOWN_ASN[asn]
        return kind, f"AS{asn} is a known {kind} network", (True if mobile_only else mobile)
    hay = " ".join(str(g.get(k) or "") for k in ("as_org", "org", "isp", "net_domain"))
    kind = _rx_kind(hay)
    if kind:
        name = clean_org(as_org or org or g.get("isp") or g.get("net_domain") or "")
        return kind, f"{name} matches the {kind} name rule", mobile
    rd = g.get("rdns_domain") or ""
    if (rd and g.get("rdns_dynamic") is False and domain_root(rd) != domain_root(g.get("net_domain"))
            and not _rx_kind(rd)):
        return "corporate", f"reverse DNS names {rd}", mobile
    return "unknown", "no rule matched", mobile


def org_of(geo: Mapping[str, Any], kind: str) -> str | None:
    """The organisation to store as net_org: the netblock holder for a corporate sub-allocation, else the AS owner."""
    g = geo or {}
    if kind == "corporate" and g.get("org") and g.get("org_scope") == "netblock":
        return g["org"]
    return g.get("as_org") or g.get("org") or g.get("isp")


# ---------------------------------------------------------------- matching and wording
_MATCH_TEXT = {
    "local": "local test network; no lookup",
    "claim": "matches the company they typed",
    "email": "matches their email domain",
    "consumer": "home/mobile connection; says nothing about their employer",
    "hosting": "cloud server; often a VPN or company security gateway, says nothing about them",
    "privacy": "VPN, relay or security proxy; says nothing about them",
    "coworking": "coworking space; says nothing about their employer",
    "education": "university network",
    "government": "government network",
    "unknown": "network type unknown",
}


def match(net: Mapping[str, Any], company_typed: str | None, email_domain: str | None, email_kind: str | None) -> dict[str, str]:
    """How the network relates to what the visitor told us. `net` has kind (or net_kind), net_org (or as_org/org) and
    net_domain. A claim only counts on corporate, unknown, education or government networks: 'Reliance' typed on Jio or
    'Microsoft' on Azure proves nothing."""
    kind = net.get("kind") or net.get("net_kind") or "unknown"
    org = net.get("net_org") or net.get("as_org") or net.get("org") or ""
    dom = net.get("net_domain") or ""
    typed = (company_typed or "").strip()
    if kind == "local":
        return {"match": "local", "text": _MATCH_TEXT["local"]}
    if typed and kind in ("corporate", "unknown", "education", "government"):
        if same_company(org_key(typed), org_key(org) or org_key(domain_root(dom))):
            return {"match": "claim", "text": _MATCH_TEXT["claim"]}
    if email_kind == "business" and email_domain and kind not in ("consumer", "privacy", "coworking"):
        if (dom and registrable(email_domain) == registrable(dom)) or \
                (kind != "hosting" and same_company(org_key(domain_root(email_domain)), org_key(org))):
            return {"match": "email", "text": _MATCH_TEXT["email"]}
    shown = clean_org(org) or "an unnamed company"
    if kind == "corporate" and typed:
        return {"match": "mismatch", "text": f"they typed {typed} but the network belongs to {shown}"}
    if kind == "corporate":
        return {"match": "other_company", "text": f"a company network ({shown}); nothing else ties them to it"}
    return {"match": kind, "text": _MATCH_TEXT.get(kind, _MATCH_TEXT["unknown"])}


def label(kind: str | None, mobile: bool | None = None) -> str:
    if kind == "consumer":
        return "mobile network" if mobile else "home broadband"
    return {"corporate": "company network", "hosting": "cloud server", "privacy": "VPN, relay or security proxy",
            "coworking": "coworking space", "education": "university network", "government": "government network",
            "local": "local test network"}.get(kind or "", "network type unknown")


def tz_mismatch(client_tz: str | None, geo_tz: str | None, now: datetime | None = None) -> bool:
    """True when the browser's timezone and the IP's are 2+ hours apart right now (VPN or travel). Unknown names: False."""
    if not client_tz or not geo_tz:
        return False
    from zoneinfo import ZoneInfo

    try:
        now = now or datetime.now(timezone.utc)
        a, b = now.astimezone(ZoneInfo(client_tz)).utcoffset(), now.astimezone(ZoneInfo(geo_tz)).utcoffset()
    except Exception:
        return False
    return a is not None and b is not None and abs(a - b) >= timedelta(hours=2)
