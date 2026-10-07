"""Who is talking to the widget, when it runs inside an application where people are signed in.

Two token formats are accepted in the X-Visitor-Token header, both optional (no token = anonymous visitor):

1. HMAC token minted by the host application's backend with WIDGET_SIGNING_SECRET:
       v1.<base64url(json)>.<hex hmac-sha256>
   json = {"sub": "user id", "name": "...", "email": "...", "exp": unix seconds}
   Any backend can mint it in three lines; see docs/WIDGET.md for Node and Python snippets.

2. Clerk session JWT (ChampSet): RS256, verified against {CLERK_JWT_ISSUER_DOMAIN}/.well-known/jwks.json.
   The default Clerk session token carries only `sub`; name and email arrive if the JWT template adds them
   (claims `name`, `email`, or `first_name`/`last_name`), otherwise the widget's user-name / user-email hints
   are used for prefill (unverified, marked as such).

verify() never raises: a bad token means an anonymous visitor, and the reason is logged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any

from app.config import settings

log = logging.getLogger("identity")

_jwks_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
JWKS_TTL = 3600


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------- HMAC tokens
def mint(sub: str, name: str | None = None, email: str | None = None, ttl_seconds: int = 3600,
         secret: str | None = None) -> str:
    """For the host app's backend (and the demo page). Never call this from browser code."""
    secret = secret if secret is not None else settings.widget_signing_secret
    if not secret:
        raise ValueError("WIDGET_SIGNING_SECRET is not set")
    payload = {"sub": str(sub)[:200], "exp": int(time.time()) + int(ttl_seconds)}
    if name:
        payload["name"] = str(name)[:120]
    if email:
        payload["email"] = str(email)[:200]
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"v1.{body}.{sig}"


def _verify_hmac(token: str, secret: str) -> dict[str, Any] | None:
    try:
        _, body, sig = token.split(".", 2)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        log.info("widget token: bad signature")
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("sub"):
        return None
    if int(payload.get("exp", 0)) < time.time():
        log.info("widget token: expired")
        return None
    return {"sub": str(payload["sub"]), "name": payload.get("name"), "email": payload.get("email"), "via": "hmac"}


# ---------------------------------------------------------------- Clerk JWTs
def _jwks(issuer: str):
    import httpx

    now = time.monotonic()
    with _lock:
        hit = _jwks_cache.get(issuer)
        if hit and now - hit[0] < JWKS_TTL:
            return hit[1]
    r = httpx.get(issuer.rstrip("/") + "/.well-known/jwks.json", timeout=5)
    r.raise_for_status()
    keys = r.json()
    with _lock:
        _jwks_cache[issuer] = (now, keys)
    return keys


def _verify_clerk(token: str, issuer: str) -> dict[str, Any] | None:
    try:
        import jwt
        from jwt import PyJWK

        header = jwt.get_unverified_header(token)
        keys = _jwks(issuer).get("keys", [])
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if key is None:
            log.info("clerk token: unknown kid")
            return None
        claims = jwt.decode(token, PyJWK(key).key, algorithms=["RS256"], issuer=issuer.rstrip("/"),
                            options={"require": ["exp", "sub"], "verify_aud": False}, leeway=10)
    except Exception as e:  # expired, bad signature, wrong issuer, JWKS unreachable
        log.info("clerk token rejected: %s", e)
        return None
    name = claims.get("name") or " ".join(p for p in (claims.get("first_name"), claims.get("last_name")) if p) or None
    email = claims.get("email") or claims.get("email_address") or None
    return {"sub": str(claims["sub"]), "name": name, "email": email, "via": "clerk"}


# ---------------------------------------------------------------- entry point
def verify(token: str | None) -> dict[str, Any] | None:
    """{"sub","name","email","via"} for a valid token, else None. Never raises."""
    token = (token or "").strip()
    if not token:
        return None
    try:
        if token.startswith("v1.") and settings.widget_signing_secret:
            return _verify_hmac(token, settings.widget_signing_secret)
        if token.count(".") == 2 and settings.clerk_jwt_issuer_domain:
            return _verify_clerk(token, settings.clerk_jwt_issuer_domain)
    except Exception as e:
        log.warning("identity check failed: %s", e)
    return None


def describe(identity: dict[str, Any] | None, hint_name: str | None = None, hint_email: str | None = None) -> dict[str, Any]:
    """What the widget may show and what the model may rely on. Hints are unverified client attributes."""
    if not identity:
        return {"signed_in": False, "name": (hint_name or "")[:120] or None, "email": (hint_email or "")[:200] or None,
                "verified": False}
    return {"signed_in": True, "sub": identity["sub"], "name": identity.get("name") or (hint_name or "")[:120] or None,
            "email": identity.get("email") or (hint_email or "")[:200] or None,
            "verified": bool(identity.get("email")), "via": identity.get("via")}
