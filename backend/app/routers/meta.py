"""Platform metadata, bootstrap catalogs, dashboard stats and settings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import __version__, db, deps, security
from ..config import settings
from ..routers import forms, workflows
from ..services import llm, mcp_servers, mcp_tools, model_providers, skill_catalog, sso

router = APIRouter(prefix="/meta", tags=["Metadata"])
settings_router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/health", summary="Public health check", include_in_schema=True)
def health(request: Request):
    return {
        "status": "ok", "app": settings.app_name, "version": __version__,
        "env": settings.app_env,
        "mcp": {"enabled": settings.mcp_enabled, "mode": getattr(request.app.state, "mcp_mode", "unknown"),
                "endpoint": "/mcp"},
        "llm": {"provider": llm.describe()["provider"], "model": llm.describe()["model"],
                "config_source": llm.describe()["config_source"],
                "agentscope": llm.AGENTSCOPE_INFO["available"]},
        "registries": {"mcp_servers": mcp_servers.stats()["total"],
                       "skills": int(db.scalar("SELECT COUNT(*) FROM mcp_skills") or 0),
                       "model_providers": model_providers.meta()["total"]},
        "database": "sqlite",
    }


@router.get("/version", summary="Version information")
def version():
    return {"version": __version__, "name": settings.app_name,
            "api_prefix": settings.api_prefix, "license": "MIT"}


@router.get("/stats", summary="Dashboard statistics")
def stats(_user: dict = Depends(deps.require("dashboard:view"))):
    # Internal dashboard aggregation — not an MCP invocation, skip the journal.
    data = mcp_tools.call_tool("get_stats", {}, journal=False)
    data["recent_instances"] = db.q(
        "SELECT id,workflow_id,status,started_by,started_at FROM workflow_instances "
        "ORDER BY id DESC LIMIT 5")
    data["recent_logs"] = [db.loads(r, "detail") for r in db.q(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT 6")]
    return data


@router.get("/bootstrap", summary="All UI catalogs in one request")
def bootstrap(user: dict = Depends(deps.get_current_user), request: Request = None):
    perms = db.q("SELECT code,name,resource,action FROM permissions ORDER BY resource,action")
    roles = db.q("SELECT id,code,name,description,builtin,mfa_required FROM roles ORDER BY id")
    providers = db.q("SELECT code,type,name,enabled FROM auth_providers ORDER BY sort_order")
    return {
        "app": {"name": settings.app_name, "version": __version__,
                "api_prefix": settings.api_prefix, "license": "MIT"},
        "i18n": {"locales": ["en", "zh"], "default": "en"},
        "themes": ["system", "light", "dark"],
        "defaults": {"locale": "en", "theme": "system"},
        "form": {"field_types": forms.FIELD_TYPES,
                 "statuses": ["draft", "published", "archived"]},
        "workflow": {"node_types": workflows.NODE_TYPES, "operators": workflows.OPERATORS,
                     "statuses": ["draft", "published", "archived"]},
        "rbac": {"permissions": perms,
                 "roles": [dict(r, builtin=bool(r["builtin"]),
                                mfa_required=bool(r["mfa_required"])) for r in roles]},
        "auth": {"provider_meta": sso.PROVIDER_META,
                 "providers": [dict(p, enabled=bool(p["enabled"])) for p in providers],
                 "mfa_methods": ["otp", "passkey"],
                 "mfa_policy": security.mfa_policy()},
        "agents": {"modes": ["query", "act", "hybrid"], "runtime": llm.describe()},
        "mcp": {"types": ["builtin", "http", "sse", "stdio"], "endpoint": "/mcp",
                "mode": getattr(request.app.state, "mcp_mode", "unknown") if request else "unknown",
                "tool_count": len(mcp_tools.list_tools()),
                "builtin_tool_count": len(mcp_tools.TOOL_SPECS),
                "server_count": mcp_servers.stats()["total"]},
        "skills": {"catalog_count": len(skill_catalog.CATALOG_SPECS),
                   "installed": int(db.scalar(
                       "SELECT COUNT(*) FROM mcp_skills WHERE status!='uninstalled'") or 0),
                   "types": ["builtin", "http", "sse", "stdio"],
                   "statuses": ["installed", "disabled", "uninstalled", "error"]},
        "ai": {"categories": list(model_providers.CATEGORY_CODES),
               "providers": model_providers.meta()["total"],
               "defaults": model_providers.meta()["defaults"]},
        "user": {k: v for k, v in user.items() if k not in {"password_hash", "otp_secret", "passkeys"}},
    }


DEFAULT_SETTINGS = {
    "default_locale": "en", "default_theme": "system", "allow_signup": False,
    "audit_retention_days": 90, "password_min_length": 8, "session_idle_minutes": 120,
}


@settings_router.get("", summary="Platform settings")
def get_settings(_user: dict = Depends(deps.require("settings:read"))):
    row = db.q1("SELECT value,updated_at FROM settings WHERE key='platform_settings'")
    value = DEFAULT_SETTINGS
    if row:
        try:
            import json
            value = {**DEFAULT_SETTINGS, **json.loads(row["value"])}
        except ValueError:
            pass
    return {"settings": value, "updated_at": row["updated_at"] if row else None}


@settings_router.put("", summary="Update platform settings")
def put_settings(body: dict, user: dict = Depends(deps.require("settings:write")),
                 request: Request = None):
    current = get_settings(user)["settings"]
    merged = {**current, **body}
    db.run("INSERT INTO settings(key,value,updated_at) VALUES('platform_settings',?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
           (db.dumps(merged), db.now()))
    deps.audit(user["username"], "settings.update", "settings", merged, request=request)
    return {"settings": merged}


class AiSettingsItem(BaseModel):
    category: str
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    enabled: bool | None = None


class AiSettingsIn(BaseModel):
    items: list[AiSettingsItem] = Field(default_factory=list)


@settings_router.get("/ai", summary="AI model services, initial values bootstrapped from .env")
def get_ai_settings(_user: dict = Depends(deps.require("settings:read"))):
    return model_providers.settings_view()


@settings_router.put("/ai", summary="Save the default AI model service of each category")
def put_ai_settings(body: AiSettingsIn, user: dict = Depends(deps.require("settings:write")),
                    request: Request = None):
    try:
        result = model_providers.save_settings(
            [item.model_dump(exclude_none=True) for item in body.items])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "settings.ai.update", "ai_providers",
               {"categories": [item.category for item in body.items],
                "saved": result.get("saved", 0)}, request=request)
    return result
