"""Security primitives: password hashing, JWT (HS256), TOTP, WebAuthn/passkey.

Only the Python standard library is required so the platform always boots.
For production passkey deployments install the optional ``webauthn`` extra to
enable full attestation/assertion verification (see README).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from typing import Any

from . import db
from .config import settings

PBKDF2_ROUNDS = 180_000


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT (HS256)
# --------------------------------------------------------------------------- #
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def jwt_encode(payload: dict, ttl: int | None = None, token_type: str = "access") -> str:
    ttl = ttl if ttl is not None else settings.access_token_ttl
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + ttl, "typ": token_type}
    head = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    data = _b64e(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(settings.secret_key.encode(), f"{head}.{data}".encode(), hashlib.sha256).digest())
    return f"{head}.{data}.{sig}"


def jwt_decode(token: str, expected_type: str | None = None) -> dict:
    try:
        head, data, sig = token.split(".")
        expected = _b64e(hmac.new(
            settings.secret_key.encode(), f"{head}.{data}".encode(), hashlib.sha256
        ).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        payload = json.loads(_b64d(data))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        if expected_type and payload.get("typ") != expected_type:
            raise ValueError("wrong token type")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid token: {exc}") from exc


def sign_user_token(user: dict, token_type: str = "access", ttl: int | None = None) -> str:
    return jwt_encode(
        {"sub": str(user["id"]), "username": user["username"], "provider": user.get("provider") or "local"},
        ttl=ttl,
        token_type=token_type,
    )


# --------------------------------------------------------------------------- #
# TOTP / OTP (RFC 6238)
# --------------------------------------------------------------------------- #
def new_otp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, timestamp: float | None = None, interval: int = 30, digits: int = 6) -> str:
    timestamp = time.time() if timestamp is None else timestamp
    counter = int(timestamp // interval)
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not code or not code.isdigit():
        return False
    now = time.time()
    for shift in range(-window, window + 1):
        if hmac.compare_digest(totp_code(secret, now + shift * 30), code.strip()):
            return True
    return False


def otpauth_uri(secret: str, label: str, issuer: str | None = None) -> str:
    from urllib.parse import quote
    issuer = issuer or settings.passkey_rp_name
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(label)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


# --------------------------------------------------------------------------- #
# Challenges (shared by OTP enrollment, passkey register / authenticate, SSO)
# --------------------------------------------------------------------------- #
def create_challenge(kind: str, user_id: int | None = None, payload: dict | None = None,
                     ttl: int = 300) -> str:
    challenge = secrets.token_urlsafe(32)
    db.insert("mfa_challenges", {
        "user_id": user_id,
        "kind": kind,
        "challenge": challenge,
        "payload": payload or {},
        "expires_at": int(time.time()) + ttl,
        "created_at": db.now(),
    })
    return challenge


def consume_challenge(kind: str, challenge: str, user_id: int | None = None) -> dict | None:
    row = db.q1(
        "SELECT * FROM mfa_challenges WHERE kind=? AND challenge=? AND consumed=0 AND expires_at>?",
        (kind, challenge, int(time.time())),
    )
    if not row or (user_id is not None and row["user_id"] not in (None, user_id)):
        return None
    db.update("mfa_challenges", row["id"], {"consumed": 1})
    return db.loads(row, "payload") or {}


def random_state() -> str:
    return secrets.token_urlsafe(24)


# --------------------------------------------------------------------------- #
# Passkey / WebAuthn options
# --------------------------------------------------------------------------- #
def passkey_registration_options(user: dict, challenge: str) -> dict:
    return {
        "challenge": challenge,
        "rp": {"id": settings.passkey_rp_id, "name": settings.passkey_rp_name},
        "user": {
            "id": _b64e(str(user["id"]).encode()),
            "name": user["username"],
            "displayName": user.get("display_name") or user["username"],
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},    # ES256
            {"type": "public-key", "alg": -257},  # RS256
        ],
        "authenticatorSelection": {
            "residentKey": "preferred",
            "userVerification": "preferred",
        },
        "timeout": 60000,
        "attestation": "none",
        "excludeCredentials": [
            {"type": "public-key", "id": c.get("id")}
            for c in (db.loads(user, "passkeys") or {}).get("passkeys", [])
        ],
    }


def passkey_authentication_options(challenge: str, user: dict | None = None) -> dict:
    allow = []
    if user:
        allow = [
            {"type": "public-key", "id": c.get("id")}
            for c in (db.loads(user, "passkeys") or {}).get("passkeys", [])
        ]
    return {
        "challenge": challenge,
        "rpId": settings.passkey_rp_id,
        "timeout": 60000,
        "userVerification": "preferred",
        "allowCredentials": allow,
    }


def parse_client_data(client_data_b64: str) -> dict:
    try:
        return json.loads(_b64d(client_data_b64))
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# MFA policy
# --------------------------------------------------------------------------- #
DEFAULT_MFA_POLICY: dict[str, Any] = {
    "required": settings.mfa_required,
    "methods": settings.mfa_methods,
    "enforced_roles": settings.mfa_enforced_roles,
    "enforced_users": settings.mfa_enforced_users,
    "otp": True,
    "passkey": True,
}


def mfa_policy() -> dict:
    row = db.q1("SELECT value FROM settings WHERE key='mfa_policy'")
    if row:
        try:
            return {**DEFAULT_MFA_POLICY, **json.loads(row["value"])}
        except (ValueError, TypeError):
            pass
    return dict(DEFAULT_MFA_POLICY)


def save_mfa_policy(policy: dict) -> dict:
    merged = {**DEFAULT_MFA_POLICY, **policy}
    db.run(
        "INSERT INTO settings(key,value,updated_at) VALUES('mfa_policy',?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (db.dumps(merged), db.now()),
    )
    return merged


def mfa_required_for(user: dict, role_codes: list[str]) -> bool:
    p = mfa_policy()
    if bool(p.get("required")):
        return True
    if user["username"] in (p.get("enforced_users") or []):
        return True
    if any(r in (p.get("enforced_roles") or []) for r in role_codes):
        return True
    for rid in (db.loads(user, "role_ids") or {}).get("role_ids", []):
        role = db.q1("SELECT mfa_required FROM roles WHERE id=?", (rid,))
        if role and role["mfa_required"]:
            return True
    return False


def available_mfa_methods(user: dict) -> list[str]:
    methods = []
    p = mfa_policy()
    if p.get("otp", True) and user.get("otp_enabled"):
        methods.append("otp")
    if p.get("passkey", True) and user.get("passkey_enabled"):
        methods.append("passkey")
    return methods
