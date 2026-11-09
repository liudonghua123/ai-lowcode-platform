"""Platform metadata, bootstrap catalogs, dashboard stats and settings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import __version__, db, deps, security
from ..config import settings
from ..routers import forms, workflows
from ..services import (
    flow_runtime,
    form_catalog,
    llm,
    mcp_servers,
    mcp_tools,
    model_providers,
    registry,
    skill_catalog,
    sso,
)

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
        "form_flow": {"form_field_types": len(forms.FIELD_TYPES),
                      "workflow_node_types": len(registry.node_codes()),
                      "component_groups": len(form_catalog.GROUPS),
                      "custom_components": len(registry.custom_components()),
                      "custom_nodes": len(registry.custom_nodes()),
                      "pending_tasks": int(db.scalar(
                          "SELECT COUNT(*) FROM flow_tasks WHERE status='pending'") or 0),
                      "org_units": int(db.scalar("SELECT COUNT(*) FROM org_units") or 0)},
        "hubs": {"configured": int(db.scalar("SELECT COUNT(*) FROM skill_hubs") or 0),
                 "enabled": int(db.scalar("SELECT COUNT(*) FROM skill_hubs WHERE enabled=1") or 0)},
        "database": "sqlite",
        "security": {"data_scopes": ["all", "audit", "self"],
                     "auditor_role": bool(db.q1("SELECT id FROM roles WHERE code='auditor'"))},
    }


@router.get("/version", summary="Version information")
def version():
    return {"version": __version__, "name": settings.app_name,
            "api_prefix": settings.api_prefix, "license": "MIT"}


# --------------------------------------------------------------------------- #
# Declarative registry — single source of truth for designers
# --------------------------------------------------------------------------- #
@router.get("/registry", summary="Extensible component / node registry with config schemas")
def get_registry(lang: str = Query("en", pattern="^(en|zh)$"),
                 _user: dict = Depends(deps.get_current_user)):
    return registry.registry_payload(lang)


class CustomTypeIn(BaseModel):
    spec: dict


@router.post("/registry/components", status_code=201,
             summary="Register a custom form component type at runtime")
def register_component(body: CustomTypeIn, user: dict = Depends(deps.require("form:write")),
                       request: Request = None):
    try:
        saved = registry.register_custom("components", body.spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "registry.component.create", f"component:{saved.get('code')}",
               {"code": saved.get("code")}, request=request)
    return {"registered": saved, "total": len(registry.custom_components())}


@router.post("/registry/nodes", status_code=201,
             summary="Register a custom workflow node type at runtime")
def register_node(body: CustomTypeIn, user: dict = Depends(deps.require("workflow:write")),
                  request: Request = None):
    try:
        saved = registry.register_custom("nodes", body.spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "registry.node.create", f"node:{saved.get('type')}",
               {"type": saved.get("type")}, request=request)
    return {"registered": saved, "total": len(registry.custom_nodes())}


@router.delete("/registry/{kind}/{code}", summary="Remove a custom component / node type")
def remove_custom_type(kind: str, code: str,
                       user: dict = Depends(deps.get_current_user), request: Request = None):
    allowed = {"components": "form:write", "nodes": "workflow:write"}
    if kind not in allowed:
        raise HTTPException(status_code=400, detail="kind must be components | nodes")
    if not deps.has_permission(user, allowed[kind]):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        removed = registry.remove_custom(kind, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], f"registry.{kind}.delete", f"{kind}:{code}", {}, request=request)
    return {"ok": removed, "code": code, "kind": kind}


@router.get("/stats", summary="Dashboard statistics")
def stats(user: dict = Depends(deps.require("dashboard:view"))):
    # Internal dashboard aggregation — not an MCP invocation, skip the journal.
    # Pass the caller so self-scope users only see their own business rows.
    data = mcp_tools.call_tool("get_stats", {}, user=user, journal=False)
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
                 "field_groups": form_catalog.catalog()["groups"],
                 "validators": [v["code"] for v in form_catalog.VALIDATORS],
                 "functions": [f["code"] for f in form_catalog.FUNCTIONS],
                 "permission_modes": [m["code"] for m in form_catalog.PERMISSION_MODES],
                 "composite_types": sorted(form_catalog.COMPOSITE_TYPES),
                 "component_count": len(forms.FIELD_TYPES),
                 "statuses": ["draft", "published", "archived"]},
        "workflow": {"node_types": registry.node_types(),
                     "node_categories": sorted({n["category"] for n in registry.node_types()}),
                     "human_nodes": sorted(registry.human_node_types()),
                     "operators": workflows.OPERATORS,
                     "approver_rules": [r["code"] for r in flow_runtime.APPROVER_RULES],
                     "sign_modes": [m["code"] for m in flow_runtime.SIGN_MODES],
                     "actions": flow_runtime.ACTIONS,
                     "statuses": ["draft", "published", "archived"]},
        "registry": {"components": len(forms.FIELD_TYPES),
                     "nodes": len(registry.node_codes()),
                     "custom_components": len(registry.custom_components()),
                     "custom_nodes": len(registry.custom_nodes()),
                     "endpoint": "/meta/registry"},
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
                "tool_count": len(mcp_tools.list_tools(user=user)),
                "builtin_tool_count": len(mcp_tools.TOOL_SPECS),
                "capability_matrix": mcp_tools.capability_matrix(user),
                "server_count": mcp_servers.stats()["total"]},
        "skills": {"catalog_count": len(skill_catalog.CATALOG_SPECS),
                   "installed": int(db.scalar(
                       "SELECT COUNT(*) FROM mcp_skills WHERE status!='uninstalled'") or 0),
                   "types": ["builtin", "http", "sse", "stdio"],
                   "statuses": ["installed", "disabled", "uninstalled", "error"],
                   "hubs": int(db.scalar("SELECT COUNT(*) FROM skill_hubs") or 0),
                   "hub_enabled": int(db.scalar(
                       "SELECT COUNT(*) FROM skill_hubs WHERE enabled=1") or 0),
                   "independent_registry": True},
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
