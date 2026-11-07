"""MCP management: tool catalog, call journal, skill lifecycle, editable files, sync, invoke."""
from __future__ import annotations

import csv
import io
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import Response

from .. import db, deps
from ..config import settings
from ..services import mcp_journal, mcp_tools, skill_catalog, skill_files

router = APIRouter(prefix="/mcp", tags=["MCP"])

SKILL_TYPES = ["builtin", "http", "sse", "stdio"]
SKILL_STATUSES = ["installed", "disabled", "uninstalled", "error"]
_CODE_PATTERN = r"^[a-z][a-z0-9_-]{1,49}$"


class SkillIn(BaseModel):
    code: str = Field(..., pattern=_CODE_PATTERN)
    name: str
    type: str = "http"
    endpoint: str | None = None
    command: str | None = None
    enabled: bool = True
    description: str = ""
    version: str = "1.0.0"
    source: str = "manual"
    manifest: dict = Field(default_factory=dict)
    auth_config: dict = Field(default_factory=dict)
    tools: list[dict] = Field(default_factory=list)


class SkillPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    endpoint: str | None = None
    command: str | None = None
    enabled: bool | None = None
    status: str | None = None
    description: str | None = None
    version: str | None = None
    manifest: dict | None = None
    auth_config: dict | None = None
    tools: list[dict] | None = None


class InstallIn(BaseModel):
    code: str = Field(..., pattern=_CODE_PATTERN)
    name: str | None = None
    type: str | None = None
    endpoint: str | None = None
    command: str | None = None
    version: str | None = None
    description: str | None = None
    source: str = "catalog"
    enabled: bool = True
    manifest: dict = Field(default_factory=dict)


class InvokeIn(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


class FileIn(BaseModel):
    content: str = ""


def _out(row: dict) -> dict:
    out = db.loads(row, "tools", "auth_config", "manifest") or {}
    out["enabled"] = bool(out.get("enabled"))
    out["tools"] = out.get("tools") or []
    out["auth_config"] = out.get("auth_config") or {}
    out["manifest"] = out.get("manifest") or {}
    out["status"] = out.get("status") or "installed"
    out["file_count"] = int(db.scalar(
        "SELECT COUNT(*) FROM mcp_skill_files WHERE skill_id=?", (out["id"],)) or 0)
    return out


def _skill(skill_id: int) -> dict:
    row = db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _out(row)


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


def _file_or_404(skill_id: int, path: str) -> dict:
    try:
        row = skill_files.get_file(skill_id, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Skill file not found")
    return row


# --------------------------------------------------------------------------- #
# Tool catalog + server status
# --------------------------------------------------------------------------- #
@router.get("/tools", summary="Platform MCP tool catalog")
def tools(_user: dict = Depends(deps.require("mcp:read"))):
    return {"tools": mcp_tools.list_tools(), "total": len(mcp_tools.TOOL_SPECS),
            "permissions": mcp_tools.PERMISSION_MAP}


@router.get("/status", summary="MCP server status")
def status(_user: dict = Depends(deps.require("mcp:read"))):
    by_status = {r["status"]: r["count"] for r in db.q(
        "SELECT status, COUNT(*) AS count FROM mcp_skills GROUP BY status")}
    return {"enabled": settings.mcp_enabled, "endpoint": "/mcp",
            "transport": "streamable-http", "stateless": settings.mcp_stateless,
            "protocol_version": "2025-06-18", "tool_count": len(mcp_tools.TOOL_SPECS),
            "external_servers": settings.mcp_external_servers,
            "skills": int(db.scalar("SELECT COUNT(*) FROM mcp_skills") or 0),
            "skill_statuses": by_status,
            "journal": {"enabled": True,
                        "total": int(db.scalar("SELECT COUNT(*) FROM mcp_call_logs") or 0),
                        "sources": list(mcp_journal.SOURCES)}}


# --------------------------------------------------------------------------- #
# Call journal  (static routes MUST precede /calls/{call_id})
# --------------------------------------------------------------------------- #
@router.get("/calls", summary="Query the MCP call journal")
def list_calls(tool: str | None = None, source: str | None = None,
               status: str | None = None, actor: str | None = None,
               method: str | None = None, q: str | None = None,
               limit: int = 100, offset: int = 0,
               _user: dict = Depends(deps.require("mcp:read"))):
    return mcp_journal.query(limit=limit, offset=offset, tool=tool, source=source,
                             status=status, actor=actor, method=method, q=q)


@router.get("/calls/stats", summary="MCP call journal statistics")
def call_stats(_user: dict = Depends(deps.require("mcp:read"))):
    return mcp_journal.stats()


@router.get("/calls/export", summary="Export the MCP call journal as CSV")
def export_calls(tool: str | None = None, source: str | None = None,
                 status: str | None = None, q: str | None = None,
                 _user: dict = Depends(deps.require("mcp:read"))):
    rows = mcp_journal.export(tool=tool, source=source, status=status, q=q)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "source", "method", "tool", "actor",
                     "status", "duration_ms", "arguments", "error"])
    for row in rows:
        writer.writerow([row.get("id"), row.get("created_at"), row.get("source"),
                         row.get("method"), row.get("tool") or "", row.get("actor") or "",
                         row.get("status"), row.get("duration_ms"),
                         json.dumps(row.get("arguments") or {}, ensure_ascii=False),
                         row.get("error") or ""])
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="mcp-call-journal.csv"'})


