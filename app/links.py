"""Signed links for emails: one tap from the inbox, no login, nothing guessable.

sign("outcome", 42) -> a short HMAC token; check("outcome", 42, token) verifies it. The key is LINK_SECRET, else derived
from ADMIN_TOKEN (then WIDGET_SIGNING_SECRET); with neither set no link verifies and the features that need one say so.
Links open a page with a button rather than acting on GET: mail scanners open every link in a message, a person presses
the button.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

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
    good = sign(kind, value)
    return bool(good and token) and hmac.compare_digest(good, str(token))


def base_url() -> str:
    """Where this service is reachable from the recipient's inbox (PUBLIC_BASE_URL)."""
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        log.warning("PUBLIC_BASE_URL is not set; email links point at http://localhost:8080")
        base = "http://localhost:8080"
    return base
