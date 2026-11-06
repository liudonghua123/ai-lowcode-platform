"""MCP management: platform tools, third-party skills registry, sync and invoke."""
from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..config import settings
from ..services import mcp_tools

router = APIRouter(prefix="/mcp", tags=["MCP"])

SKILL_TYPES = ["builtin", "http", "sse", "stdio"]


class SkillIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    name: str
    type: str = "http"
    endpoint: str | None = None
    command: str | None = None
    enabled: bool = True
    auth_config: dict = Field(default_factory=dict)
    tools: list[dict] = Field(default_factory=list)


class SkillPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    endpoint: str | None = None
    command: str | None = None
    enabled: bool | None = None
    auth_config: dict | None = None
    tools: list[dict] | None = None


class InvokeIn(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


def _out(row: dict) -> dict:
    out = db.loads(row, "tools", "auth_config") or {}
    out["enabled"] = bool(out.get("enabled"))
    out["tools"] = out.get("tools") or []
    out["auth_config"] = out.get("auth_config") or {}
    return out


def _parse_rpc(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except ValueError:
                continue
    return None


@router.get("/tools", summary="Platform MCP tool catalog")
def tools(_user: dict = Depends(deps.require("mcp:read"))):
    return {"tools": mcp_tools.list_tools(), "total": len(mcp_tools.TOOL_SPECS),
            "permissions": mcp_tools.PERMISSION_MAP}


@router.get("/status", summary="MCP server status")
def status(_user: dict = Depends(deps.require("mcp:read"))):
    return {"enabled": settings.mcp_enabled, "endpoint": "/mcp",
            "transport": "streamable-http", "stateless": settings.mcp_stateless,
            "protocol_version": "2025-06-18", "tool_count": len(mcp_tools.TOOL_SPECS),
            "external_servers": settings.mcp_external_servers,
            "skills": int(db.scalar("SELECT COUNT(*) FROM mcp_skills") or 0)}


@router.get("/skills", summary="List registered MCP skills / third-party servers")
def list_skills(_user: dict = Depends(deps.require("mcp:read"))):
    rows = db.q("SELECT * FROM mcp_skills ORDER BY id")
    return {"skills": [_out(r) for r in rows], "total": len(rows),
            "types": SKILL_TYPES}


@router.post("/skills", status_code=201, summary="Register a third-party MCP server as a skill")
def create_skill(body: SkillIn, user: dict = Depends(deps.require("mcp:write")),
                 request: Request = None):
    if body.type not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    if db.q1("SELECT id FROM mcp_skills WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Skill code already exists")
    sid = db.insert("mcp_skills", {**body.model_dump(), "enabled": int(body.enabled),
                                   "health": "unknown", "created_at": db.now()})
    deps.audit(user["username"], "mcp.skill.create", f"skill:{body.code}",
               {"type": body.type}, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (sid,)))


@router.put("/skills/{skill_id}", summary="Update a registered skill")
def update_skill(skill_id: int, body: SkillPatch,
                 user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    if not db.q1("SELECT id FROM mcp_skills WHERE id=?", (skill_id,)):
        raise HTTPException(status_code=404, detail="Skill not found")
    patch = body.model_dump(exclude_none=True)
    if "enabled" in patch:
        patch["enabled"] = int(patch["enabled"])
    if patch.get("type") and patch["type"] not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    db.update("mcp_skills", skill_id, patch)
    deps.audit(user["username"], "mcp.skill.update", f"skill:{skill_id}", patch, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,)))


@router.delete("/skills/{skill_id}", summary="Remove a skill")
def delete_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                 request: Request = None):
    row = db.q1("SELECT code FROM mcp_skills WHERE id=?", (skill_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete("mcp_skills", skill_id)
    deps.audit(user["username"], "mcp.skill.delete", f"skill:{row['code']}", {}, request=request)
    return {"ok": True}


@router.post("/skills/{skill_id}/sync", summary="Probe an MCP server and refresh its tool list")
async def sync_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                     request: Request = None):
    skill = db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    s = _out(skill)
    health, tools, message = "unknown", list(s.get("tools") or []), ""
    if s["type"] == "builtin":
        tools = mcp_tools.list_tools()
        health, message = "healthy", "Synced from the platform tool registry."
    elif s["type"] == "stdio":
        health, message = "manual", "stdio skills run on the host; tools must be declared manually."
    elif s.get("endpoint"):
        headers = {"Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json"}
        auth = s.get("auth_config") or {}
        if auth.get("token"):
            headers["Authorization"] = f"Bearer {auth['token']}"
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "ai-lowcode-platform", "version": "0.1.0"}}}
                await client.post(s["endpoint"], json=init, headers=headers)
                r = await client.post(s["endpoint"], json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, headers=headers)
                payload = _parse_rpc(r.text) or {}
                remote = ((payload.get("result") or {}).get("tools")) or []
                if remote:
                    tools = [{"name": t.get("name"), "description": t.get("description") or "",
                              "inputSchema": t.get("inputSchema") or {}} for t in remote]
                health, message = "healthy", f"Discovered {len(tools)} remote tools."
        except Exception as exc:
            health, message = "unreachable", f"Probe failed: {str(exc)[:160]}. Keeping declared tools."
    else:
        health, message = "unconfigured", "Set an endpoint to enable probing."
    db.update("mcp_skills", skill_id, {"tools": tools, "health": health,
                                       "last_sync_at": db.now()})
    deps.audit(user["username"], "mcp.skill.sync", f"skill:{s['code']}",
               {"health": health, "tools": len(tools)}, request=request)
    return {"ok": True, "health": health, "tools": tools, "message": message,
            "last_sync_at": db.now()}


@router.post("/invoke", summary="Invoke a platform MCP tool over REST")
def invoke(body: InvokeIn, user: dict = Depends(deps.require("mcp:invoke")),
           request: Request = None):
    try:
        result = mcp_tools.call_tool(body.tool, body.arguments, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    deps.audit(user["username"], "mcp.invoke", f"tool:{body.tool}",
               {"arguments": body.arguments}, request=request)
    return {"tool": body.tool, "result": result}
