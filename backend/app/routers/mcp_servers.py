"""MCP server registry — independent from the Skills registry.

Manages connections to the platform's own /mcp endpoint and to third-party
streamable-HTTP / SSE / stdio MCP servers. Each server owns its transport,
auth, declared tool catalog, health and call target. Skills live under
``/skills`` and may optionally reference a server through ``server_id``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..services import mcp_servers, mcp_tools

router = APIRouter(prefix="/mcp/servers", tags=["MCP Servers"])

_CODE_PATTERN = r"^[a-z][a-z0-9_-]{1,49}$"


class ServerIn(BaseModel):
    code: str = Field(..., pattern=_CODE_PATTERN)
    name: str
    description: str = ""
    transport: str = "http"
    endpoint: str | None = None
    command: str | None = None
    enabled: bool = True
    auth_config: dict = Field(default_factory=dict)
    tools: list[dict] = Field(default_factory=list)
    source: str = "manual"
    status: str = "active"


class ServerPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    transport: str | None = None
    endpoint: str | None = None
    command: str | None = None
    enabled: bool | None = None
    auth_config: dict | None = None
    tools: list[dict] | None = None
    status: str | None = None
    health: str | None = None


class ServerInvokeIn(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


def _server(server_id: int) -> dict:
    row = mcp_servers.get(server_id)
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return row


@router.get("", summary="List registered MCP servers")
def list_servers(_user: dict = Depends(deps.require("mcp:read"))):
    rows = mcp_servers.rows()
    return {"servers": rows, "total": len(rows),
            "transports": list(mcp_servers.TRANSPORTS),
            "statuses": list(mcp_servers.STATUSES),
            "stats": mcp_servers.stats()}


@router.get("/summary", summary="MCP server registry statistics")
def server_summary(_user: dict = Depends(deps.require("mcp:read"))):
    return mcp_servers.stats()


@router.post("", status_code=201, summary="Register an MCP server")
def create_server(body: ServerIn, user: dict = Depends(deps.require("mcp:write")),
                  request: Request = None):
    if body.transport not in mcp_servers.TRANSPORTS:
        raise HTTPException(status_code=400,
                            detail=f"transport must be one of {list(mcp_servers.TRANSPORTS)}")
    if db.q1("SELECT id FROM mcp_servers WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="MCP server code already exists")
    now = db.now()
    sid = db.insert("mcp_servers", {**body.model_dump(), "enabled": int(body.enabled),
                                    "health": "unknown", "last_sync_at": None,
                                    "created_by": user["username"],
                                    "created_at": now, "updated_at": now})
    deps.audit(user["username"], "mcp.server.create", f"server:{body.code}",
               {"transport": body.transport}, request=request)
    return mcp_servers.get(sid)


@router.get("/{server_id}", summary="Get one MCP server")
def get_server(server_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    server = _server(server_id)
    return {**server, "skills": db.q(
        "SELECT id,code,name,status FROM mcp_skills WHERE server_id=? ORDER BY id",
        (server_id,))}


@router.put("/{server_id}", summary="Update an MCP server")
def update_server(server_id: int, body: ServerPatch,
                  user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    row = _server(server_id)
    patch = body.model_dump(exclude_none=True)
    if patch.get("transport") and patch["transport"] not in mcp_servers.TRANSPORTS:
        raise HTTPException(status_code=400,
                            detail=f"transport must be one of {list(mcp_servers.TRANSPORTS)}")
    if patch.get("status") and patch["status"] not in mcp_servers.STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"status must be one of {list(mcp_servers.STATUSES)}")
    if "enabled" in patch:
        patch["enabled"] = int(patch["enabled"])
    patch["updated_at"] = db.now()
    db.update("mcp_servers", server_id, patch)
    deps.audit(user["username"], "mcp.server.update", f"server:{row['code']}", patch,
               request=request)
    return mcp_servers.get(server_id)


@router.delete("/{server_id}", summary="Delete an MCP server")
def delete_server(server_id: int, user: dict = Depends(deps.require("mcp:write")),
                  request: Request = None):
    row = _server(server_id)
    db.run("UPDATE mcp_skills SET server_id=NULL WHERE server_id=?", (server_id,))
    db.delete("mcp_servers", server_id)
    deps.audit(user["username"], "mcp.server.delete", f"server:{row['code']}", {},
               request=request)
    return {"ok": True}


@router.get("/{server_id}/tools", summary="Tools declared by an MCP server")
def server_tools(server_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    server = _server(server_id)
    return {"tools": server.get("tools") or [], "total": len(server.get("tools") or []),
            "server": server["code"], "health": server["health"]}


@router.post("/{server_id}/sync", summary="Probe an MCP server and refresh its tool list")
def sync_server(server_id: int, user: dict = Depends(deps.require("mcp:write")),
                request: Request = None):
    row = _server(server_id)
    result = mcp_servers.sync(server_id)
    deps.audit(user["username"], "mcp.server.sync", f"server:{row['code']}",
               {"health": result["health"], "tools": len(result["tools"])}, request=request)
    return {**result, "server": row["code"]}


def _toggle(server_id: int, enabled: bool, user: dict, request: Request | None) -> dict:
    row = _server(server_id)
    db.update("mcp_servers", server_id, {
        "enabled": int(enabled), "status": "active" if enabled else "inactive",
        "updated_at": db.now()})
    deps.audit(user["username"], "mcp.server.toggle", f"server:{row['code']}",
               {"enabled": enabled}, request=request)
    return mcp_servers.get(server_id) or {}


@router.post("/{server_id}/enable", summary="Enable an MCP server")
def enable_server(server_id: int, user: dict = Depends(deps.require("mcp:write")),
                  request: Request = None):
    return _toggle(server_id, True, user, request)


@router.post("/{server_id}/disable", summary="Disable an MCP server")
def disable_server(server_id: int, user: dict = Depends(deps.require("mcp:write")),
                   request: Request = None):
    return _toggle(server_id, False, user, request)


@router.post("/{server_id}/invoke", summary="Invoke a tool through a specific MCP server")
def invoke_on_server(server_id: int, body: ServerInvokeIn,
                     user: dict = Depends(deps.require("mcp:invoke")),
                     request: Request = None):
    server = _server(server_id)
    declared = {t.get("name") for t in (server.get("tools") or []) if isinstance(t, dict)}
    if body.tool not in declared:
        raise HTTPException(status_code=400,
                            detail=f"Tool '{body.tool}' is not declared by {server['code']}")
    mcp_tools.bind_context(source="rest", transport=server["transport"], method="server.invoke",
                           actor=user["username"], request_id=db.uid()[:12],
                           target=f"server:{server['code']}")
    try:
        result = mcp_tools.call_tool(body.tool, body.arguments, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    deps.audit(user["username"], "mcp.server.invoke", f"server:{server['code']}",
               {"tool": body.tool}, request=request)
    return {"server": server["code"], "tool": body.tool, "result": result}
