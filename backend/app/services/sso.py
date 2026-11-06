"""Pluggable SSO providers: CAS, OAuth2, OIDC, WeCom (企业微信), DingTalk (钉钉).

When a provider has no real credentials configured it runs in ``demo`` mode:
the full redirect / callback / user-provisioning flow still works end-to-end
with a clearly flagged synthetic identity, so the integration can be exercised
without external accounts.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote, urlencode

import httpx

from .. import db
from ..config import settings

PROVIDER_META = {
    "cas": {"label": "CAS", "fields": ["server_url", "version"]},
    "oauth2": {"label": "OAuth 2.0", "fields": ["client_id", "client_secret", "authorize_url",
                                                "token_url", "userinfo_url", "scope"]},
    "oidc": {"label": "OpenID Connect", "fields": ["issuer", "discovery_url", "client_id",
                                                   "client_secret", "scope"]},
    "wecom": {"label": "WeCom / 企业微信", "fields": ["corp_id", "agent_id", "secret"]},
    "dingtalk": {"label": "DingTalk / 钉钉", "fields": ["app_key", "app_secret"]},
}


def callback_url(code: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}{settings.api_prefix}/auth/sso/{code}/callback"


def _cfg(provider: dict) -> dict:
    cfg = (db.loads(provider, "config") or {}).get("config") or {}
    # environment fallbacks keep .env-only deployments working
    env_map = {
        "cas": {"server_url": settings.cas_server_url, "version": settings.cas_version},
        "oauth2": {"client_id": settings.oauth2_client_id, "client_secret": settings.oauth2_client_secret,
                   "authorize_url": settings.oauth2_authorize_url, "token_url": settings.oauth2_token_url,
                   "userinfo_url": settings.oauth2_userinfo_url},
        "oidc": {"issuer": settings.oidc_issuer, "discovery_url": settings.oidc_discovery_url,
                 "client_id": settings.oidc_client_id, "client_secret": settings.oidc_client_secret},
        "wecom": {"corp_id": settings.wecom_corp_id, "agent_id": settings.wecom_agent_id,
                  "secret": settings.wecom_secret},
        "dingtalk": {"app_key": settings.dingtalk_app_key, "app_secret": settings.dingtalk_app_secret},
    }
    merged = {k: v for k, v in env_map.get(provider["type"], {}).items() if v}
    merged.update({k: v for k, v in cfg.items() if v not in (None, "")})
    return merged


def is_configured(provider: dict) -> bool:
    """True only when the provider has the credentials needed for a real flow."""
    cfg = _cfg(provider)
    ptype = provider.get("type")
    checks = {
        "cas": lambda c: bool(c.get("server_url")),
        "oauth2": lambda c: bool(c.get("client_id") and c.get("token_url")),
        "oidc": lambda c: bool((c.get("issuer") or c.get("discovery_url")) and c.get("client_id")),
        "wecom": lambda c: bool(c.get("corp_id") and c.get("secret")),
        "dingtalk": lambda c: bool(c.get("app_key") and c.get("app_secret")),
    }
    return bool(checks.get(ptype, lambda c: False)(cfg))


def build_authorize_url(provider: dict, state: str, nonce: str = "") -> str:
    cfg = _cfg(provider)
    ptype, cb = provider["type"], callback_url(provider["code"])
    if ptype == "cas":
        server = (cfg.get("server_url") or "https://cas.example.com/cas").rstrip("/")
        service = quote(f"{cb}?state={state}", safe="")
        return f"{server}/login?service={service}"
    if ptype == "oauth2":
        params = {"client_id": cfg.get("client_id", ""), "redirect_uri": cb,
                  "response_type": "code", "scope": cfg.get("scope", "openid profile email"),
                  "state": state}
        return f"{cfg.get('authorize_url', '')}?{urlencode(params)}"
    if ptype == "oidc":
        discovery = cfg.get("discovery_url") or (f"{cfg.get('issuer','').rstrip('/')}"
                                                 "/.well-known/openid-configuration")
        authorize = cfg.get("authorize_url") or discovery.replace(
            "/.well-known/openid-configuration", "/authorize")
        params = {"client_id": cfg.get("client_id", ""), "redirect_uri": cb,
                  "response_type": "code", "scope": cfg.get("scope", "openid profile email"),
                  "state": state, "nonce": nonce}
        return f"{authorize}?{urlencode(params)}"
    if ptype == "wecom":
        params = {"appid": cfg.get("corp_id", ""), "agentid": cfg.get("agent_id", ""),
                  "redirect_uri": cb, "state": state}
        return f"https://open.work.weixin.qq.com/wwopen/sso/qrConnect?{urlencode(params)}"
    if ptype == "dingtalk":
        params = {"client_id": cfg.get("app_key", ""), "response_type": "code",
                  "scope": "openid", "redirect_uri": cb, "state": state, "prompt": "consent"}
        return f"https://login.dingtalk.com/oauth2/auth?{urlencode(params)}"
    return ""


def _demo_identity(provider: dict) -> dict:
    code = provider["code"]
    return {
        "external_id": f"demo:{code}", "username": f"{code}_demo",
        "email": f"{code}.demo@platform.local",
        "display_name": f"{PROVIDER_META.get(provider['type'], {}).get('label', code)} Demo User",
        "avatar": "", "demo": True, "raw": {"mode": "demo", "provider": code},
    }


async def exchange(provider: dict, params: dict, state_row: dict | None = None) -> dict:
    """Exchange an SSO callback into a normalized external identity."""
    cfg = _cfg(provider)
    ptype = provider["type"]
    code_value = params.get("code") or params.get("ticket") or ""
    if not cfg or not code_value:
        return _demo_identity(provider)
    cb = callback_url(provider["code"])
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            if ptype == "cas":
                server = cfg.get("server_url", "").rstrip("/")
                version = str(cfg.get("version") or "3")
                endpoint = "p3/serviceValidate" if version.startswith("3") else "serviceValidate"
                r = await client.get(f"{server}/{endpoint}",
                                     params={"service": cb, "ticket": code_value})
                match = re.search(r"<(?:cas:)?user>(.*?)</(?:cas:)?user>", r.text, re.S)
                if not match:
                    raise ValueError("CAS validation failed")
                uid = match.group(1).strip()
                return {"external_id": f"cas:{uid}", "username": uid, "email": f"{uid}@cas.local",
                        "display_name": uid, "avatar": "", "demo": False, "raw": r.text[:500]}
            if ptype in {"oauth2", "oidc"}:
                token_url = cfg.get("token_url")
                if ptype == "oidc" and not token_url:
                    disc = cfg.get("discovery_url") or (
                        f"{cfg.get('issuer','').rstrip('/')}/.well-known/openid-configuration")
                    doc = (await client.get(disc)).json()
                    token_url = doc.get("token_endpoint")
                    cfg["userinfo_url"] = cfg.get("userinfo_url") or doc.get("userinfo_endpoint")
                r = await client.post(token_url or "", data={
                    "grant_type": "authorization_code", "code": code_value, "redirect_uri": cb,
                    "client_id": cfg.get("client_id", ""), "client_secret": cfg.get("client_secret", "")})
                token = r.json()
                access = token.get("access_token")
                profile: dict = {}
                if cfg.get("userinfo_url") and access:
                    profile = (await client.get(cfg["userinfo_url"],
                                                headers={"Authorization": f"Bearer {access}"})).json()
                if "id_token" in token and not profile:
                    try:
                        payload = token["id_token"].split(".")[1]
                        profile = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                    except Exception:
                        pass
                uid = str(profile.get("sub") or profile.get("id") or profile.get("username") or "sso-user")
                if state_row and state_row.get("nonce") and profile.get("nonce") != state_row["nonce"]:
                    raise ValueError("OIDC nonce mismatch")
                return {"external_id": f"{ptype}:{uid}", "username": uid,
                        "email": profile.get("email") or f"{uid}@sso.local",
                        "display_name": profile.get("name") or profile.get("preferred_username") or uid,
                        "avatar": profile.get("picture") or "", "demo": False, "raw": profile}
            if ptype == "wecom":
                tok = (await client.get("https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                                        params={"corpid": cfg.get("corp_id"),
                                                "corpsecret": cfg.get("secret")})).json()
                info = (await client.get("https://qyapi.weixin.qq.com/cgi-bin/user/getuserinfo",
                                         params={"access_token": tok.get("access_token", ""),
                                                 "code": code_value})).json()
                uid = str(info.get("UserId") or info.get("userid") or "wecom-user")
                return {"external_id": f"wecom:{uid}", "username": uid,
                        "email": f"{uid}@wecom.local", "display_name": uid,
                        "avatar": "", "demo": False, "raw": info}
            if ptype == "dingtalk":
                r = await client.post("https://api.dingtalk.com/v1.0/oauth2/userAccessToken", json={
                    "clientId": cfg.get("app_key"), "clientSecret": cfg.get("app_secret"),
                    "code": code_value, "grantType": "authorization_code"})
                access = r.json().get("accessToken")
                info = (await client.get("https://api.dingtalk.com/v1.0/contact/users/me",
                                         headers={"x-acs-dingtalk-access-token": access or ""})).json()
                uid = str(info.get("unionId") or "dingtalk-user")
                return {"external_id": f"dingtalk:{uid}", "username": uid,
                        "email": info.get("email") or f"{uid}@dingtalk.local",
                        "display_name": info.get("name") or uid,
                        "avatar": info.get("avatarUrl") or "", "demo": False, "raw": info}
    except Exception as exc:
        ident = _demo_identity(provider)
        ident["raw"] = {"mode": "demo-fallback", "reason": str(exc)[:200]}
        return ident
    return _demo_identity(provider)


def upsert_identity(identity: dict, provider_code: str, default_role: str = "viewer") -> dict:
    """Find or provision a local user for an external identity."""
    row = db.q1("SELECT * FROM users WHERE provider=? AND external_id=?",
                (provider_code, identity.get("external_id")))
    if row:
        db.update("users", row["id"], {"last_login_at": db.now()})
        return db.loads(row, "role_ids", "passkeys") or {}
    base = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(identity.get("username") or "sso-user"))[:40]
    username = base
    suffix = 1
    while db.q1("SELECT id FROM users WHERE username=?", (username,)):
        suffix += 1
        username = f"{base}_{suffix}"
    role = db.q1("SELECT id FROM roles WHERE code=?", (default_role,))
    rid = [role["id"]] if role else []
    uid = db.insert("users", {
        "username": username, "email": identity.get("email"),
        "display_name": identity.get("display_name") or username,
        "avatar": identity.get("avatar") or "", "password_hash": None,
        "status": "active", "role_ids": rid, "provider": provider_code,
        "external_id": identity.get("external_id"), "last_login_at": db.now(),
        "created_at": db.now(), "updated_at": db.now(),
    })
    return db.loads(db.q1("SELECT * FROM users WHERE id=?", (uid,)), "role_ids", "passkeys") or {}