@router.get("/calls/{call_id}", summary="Get one MCP call journal entry")
def get_call(call_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    row = mcp_journal.get(call_id)
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return row


@router.delete("/calls", summary="Clear the MCP call journal")
def clear_calls(user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    deleted = mcp_journal.clear()
    deps.audit(user["username"], "mcp.journal.clear", "mcp_call_logs",
               {"deleted": deleted}, request=request)
    return {"ok": True, "deleted": deleted}


# --------------------------------------------------------------------------- #
# Skill registry + installable catalog
# --------------------------------------------------------------------------- #
@router.get("/skills", summary="List registered MCP skills")
def list_skills(_user: dict = Depends(deps.require("mcp:read"))):
    rows = db.q("SELECT * FROM mcp_skills ORDER BY id")
    return {"skills": [_out(r) for r in rows], "total": len(rows),
            "types": SKILL_TYPES, "statuses": SKILL_STATUSES,
            "catalog_count": len(skill_catalog.CATALOG_SPECS)}


@router.get("/skills/catalog", summary="Built-in installable MCP skill catalog")
def catalog(_user: dict = Depends(deps.require("mcp:read"))):
    installed = {r["code"]: r["status"] for r in db.q("SELECT code,status FROM mcp_skills")}
    items = skill_catalog.catalog()
    for item in items:
        state = installed.get(item["code"])
        item["installed"] = bool(state and state != "uninstalled")
        item["status"] = state or "available"
    return {"catalog": items, "total": len(items)}


@router.post("/skills/install", status_code=201, summary="Install an MCP skill and create its files")
def install_skill(body: InstallIn, user: dict = Depends(deps.require("mcp:write")),
                  request: Request = None):
    template = skill_catalog.find(body.code)
    skill_type = body.type or (template or {}).get("type") or "http"
    if skill_type not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    existing = db.q1("SELECT * FROM mcp_skills WHERE code=?", (body.code,))
    now = db.now()
    if existing and (existing.get("status") or "installed") != "uninstalled":
        raise HTTPException(status_code=409, detail="Skill is already installed")
    fields = {
        "name": body.name or (template or {}).get("name") or body.code,
        "type": skill_type,
        "endpoint": body.endpoint or (template or {}).get("endpoint"),
        "command": body.command or (template or {}).get("command"),
        "version": body.version or (template or {}).get("version") or "1.0.0",
        "description": body.description or (template or {}).get("description") or "",
        "manifest": body.manifest or {"schema": "ailp.mcp.skill/1",
                                      "capabilities": (template or {}).get("capabilities", [])},
        "enabled": int(body.enabled), "status": "installed", "source": body.source,
        "health": "unknown", "installed_at": now, "updated_at": now,
    }
    if existing:
        db.update("mcp_skills", existing["id"], fields)
        skill_id = existing["id"]
    else:
        skill_id = db.insert("mcp_skills", {**fields, "code": body.code,
                                             "auth_config": {}, "tools": [],
                                             "created_at": now})
    created = skill_files.install_files({**fields, "id": skill_id, "code": body.code})
    deps.audit(user["username"], "mcp.skill.install", f"skill:{body.code}",
               {"type": skill_type, "files": created, "source": body.source}, request=request)
    return {**_out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))),
            "files_created": created}


