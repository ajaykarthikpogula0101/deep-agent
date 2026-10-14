"""Signed links for emails: one tap from the inbox, no login, nothing guessable.

sign("outcome", 42) -> a short HMAC token; check("outcome", 42, token) verifies it. The key is LINK_SECRET, else derived
from ADMIN_TOKEN (then WIDGET_SIGNING_SECRET); with neither set no link verifies and the features that need one say so.
Links open a page with a button rather than acting on GET: mail scanners open every link in a message, a person presses
the button.

public_problem() says, in one sentence, why PUBLIC_BASE_URL cannot be opened from a phone (unset, not http(s), localhost
or a private address); the startup log and Console -> Emails show it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
from urllib.parse import urlsplit

from app.config import settings

log = logging.getLogger("links")


def _key() -> bytes:
    secret = settings.link_secret or settings.admin_token or settings.widget_signing_secret
    return hashlib.sha256(("deep-links:" + secret).encode()).digest() if secret else b""


def enabled() -> bool:
    return bool(_key())


def sign(kind: str, value: str | int) -> str:
    key = _key()
    if not key:
        return ""
    mac = hmac.new(key, f"{kind}:{str(value).strip().lower()}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:16]).decode().rstrip("=")


def check(kind: str, value: str | int, token: str | None) -> bool:
    """Never raises: a non-ASCII or oversized token is simply wrong (compare_digest on str raises for non-ASCII)."""
    good = sign(kind, value)
    t = str(token or "")
    if not good or not t or len(t) > 128:
        return False
    return hmac.compare_digest(good.encode(), t.encode())


def base_url() -> str:
    """Where this service is reachable from the recipient's inbox (PUBLIC_BASE_URL)."""
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        log.warning("PUBLIC_BASE_URL is not set; email links point at http://localhost:8080")
        base = "http://localhost:8080"
    return base


_LOCAL_HOSTS = {"localhost", "0.0.0.0", "::1", "host.docker.internal"}
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal")


def _not_public(host: str) -> bool:
    h = host.strip("[]").lower()
    if h in _LOCAL_HOSTS or h.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        return not ipaddress.ip_address(h).is_global
    except ValueError:  # a host name
        return False


def public_problem() -> str:
    """'' when PUBLIC_BASE_URL can be opened from a phone or another computer, else one sentence saying why not."""
    raw = (settings.public_base_url or "").strip()
    if not raw:
        return "PUBLIC_BASE_URL is not set"
    try:
        u = urlsplit(raw)
        host = u.hostname or ""
    except ValueError:
        return f"PUBLIC_BASE_URL ({raw}) is not an http(s) URL"
    if u.scheme not in ("http", "https") or not host:
        return f"PUBLIC_BASE_URL ({raw}) is not an http(s) URL"
    if _not_public(host):
        return f"PUBLIC_BASE_URL points at {host}, which a phone or another computer cannot open"
    return ""


def public_ok() -> bool:
    return not public_problem()


def plain_http() -> bool:
    """Public but plain http: the links open, but their tokens travel unencrypted."""
    return public_ok() and urlsplit(settings.public_base_url.strip()).scheme == "http"
