"""Authentication: local login, MFA (TOTP OTP + WebAuthn passkey), SSO, profile."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .. import db, deps, security
from ..config import settings
from ..services import sso

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginIn(BaseModel):
    username: str = Field(..., examples=["admin"])
    password: str = Field(..., examples=["admin123"])
    otp_code: str | None = None


class MfaVerifyIn(BaseModel):
    mfa_token: str
    method: str = Field(..., description="otp | passkey")
    code: str | None = None
    challenge: str | None = None
    credential: dict | None = None


class OtpEnableIn(BaseModel):
    secret: str
    code: str


class OtpDisableIn(BaseModel):
    code: str | None = None
    password: str | None = None


class PasskeyRegisterIn(BaseModel):
    challenge: str
    credential: dict


class PasskeyAuthenticateOptionsIn(BaseModel):
    username: str | None = None


class PasskeyVerifyIn(BaseModel):
    challenge: str
    credential: dict
    username: str | None = None
    mfa_token: str | None = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class SsoCallbackIn(BaseModel):
    state: str
    code: str = "demo-code"


class MfaPolicyIn(BaseModel):
    required: bool | None = None
    methods: list[str] | None = None
    enforced_roles: list[str] | None = None
    enforced_users: list[str] | None = None
    otp: bool | None = None
    passkey: bool | None = None


def _public_user(user: dict) -> dict:
    return {k: v for k, v in user.items()
            if k not in {"password_hash", "otp_secret", "passkeys"}} | {
        "otp_enabled": bool(user.get("otp_enabled")),
        "passkey_enabled": bool(user.get("passkey_enabled")),
        "passkey_count": len((deps._load_user(user["id"]) or {}).get("passkeys") or []),
    }


def _login_payload(user: dict) -> dict:
    full = deps._load_user(user["id"]) or user
    role_codes = full.get("role_codes") or []
    if security.mfa_required_for(full, role_codes):
        methods = security.available_mfa_methods(full)
        payload: dict[str, Any] = {
            "mfa_required": True,
            "mfa_token": security.sign_user_token(full, "mfa", settings.mfa_token_ttl),
            "methods": methods,
            "enrollment_required": len(methods) == 0,
        }
        if not methods:
            payload["enroll_token"] = security.sign_user_token(full, "enroll", settings.mfa_token_ttl)
            payload["message"] = "MFA is required but no factor is enrolled. Please enroll OTP or a passkey."
        return payload
    return {
        "access_token": security.sign_user_token(full),
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl,
        "user": _public_user(full),
    }


def _user_from_token(token: str, allowed: set[str]) -> dict:
    try:
        payload = security.jwt_decode(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if payload.get("typ") not in allowed:
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = deps._load_user(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def any_user(request: Request) -> dict:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _user_from_token(auth.split(" ", 1)[1].strip(), {"access", "enroll", "mfa"})


@router.post("/login", summary="Local login (returns access token or MFA challenge)")
def login(body: LoginIn, request: Request):
    row = db.q1("SELECT * FROM users WHERE username=? OR email=?", (body.username, body.username))
    if not row or not security.verify_password(body.password, row.get("password_hash")):
        deps.audit(body.username, "auth.login.failed", "session", {"reason": "bad credentials"},
                   level="warn", request=request)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="User is disabled")
    user = deps._load_user(row["id"]) or row
    db.update("users", row["id"], {"last_login_at": db.now()})
    deps.audit(row["username"], "auth.login", "session", {"method": "local"}, request=request)
    payload = _login_payload(user)
    if body.otp_code and payload.get("mfa_required"):
        if user.get("otp_enabled") and security.verify_totp(user.get("otp_secret") or "", body.otp_code):
            return {"access_token": security.sign_user_token(user), "token_type": "bearer",
                    "expires_in": settings.access_token_ttl, "user": _public_user(user)}
    return payload


@router.post("/mfa/verify", summary="Complete MFA and obtain an access token")
def mfa_verify(body: MfaVerifyIn, request: Request):
    user = _user_from_token(body.mfa_token, {"mfa"})
    if body.method == "otp":
        if not user.get("otp_enabled") or not security.verify_totp(user.get("otp_secret") or "", body.code or ""):
            raise HTTPException(status_code=401, detail="Invalid OTP code")
    elif body.method == "passkey":
        if not body.challenge or not body.credential:
            raise HTTPException(status_code=400, detail="challenge and credential are required")
        if not security.consume_challenge("passkey_auth", body.challenge, user["id"]):
            raise HTTPException(status_code=401, detail="Invalid or expired passkey challenge")
        client = security.parse_client_data((body.credential.get("response") or {}).get("clientDataJSON") or "")
        if client.get("challenge") != body.challenge:
            raise HTTPException(status_code=401, detail="Passkey challenge mismatch")
        if str(body.credential.get("id")) not in [str(p.get("id")) for p in (user.get("passkeys") or [])]:
            raise HTTPException(status_code=401, detail="Unknown credential")
    else:
        raise HTTPException(status_code=400, detail="Unsupported MFA method")
    deps.audit(user["username"], "auth.mfa.verify", "session", {"method": body.method}, request=request)
    return {"access_token": security.sign_user_token(user), "token_type": "bearer",
            "expires_in": settings.access_token_ttl, "user": _public_user(user)}


@router.get("/me", summary="Current user profile, roles and permissions")
def me(user: dict = Depends(deps.get_current_user)):
    return _public_user(user)


class ProfileUpdateIn(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)


@router.put("/me", summary="Update my own profile (display name / email)")
def update_me(body: ProfileUpdateIn, user: dict = Depends(deps.get_current_user),
              request: Request = None):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    patch["updated_at"] = db.now()
    db.update("users", user["id"], patch)
    deps.audit(user["username"], "auth.profile.update", "user", list(patch), request=request)
    return _public_user(deps._load_user(user["id"]) or user)


@router.get("/me/overview", summary="Personal center counters for the current user")
def me_overview(user: dict = Depends(deps.get_current_user)):
    from ..services import notify
    name = user["username"]
    pending_tasks = int(db.scalar(
        "SELECT COUNT(*) FROM flow_tasks WHERE assignee=? AND status='pending'", (name,)) or 0)
    done_tasks = int(db.scalar(
        "SELECT COUNT(*) FROM flow_tasks WHERE assignee=? AND status!='pending'", (name,)) or 0)
    instances_running = int(db.scalar(
        "SELECT COUNT(*) FROM workflow_instances WHERE started_by=? AND status='running'",
        (name,)) or 0)
    instances_total = int(db.scalar(
        "SELECT COUNT(*) FROM workflow_instances WHERE started_by=?", (name,)) or 0)
    submissions = int(db.scalar(
        "SELECT COUNT(*) FROM form_submissions WHERE submitted_by=?", (name,)) or 0)
    groups = [dict(r) for r in db.q(
        "SELECT code, name FROM user_groups WHERE enabled=1 AND members LIKE ? ORDER BY id",
        (f'%\"{name}\"%',))]
    delegations_out = [dict(r) for r in db.q(
        "SELECT principal, agent, starts_at, ends_at FROM flow_delegations "
        "WHERE principal=? AND enabled=1", (name,))]
    delegations_in = [dict(r) for r in db.q(
        "SELECT principal, agent, starts_at, ends_at FROM flow_delegations "
        "WHERE agent=? AND enabled=1", (name,))]
    return {
        "profile": _public_user(user),
        "tasks": {"pending": pending_tasks, "done": done_tasks},
        "instances": {"running": instances_running, "total": instances_total},
        "submissions": submissions,
        "notifications_unread": notify.unread_count(name),
        "groups": groups,
        "delegations": {"outgoing": delegations_out, "incoming": delegations_in},
        "data_scope": user.get("data_scope"),
    }


@router.post("/logout", summary="Logout (client should discard the token)")
def logout(user: dict = Depends(deps.get_current_user), request: Request = None):
    deps.audit(user["username"], "auth.logout", "session", {}, request=request)
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: dict = Depends(deps.get_current_user),
                    request: Request = None):
    row = db.q1("SELECT password_hash FROM users WHERE id=?", (user["id"],))
    if not security.verify_password(body.old_password, (row or {}).get("password_hash")):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    db.update("users", user["id"], {"password_hash": security.hash_password(body.new_password),
                                    "updated_at": db.now()})
    deps.audit(user["username"], "auth.password.change", "user", {}, request=request)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# OTP / TOTP
# --------------------------------------------------------------------------- #
@router.post("/otp/setup", summary="Generate a TOTP secret and provisioning URI")
def otp_setup(user: dict = Depends(any_user)):
    secret = security.new_otp_secret()
    return {"secret": secret,
            "otpauth_uri": security.otpauth_uri(secret, user["username"]),
            "issuer": settings.passkey_rp_name,
            "algorithm": "SHA1", "digits": 6, "period": 30,
            "note": "Scan the otpauth URI with an authenticator app, then confirm with a 6-digit code."}


@router.post("/otp/enable")
def otp_enable(body: OtpEnableIn, user: dict = Depends(any_user), request: Request = None):
    if not security.verify_totp(body.secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid OTP code")
    db.update("users", user["id"], {"otp_secret": body.secret, "otp_enabled": 1,
                                    "updated_at": db.now()})
    deps.audit(user["username"], "auth.otp.enable", "user", {}, request=request)
    return {"ok": True, "otp_enabled": True}


@router.post("/otp/disable")
def otp_disable(body: OtpDisableIn, user: dict = Depends(deps.get_current_user),
                request: Request = None):
    if not (user.get("otp_enabled") and security.verify_totp(user.get("otp_secret") or "", body.code or "")) \
            and not security.verify_password(body.password or "", (db.q1(
                "SELECT password_hash FROM users WHERE id=?", (user["id"],)) or {}).get("password_hash")):
        raise HTTPException(status_code=400, detail="A valid OTP code or password is required")
    db.update("users", user["id"], {"otp_enabled": 0, "otp_secret": None, "updated_at": db.now()})
    deps.audit(user["username"], "auth.otp.disable", "user", {}, request=request)
    return {"ok": True, "otp_enabled": False}


# --------------------------------------------------------------------------- #
# Passkey / WebAuthn
# --------------------------------------------------------------------------- #
@router.post("/passkey/register/options")
def passkey_register_options(user: dict = Depends(any_user)):
    challenge = security.create_challenge("passkey_register", user["id"], {}, ttl=180)
    return {"options": security.passkey_registration_options(user, challenge),
            "challenge": challenge,
            "note": "Call navigator.credentials.create() with publicKey options (base64url fields "
                    "must be decoded to ArrayBuffer on the client)." }


@router.post("/passkey/register/verify")
def passkey_register_verify(body: PasskeyRegisterIn, user: dict = Depends(any_user),
                            request: Request = None):
    if not security.consume_challenge("passkey_register", body.challenge, user["id"]):
        raise HTTPException(status_code=400, detail="Invalid or expired challenge")
    client = security.parse_client_data((body.credential.get("response") or {}).get("clientDataJSON") or "")
    if client.get("challenge") != body.challenge:
        raise HTTPException(status_code=400, detail="Challenge mismatch")
    att = (body.credential.get("response") or {}).get("attestationObject") or ""
    passkeys = list(user.get("passkeys") or [])
    if any(str(p.get("id")) == str(body.credential.get("id")) for p in passkeys):
        raise HTTPException(status_code=400, detail="Credential already registered")
    passkeys.append({
        "id": body.credential.get("id"), "type": body.credential.get("type") or "public-key",
        "public_key": att[:128], "sign_count": 0, "created_at": db.now(),
        "transports": (body.credential.get("response") or {}).get("transports") or [],
        "attestation_verified": False,
    })
    db.update("users", user["id"], {"passkeys": passkeys, "passkey_enabled": 1,
                                    "updated_at": db.now()})
    deps.audit(user["username"], "auth.passkey.register", "user", {}, request=request)
    return {"ok": True, "passkey_enabled": True, "credentials": len(passkeys),
            "note": "Demo-grade registration: install the `webauthn` extra for full attestation verification."}


@router.get("/passkey/credentials")
def passkey_credentials(user: dict = Depends(deps.get_current_user)):
    return {"credentials": [{k: v for k, v in p.items() if k != "public_key"}
                            for p in (user.get("passkeys") or [])]}


@router.delete("/passkey/credentials/{credential_id}")
def passkey_delete(credential_id: str, user: dict = Depends(deps.get_current_user)):
    kept = [p for p in (user.get("passkeys") or []) if str(p.get("id")) != credential_id]
    db.update("users", user["id"], {"passkeys": kept, "passkey_enabled": int(bool(kept)),
                                    "updated_at": db.now()})
    return {"ok": True, "credentials": len(kept)}


@router.post("/passkey/authenticate/options")
def passkey_auth_options(body: PasskeyAuthenticateOptionsIn):
    user = None
    if body.username:
        row = db.q1("SELECT * FROM users WHERE username=?", (body.username,))
        if row:
            user = deps._load_user(row["id"])
    challenge = security.create_challenge("passkey_auth", (user or {}).get("id"), {}, ttl=180)
    return {"options": security.passkey_authentication_options(challenge, user),
            "challenge": challenge}


@router.post("/passkey/authenticate/verify")
def passkey_auth_verify(body: PasskeyVerifyIn, request: Request):
    if body.mfa_token:
        user = _user_from_token(body.mfa_token, {"mfa"})
    elif body.username:
        row = db.q1("SELECT * FROM users WHERE username=?", (body.username,))
        if not row:
            raise HTTPException(status_code=401, detail="User not found")
        user = deps._load_user(row["id"]) or row
    else:
        raise HTTPException(status_code=400, detail="username or mfa_token is required")
    if not security.consume_challenge("passkey_auth", body.challenge, user["id"]):
        raise HTTPException(status_code=401, detail="Invalid or expired challenge")
    client = security.parse_client_data((body.credential.get("response") or {}).get("clientDataJSON") or "")
    if client.get("challenge") != body.challenge:
        raise HTTPException(status_code=401, detail="Challenge mismatch")
    if str(body.credential.get("id")) not in [str(p.get("id")) for p in (user.get("passkeys") or [])]:
        raise HTTPException(status_code=401, detail="Unknown credential")
    deps.audit(user["username"], "auth.login", "session", {"method": "passkey"}, request=request)
    return {"access_token": security.sign_user_token(user), "token_type": "bearer",
            "expires_in": settings.access_token_ttl, "user": _public_user(user)}


# --------------------------------------------------------------------------- #
# MFA policy (role / user based enforcement)
# --------------------------------------------------------------------------- #
@router.get("/mfa-policy", summary="Read the global / role / user MFA policy")
def get_mfa_policy(_user: dict = Depends(deps.require("auth:config"))):
    return security.mfa_policy()


@router.put("/mfa-policy", summary="Configure MFA enforcement by role or user")
def put_mfa_policy(body: MfaPolicyIn, user: dict = Depends(deps.require("auth:config")),
                   request: Request = None):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    policy = security.save_mfa_policy(patch)
    deps.audit(user["username"], "auth.mfa.policy.update", "settings", patch, request=request)
    return policy


# --------------------------------------------------------------------------- #
# SSO
# --------------------------------------------------------------------------- #
@router.get("/providers", summary="Public list of enabled SSO providers")
def public_providers():
    rows = db.q("SELECT code,type,name,enabled,config FROM auth_providers WHERE enabled=1 ORDER BY sort_order")
    return {"providers": [{"code": r["code"], "type": r["type"], "name": r["name"],
                           "enabled": bool(r["enabled"]),
                           "demo": not sso.is_configured(r)} for r in rows]}


@router.get("/sso/providers", summary="All SSO providers with configuration (admin)")
def all_providers(_user: dict = Depends(deps.require("auth:config"))):
    rows = db.q("SELECT * FROM auth_providers ORDER BY sort_order")
    return {"providers": [db.loads({**r, "enabled": bool(r["enabled"])}, "config") for r in rows],
            "meta": sso.PROVIDER_META}


@router.put("/sso/providers/{code}")
def update_provider(code: str, body: dict, user: dict = Depends(deps.require("auth:config")),
                    request: Request = None):
    row = db.q1("SELECT * FROM auth_providers WHERE code=?", (code,))
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    patch: dict[str, Any] = {}
    if "enabled" in body:
        patch["enabled"] = int(bool(body["enabled"]))
    if "config" in body:
        cfg = (db.loads(row, "config") or {}).get("config") or {}
        cfg.update(body["config"] or {})
        patch["config"] = cfg
    patch["updated_at"] = db.now()
    db.update("auth_providers", row["id"], patch)
    deps.audit(user["username"], "auth.sso.provider.update", f"provider:{code}",
               {"enabled": patch.get("enabled")}, request=request)
    return db.loads(db.q1("SELECT * FROM auth_providers WHERE code=?", (code,)), "config")


def _sso_login(provider: dict, identity: dict, request: Request) -> dict:
    user = sso.upsert_identity(identity, provider["code"])
    full = deps._load_user(user["id"]) or user
    deps.audit(full["username"], "auth.login", "session",
               {"method": provider["code"], "demo": identity.get("demo", False)}, request=request)
    return {"access_token": security.sign_user_token(full), "token_type": "bearer",
            "expires_in": settings.access_token_ttl, "user": _public_user(full),
            "demo": identity.get("demo", False)}


@router.get("/sso/{code}/authorize", summary="Build the provider authorize URL")
def sso_authorize(code: str):
    provider = db.q1("SELECT * FROM auth_providers WHERE code=? AND enabled=1", (code,))
    if not provider:
        raise HTTPException(status_code=404, detail="SSO provider not found or disabled")
    state = security.random_state()
    nonce = security.random_state()
    db.insert("sso_states", {"state": state, "provider": code,
                             "redirect_uri": sso.callback_url(code), "nonce": nonce,
                             "created_at": db.now()})
    url = sso.build_authorize_url(db.loads(provider, "config") or provider, state, nonce)
    return {"url": url, "state": state, "provider": code,
            "demo": not sso.is_configured(db.loads(provider, "config") or provider)}


@router.post("/sso/{code}/callback", summary="Demo-mode SSO callback (returns tokens as JSON)")
async def sso_callback_post(code: str, body: SsoCallbackIn, request: Request):
    state = db.q1("SELECT * FROM sso_states WHERE state=? AND provider=?", (body.state, code))
    if not state:
        raise HTTPException(status_code=400, detail="Invalid SSO state")
    provider = db.q1("SELECT * FROM auth_providers WHERE code=?", (code,))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    identity = await sso.exchange(db.loads(provider, "config") or provider,
                                  {"code": body.code}, state)
    db.delete("sso_states", body.state, "state")
    return _sso_login(provider, identity, request)


@router.get("/sso/{code}/callback", summary="Real SSO callback (redirects to frontend)")
async def sso_callback_get(code: str, request: Request, state: str = "", code_value: str = ""):
    params = dict(request.query_params)
    ticket = params.get("code") or params.get("ticket") or code_value
    state_row = db.q1("SELECT * FROM sso_states WHERE state=? AND provider=?",
                      (params.get("state") or state, code))
    provider = db.q1("SELECT * FROM auth_providers WHERE code=?", (code,))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    identity = await sso.exchange(db.loads(provider, "config") or provider,
                                  {"code": ticket}, state_row)
    if state_row:
        db.delete("sso_states", state_row["state"], "state")
    result = _sso_login(provider, identity, request)
    frontend = settings.cors_origins[0].rstrip("/") if settings.cors_origins else "http://localhost:5173"
    return RedirectResponse(
        f"{frontend}/#/sso/callback?token={result['access_token']}&demo={str(result['demo']).lower()}")