@router.post("/skills", status_code=201, summary="Register a third-party MCP server as a skill")
def create_skill(body: SkillIn, user: dict = Depends(deps.require("mcp:write")),
                 request: Request = None):
    if body.type not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    if db.q1("SELECT id FROM mcp_skills WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Skill code already exists")
    now = db.now()
    sid = db.insert("mcp_skills", {**body.model_dump(), "enabled": int(body.enabled),
                                   "status": "installed", "health": "unknown",
                                   "installed_at": now, "updated_at": now,
                                   "created_at": now})
    skill_files.install_files({**body.model_dump(), "id": sid})
    deps.audit(user["username"], "mcp.skill.create", f"skill:{body.code}",
               {"type": body.type}, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (sid,)))


# --------------------------------------------------------------------------- #
# Single skill: detail, update, lifecycle
# --------------------------------------------------------------------------- #
@router.get("/skills/{skill_id}", summary="Get a skill with its files and manifest")
def get_skill(skill_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    skill = _skill(skill_id)
    return {**skill, "files": skill_files.list_files(skill_id),
            "disk_path": str(skill_files.skill_dir(skill["code"]))}


@router.put("/skills/{skill_id}", summary="Update a registered skill")
def update_skill(skill_id: int, body: SkillPatch,
                 user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    _skill(skill_id)
    patch = body.model_dump(exclude_none=True)
    if "enabled" in patch:
        patch["enabled"] = int(patch["enabled"])
        patch.setdefault("status", "installed" if patch["enabled"] else "disabled")
    if patch.get("type") and patch["type"] not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    if patch.get("status") and patch["status"] not in SKILL_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {SKILL_STATUSES}")
    patch["updated_at"] = db.now()
    db.update("mcp_skills", skill_id, patch)
    deps.audit(user["username"], "mcp.skill.update", f"skill:{skill_id}", patch, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,)))


@router.delete("/skills/{skill_id}", summary="Permanently remove a skill and its files")
def delete_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                 request: Request = None):
    row = db.q1("SELECT code FROM mcp_skills WHERE id=?", (skill_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_files.clear_files(skill_id, row["code"])
    db.delete("mcp_skills", skill_id)
    deps.audit(user["username"], "mcp.skill.delete", f"skill:{row['code']}", {}, request=request)
    return {"ok": True}


def _lifecycle(skill_id: int, action: str, user: dict, request: Request | None) -> dict:
    skill = _skill(skill_id)
    now = db.now()
    if action == "enable":
        patch = {"enabled": 1, "status": "installed", "updated_at": now}
        created = skill_files.ensure_files({"id": skill_id, "code": skill["code"], **skill})
    elif action == "disable":
        patch, created = {"enabled": 0, "status": "disabled", "updated_at": now}, 0
    elif action == "uninstall":
        created = skill_files.clear_files(skill_id, skill["code"])
        patch = {"enabled": 0, "status": "uninstalled", "health": "unknown",
                 "tools": [], "updated_at": now}
    else:  # reinstall
        patch = {"enabled": 1, "status": "installed", "health": "unknown",
                 "installed_at": now, "updated_at": now}
        created = skill_files.install_files({"id": skill_id, "code": skill["code"], **skill})
    db.update("mcp_skills", skill_id, patch)
    deps.audit(user["username"], f"mcp.skill.{action}", f"skill:{skill['code']}",
               {"status": patch["status"], "files": created}, request=request)
    return {**_out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))),
            "action": action, "files_affected": created}


@router.post("/skills/{skill_id}/enable", summary="Enable an installed skill")
def enable_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                 request: Request = None):
    return _lifecycle(skill_id, "enable", user, request)


@router.post("/skills/{skill_id}/disable", summary="Disable a skill without uninstalling it")
def disable_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                  request: Request = None):
    return _lifecycle(skill_id, "disable", user, request)


@router.post("/skills/{skill_id}/uninstall", summary="Uninstall a skill (keeps registry entry)")
def uninstall_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                    request: Request = None):
    return _lifecycle(skill_id, "uninstall", user, request)


