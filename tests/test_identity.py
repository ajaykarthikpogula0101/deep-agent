"""Signed-in visitors: HMAC tokens minted by a host app, Clerk JWTs, and what the model may rely on."""
from __future__ import annotations

import json
import time

import pytest

from app import identity
from app.chat import visitor_typed

SECRET = "unit-test-secret"


def test_hmac_token_round_trip_and_tampering(monkeypatch):
    monkeypatch.setattr(identity.settings, "widget_signing_secret", SECRET)
    tok = identity.mint("user_42", "Ada Lovelace", "ada@lovelace.org", ttl_seconds=60)
    who = identity.verify(tok)
    assert who == {"sub": "user_42", "name": "Ada Lovelace", "email": "ada@lovelace.org", "via": "hmac"}
    head, body, sig = tok.split(".")
    assert identity.verify(f"{head}.{body}.{'0' * len(sig)}") is None          # bad signature
    forged = identity.mint("user_42", "Ada", "ceo@lovelace.org", secret="other-secret")
    assert identity.verify(forged) is None                                      # wrong secret
    assert identity.verify("") is None and identity.verify("garbage") is None


def test_hmac_token_expires(monkeypatch):
    monkeypatch.setattr(identity.settings, "widget_signing_secret", SECRET)
    tok = identity.mint("u", ttl_seconds=-1)
    assert identity.verify(tok) is None


def test_no_secret_means_anonymous(monkeypatch):
    monkeypatch.setattr(identity.settings, "widget_signing_secret", "")
    monkeypatch.setattr(identity.settings, "clerk_jwt_issuer_domain", "")
    tok = identity.mint("u", secret=SECRET)
    assert identity.verify(tok) is None
    with pytest.raises(ValueError):
        identity.mint("u")


def test_clerk_jwt_is_verified_against_the_issuer_jwks(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    issuer = "https://example.clerk.accounts.dev"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "k1"
    monkeypatch.setattr(identity, "_jwks", lambda _issuer: {"keys": [jwk]})
    monkeypatch.setattr(identity.settings, "clerk_jwt_issuer_domain", issuer)
    monkeypatch.setattr(identity.settings, "widget_signing_secret", "")

    good = jwt.encode({"sub": "user_abc", "iss": issuer, "exp": int(time.time()) + 60, "email": "ada@lovelace.org", "first_name": "Ada", "last_name": "Lovelace"},
                      pem, algorithm="RS256", headers={"kid": "k1"})
    assert identity.verify(good) == {"sub": "user_abc", "name": "Ada Lovelace", "email": "ada@lovelace.org", "via": "clerk"}
    expired = jwt.encode({"sub": "user_abc", "iss": issuer, "exp": int(time.time()) - 60}, pem, algorithm="RS256", headers={"kid": "k1"})
    assert identity.verify(expired) is None
    wrong_issuer = jwt.encode({"sub": "user_abc", "iss": "https://evil.example", "exp": int(time.time()) + 60}, pem, algorithm="RS256", headers={"kid": "k1"})
    assert identity.verify(wrong_issuer) is None
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    forged = jwt.encode({"sub": "user_abc", "iss": issuer, "exp": int(time.time()) + 60}, other_pem, algorithm="RS256", headers={"kid": "k1"})
    assert identity.verify(forged) is None


def test_describe_marks_hints_as_unverified():
    assert identity.describe(None, "Ada", "ada@lovelace.org") == {"signed_in": False, "name": "Ada", "email": "ada@lovelace.org", "verified": False}
    d = identity.describe({"sub": "u1", "name": None, "email": None, "via": "clerk"}, "Ada", "ada@lovelace.org")
    assert d["signed_in"] and d["name"] == "Ada" and d["email"] == "ada@lovelace.org" and d["verified"] is False
    v = identity.describe({"sub": "u1", "name": "Ada", "email": "ada@lovelace.org", "via": "hmac"})
    assert v["verified"] is True


def test_signed_in_email_may_be_booked_without_being_typed():
    convo = [{"role": "user", "content": "I'd like the discovery call, about EU fintech"}]
    assert not visitor_typed("ada@lovelace.org", convo)
    assert visitor_typed("ada@lovelace.org", convo, known_email="Ada@Lovelace.org")
    assert not visitor_typed("someone@else.org", convo, known_email="ada@lovelace.org")
