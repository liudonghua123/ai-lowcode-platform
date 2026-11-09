"""Skills registry — independent from the MCP server registry.

A Skill is an installable capability package: catalog entry, install / enable /
disable / uninstall / reinstall lifecycle, versioned manifest and editable
files (SKILL.md, manifest.json, config.json, tools.json, README.md) mirrored to
``data/skills/<code>/``. A skill may reference an MCP server via ``server_id``,
but the two registries are managed separately (``/mcp/servers`` vs ``/skills``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..services import mcp_servers, skill_catalog, skill_files

router = APIRouter(prefix="/skills", tags=["Skills"])

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
    server_id: int | None = None
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
    server_id: int | None = None
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
    server_id: int | None = None
    source: str = "catalog"
    enabled: bool = True
    manifest: dict = Field(default_factory=dict)


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
    # A skill may optionally reference an MCP server, but the two registries
    # are managed independently; the link is informational only.
    server_id = out.get("server_id")
    out["server"] = None
    if server_id:
        srv = mcp_servers.get(int(server_id))
        if srv:
            out["server"] = {"id": srv["id"], "code": srv["code"], "name": srv["name"],
                             "transport": srv["transport"], "enabled": srv["enabled"]}
    out["hub"] = None
    hub_id = out.get("hub_id")
    if hub_id:
        from ..services import skill_hubs
        hub = skill_hubs.get(int(hub_id))
        if hub:
            out["hub"] = {"id": hub["id"], "code": hub["code"], "name": hub["name"],
                          "kind": hub["kind"]}
    return out


def _skill(skill_id: int) -> dict:
    row = db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _out(row)


def _file_or_404(skill_id: int, path: str) -> dict:
    try:
        row = skill_files.get_file(skill_id, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Skill file not found")
    return row


def _validate_link(server_id: int | None) -> None:
    if server_id and not mcp_servers.get(int(server_id)):
        raise HTTPException(status_code=400, detail="Linked MCP server not found")


# --------------------------------------------------------------------------- #
# Registry + installable catalog  (static routes before /{skill_id})
# --------------------------------------------------------------------------- #
@router.get("", summary="List installed skills")
def list_skills(_user: dict = Depends(deps.require("skill:read"))):
    rows = db.q("SELECT * FROM mcp_skills ORDER BY id")
    return {"skills": [_out(r) for r in rows], "total": len(rows),
            "types": SKILL_TYPES, "statuses": SKILL_STATUSES,
            "catalog_count": len(skill_catalog.CATALOG_SPECS),
            "servers": [{"id": s["id"], "code": s["code"], "name": s["name"]}
                        for s in mcp_servers.rows()]}


@router.get("/catalog", summary="Built-in installable skill catalog")
def catalog(_user: dict = Depends(deps.require("skill:read"))):
    installed = {r["code"]: r["status"] for r in db.q("SELECT code,status FROM mcp_skills")}
    items = skill_catalog.catalog()
    for item in items:
        state = installed.get(item["code"])
        item["installed"] = bool(state and state != "uninstalled")
        item["status"] = state or "available"
    return {"catalog": items, "total": len(items)}


@router.post("/install", status_code=201, summary="Install a skill and create its files")
def install_skill(body: InstallIn, user: dict = Depends(deps.require("skill:write")),
                  request: Request = None):
    template = skill_catalog.find(body.code)
    skill_type = body.type or (template or {}).get("type") or "http"
    if skill_type not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    _validate_link(body.server_id)
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
        "server_id": body.server_id, "health": "unknown",
        "installed_at": now, "updated_at": now,
    }
    if existing:
        db.update("mcp_skills", existing["id"], fields)
        skill_id = existing["id"]
    else:
        skill_id = db.insert("mcp_skills", {**fields, "code": body.code,
                                             "auth_config": {}, "tools": [],
                                             "created_at": now})
    created = skill_files.install_files({**fields, "id": skill_id, "code": body.code})
    deps.audit(user["username"], "skill.install", f"skill:{body.code}",
               {"type": skill_type, "files": created, "source": body.source}, request=request)
    return {**_out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))),
            "files_created": created}


@router.post("", status_code=201, summary="Create a custom skill")
def create_skill(body: SkillIn, user: dict = Depends(deps.require("skill:write")),
                 request: Request = None):
    if body.type not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    _validate_link(body.server_id)
    if db.q1("SELECT id FROM mcp_skills WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Skill code already exists")
    now = db.now()
    sid = db.insert("mcp_skills", {**body.model_dump(), "enabled": int(body.enabled),
                                   "status": "installed", "health": "unknown",
                                   "installed_at": now, "updated_at": now,
                                   "created_at": now})
    skill_files.install_files({**body.model_dump(), "id": sid})
    deps.audit(user["username"], "skill.create", f"skill:{body.code}",
               {"type": body.type}, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (sid,)))


# --------------------------------------------------------------------------- #
# Single skill: detail, update, lifecycle
# --------------------------------------------------------------------------- #
@router.get("/{skill_id}", summary="Get a skill with its files and manifest")
def get_skill(skill_id: int, _user: dict = Depends(deps.require("skill:read"))):
    skill = _skill(skill_id)
    return {**skill, "files": skill_files.list_files(skill_id),
            "disk_path": str(skill_files.skill_dir(skill["code"]))}


@router.put("/{skill_id}", summary="Update a skill")
def update_skill(skill_id: int, body: SkillPatch,
                 user: dict = Depends(deps.require("skill:write")), request: Request = None):
    _skill(skill_id)
    patch = body.model_dump(exclude_none=True)
    _validate_link(patch.get("server_id"))
    if "enabled" in patch:
        patch["enabled"] = int(patch["enabled"])
        patch.setdefault("status", "installed" if patch["enabled"] else "disabled")
    if patch.get("type") and patch["type"] not in SKILL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {SKILL_TYPES}")
    if patch.get("status") and patch["status"] not in SKILL_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {SKILL_STATUSES}")
    patch["updated_at"] = db.now()
    db.update("mcp_skills", skill_id, patch)
    deps.audit(user["username"], "skill.update", f"skill:{skill_id}", patch, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,)))


@router.delete("/{skill_id}", summary="Permanently remove a skill and its files")
def delete_skill(skill_id: int, user: dict = Depends(deps.require("skill:write")),
                 request: Request = None):
    row = db.q1("SELECT code FROM mcp_skills WHERE id=?", (skill_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_files.clear_files(skill_id, row["code"])
    db.delete("mcp_skills", skill_id)
    deps.audit(user["username"], "skill.delete", f"skill:{row['code']}", {}, request=request)
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
    deps.audit(user["username"], f"skill.{action}", f"skill:{skill['code']}",
               {"status": patch["status"], "files": created}, request=request)
    return {**_out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,))),
            "action": action, "files_affected": created}


@router.post("/{skill_id}/enable", summary="Enable an installed skill")
def enable_skill(skill_id: int, user: dict = Depends(deps.require("skill:write")),
                 request: Request = None):
    return _lifecycle(skill_id, "enable", user, request)


@router.post("/{skill_id}/disable", summary="Disable a skill without uninstalling it")
def disable_skill(skill_id: int, user: dict = Depends(deps.require("skill:write")),
                  request: Request = None):
    return _lifecycle(skill_id, "disable", user, request)


@router.post("/{skill_id}/uninstall", summary="Uninstall a skill (keeps registry entry)")
def uninstall_skill(skill_id: int, user: dict = Depends(deps.require("skill:write")),
                    request: Request = None):
    return _lifecycle(skill_id, "uninstall", user, request)


@router.post("/{skill_id}/reinstall", summary="Reinstall a previously uninstalled skill")
def reinstall_skill(skill_id: int, user: dict = Depends(deps.require("skill:write")),
                    request: Request = None):
    return _lifecycle(skill_id, "reinstall", user, request)


@router.post("/{skill_id}/sync", summary="Sync tools from the linked MCP server")
def sync_skill(skill_id: int, user: dict = Depends(deps.require("skill:write")),
               request: Request = None):
    skill = _skill(skill_id)
    server_id = skill.get("server_id")
    if not server_id:
        raise HTTPException(status_code=400, detail="Skill is not linked to an MCP server")
    result = mcp_servers.sync(int(server_id))
    tools = result["tools"]
    db.update("mcp_skills", skill_id, {"tools": tools, "health": result["health"],
                                       "updated_at": db.now()})
    deps.audit(user["username"], "skill.sync", f"skill:{skill['code']}",
               {"server_id": server_id, "tools": len(tools)}, request=request)
    return {**result, "skill": skill["code"], "linked_server": server_id}


# --------------------------------------------------------------------------- #
# Visual editing: rendered previews, structured manifest editing, batch saves
# --------------------------------------------------------------------------- #
class ManifestIn(BaseModel):
    manifest: dict


class BatchFilesIn(BaseModel):
    files: list[dict] = Field(default_factory=list)


def _md_html(text: str) -> str:
    """Small, XSS-safe Markdown renderer for skill documentation previews."""
    import html
    import re
    out: list[str] = []
    in_code = False
    for raw in (text or "").splitlines():
        if raw.startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(raw) + "\n")
            continue
        line = html.escape(raw)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)
        if raw.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif raw.startswith("## "):
            out.append(f"<h3>{line[3:]}</h3>")
        elif raw.startswith("# "):
            out.append(f"<h2>{line[2:]}</h2>")
        elif raw.lstrip().startswith(("- ", "* ")):
            out.append(f"<li>{line[raw.index(' ') + 1:]}</li>")
        elif raw.strip():
            out.append(f"<p>{line}</p>")
        else:
            out.append("")
    if in_code:
        out.append("</code></pre>")
    return "".join(out)


@router.get("/{skill_id}/preview", summary="Rendered, read-only visual preview of a skill")
def preview_skill(skill_id: int, _user: dict = Depends(deps.require("skill:read"))):
    skill = _skill(skill_id)
    files = {f["path"]: f for f in skill_files.list_files(skill_id)}
    def content(path: str) -> str:
        row = skill_files.get_file(skill_id, path)
        return (row or {}).get("content") or ""
    manifest = {**(skill.get("manifest") or {}), "code": skill["code"],
                "name": skill["name"], "version": skill.get("version") or "1.0.0"}
    return {
        "skill": skill, "manifest": manifest,
        "capabilities": (skill.get("manifest") or {}).get("capabilities") or [],
        "skill_md_html": _md_html(content("SKILL.md")),
        "readme_html": _md_html(content("README.md")),
        "tools": skill.get("tools") or [],
        "files": [{"path": p, "size": f["size"], "language": f["language"]}
                  for p, f in files.items()],
        "has_documentation": bool(files.get("SKILL.md") or files.get("README.md")),
    }


@router.put("/{skill_id}/manifest", summary="Save a visually edited skill manifest")
def save_manifest(skill_id: int, body: ManifestIn,
                  user: dict = Depends(deps.require("skill:write")), request: Request = None):
    skill = _skill(skill_id)
    import json
    manifest = {**(skill.get("manifest") or {}), **body.manifest}
    manifest.setdefault("schema", "ailp.mcp.skill/1")
    patch: dict = {"manifest": manifest, "updated_at": db.now()}
    for key, column in (("name", "name"), ("description", "description"), ("version", "version")):
        if body.manifest.get(key):
            patch[column] = body.manifest[key]
    db.update("mcp_skills", skill_id, patch)
    skill_files.put_file(skill_id, skill["code"], "manifest.json",
                         json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    deps.audit(user["username"], "skill.manifest.save", f"skill:{skill['code']}",
               {"keys": list(body.manifest)}, request=request)
    return _out(db.q1("SELECT * FROM mcp_skills WHERE id=?", (skill_id,)))


@router.put("/{skill_id}/files/batch", summary="Save multiple skill files in one request")
def batch_save_files(skill_id: int, body: BatchFilesIn,
                     user: dict = Depends(deps.require("skill:write")), request: Request = None):
    skill = _skill(skill_id)
    saved: list[str] = []
    for item in body.files[:50]:
        path = str(item.get("path") or "")
        if not path:
            continue
        try:
            skill_files.put_file(skill_id, skill["code"], path, str(item.get("content") or ""))
            saved.append(path)
        except ValueError:
            continue
    deps.audit(user["username"], "skill.files.batch", f"skill:{skill['code']}",
               {"files": saved}, request=request)
    return {"ok": True, "saved": saved, "total": len(saved)}


# --------------------------------------------------------------------------- #
# Editable skill files  (static /reload MUST precede /{path:path})
# --------------------------------------------------------------------------- #
@router.get("/{skill_id}/files", summary="List editable files of a skill")
def list_skill_files(skill_id: int, _user: dict = Depends(deps.require("skill:read"))):
    skill = _skill(skill_id)
    files = skill_files.list_files(skill_id)
    return {"files": files, "total": len(files),
            "disk_path": str(skill_files.skill_dir(skill["code"]))}


@router.post("/{skill_id}/files/reload", summary="Reload skill files from the disk mirror")
def reload_skill_files(skill_id: int, user: dict = Depends(deps.require("skill:write")),
                       request: Request = None):
    skill = _skill(skill_id)
    loaded = skill_files.reload_from_disk(skill)
    deps.audit(user["username"], "skill.files.reload", f"skill:{skill['code']}",
               {"loaded": loaded}, request=request)
    return {"ok": True, "loaded": loaded}


@router.get("/{skill_id}/files/{path:path}", summary="Read one skill file")
def read_skill_file(skill_id: int, path: str,
                    _user: dict = Depends(deps.require("skill:read"))):
    _skill(skill_id)
    return _file_or_404(skill_id, path)


@router.put("/{skill_id}/files/{path:path}", summary="Create or update a skill file")
def write_skill_file(skill_id: int, path: str, body: FileIn,
                     user: dict = Depends(deps.require("skill:write")), request: Request = None):
    skill = _skill(skill_id)
    try:
        row = skill_files.put_file(skill_id, skill["code"], path, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "skill.files.write", f"skill:{skill['code']}",
               {"path": row["path"], "size": row["size"]}, request=request)
    return row


@router.delete("/{skill_id}/files/{path:path}", summary="Delete a skill file")
def delete_skill_file(skill_id: int, path: str,
                      user: dict = Depends(deps.require("skill:write")), request: Request = None):
    skill = _skill(skill_id)
    try:
        removed = skill_files.delete_file(skill_id, skill["code"], path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Skill file not found")
    deps.audit(user["username"], "skill.files.delete", f"skill:{skill['code']}",
               {"path": path}, request=request)
    return {"ok": True}