@router.post("/skills/{skill_id}/reinstall", summary="Reinstall a previously uninstalled skill")
def reinstall_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                    request: Request = None):
    return _lifecycle(skill_id, "reinstall", user, request)


# --------------------------------------------------------------------------- #
# Editable skill files  (static /reload MUST precede /{path:path})
# --------------------------------------------------------------------------- #
@router.get("/skills/{skill_id}/files", summary="List editable files of a skill")
def list_skill_files(skill_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    skill = _skill(skill_id)
    files = skill_files.list_files(skill_id)
    return {"files": files, "total": len(files),
            "disk_path": str(skill_files.skill_dir(skill["code"]))}


@router.post("/skills/{skill_id}/files/reload", summary="Reload skill files from the disk mirror")
def reload_skill_files(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                       request: Request = None):
    skill = _skill(skill_id)
    loaded = skill_files.reload_from_disk(skill)
    deps.audit(user["username"], "mcp.skill.files.reload", f"skill:{skill['code']}",
               {"loaded": loaded}, request=request)
    return {"ok": True, "loaded": loaded}


@router.get("/skills/{skill_id}/files/{path:path}", summary="Read one skill file")
def read_skill_file(skill_id: int, path: str,
                    _user: dict = Depends(deps.require("mcp:read"))):
    _skill(skill_id)
    return _file_or_404(skill_id, path)


@router.put("/skills/{skill_id}/files/{path:path}", summary="Create or update a skill file")
def write_skill_file(skill_id: int, path: str, body: FileIn,
                     user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    skill = _skill(skill_id)
    try:
        row = skill_files.put_file(skill_id, skill["code"], path, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "mcp.skill.files.write", f"skill:{skill['code']}",
               {"path": row["path"], "size": row["size"]}, request=request)
    return row


@router.delete("/skills/{skill_id}/files/{path:path}", summary="Delete a skill file")
def delete_skill_file(skill_id: int, path: str,
                      user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    skill = _skill(skill_id)
    try:
        removed = skill_files.delete_file(skill_id, skill["code"], path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Skill file not found")
    deps.audit(user["username"], "mcp.skill.files.delete", f"skill:{skill['code']}",
               {"path": path}, request=request)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Sync + invoke
# --------------------------------------------------------------------------- #
@router.post("/skills/{skill_id}/sync", summary="Probe an MCP server and refresh its tool list")
async def sync_skill(skill_id: int, user: dict = Depends(deps.require("mcp:write")),
                     request: Request = None):
    skill = _skill(skill_id)
    health, tools, message = "unknown", list(skill.get("tools") or []), ""
    if skill["type"] == "builtin":
        tools = mcp_tools.list_tools()
        health, message = "healthy", "Synced from the platform tool registry."
    elif skill["type"] == "stdio":
        health, message = "manual", "stdio skills run on the host; tools must be declared manually."
    elif skill.get("endpoint"):
        headers = {"Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json"}
        auth = skill.get("auth_config") or {}
        if auth.get("token"):
            headers["Authorization"] = f"Bearer {auth['token']}"
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "ai-lowcode-platform", "version": "0.1.0"}}}
                await client.post(skill["endpoint"], json=init, headers=headers)
                r = await client.post(skill["endpoint"], json={
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
                                       "last_sync_at": db.now(), "updated_at": db.now()})
    deps.audit(user["username"], "mcp.skill.sync", f"skill:{skill['code']}",
               {"health": health, "tools": len(tools)}, request=request)
    return {"ok": True, "health": health, "tools": tools, "message": message,
            "last_sync_at": db.now()}


@router.post("/invoke", summary="Invoke a platform MCP tool over REST")
def invoke(body: InvokeIn, user: dict = Depends(deps.require("mcp:invoke")),
           request: Request = None):
    mcp_tools.bind_context(source="rest", transport="http", method="invoke",
                           actor=user["username"], request_id=db.uid()[:12])
    try:
        result = mcp_tools.call_tool(body.tool, body.arguments, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    deps.audit(user["username"], "mcp.invoke", f"tool:{body.tool}",
               {"arguments": body.arguments}, request=request)
    return {"tool": body.tool, "result": result}
