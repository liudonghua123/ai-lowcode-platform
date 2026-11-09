"""Skill Hub registry: discover, search and install skills from hubs.

A hub is either ``builtin`` (ships with the platform, fully offline) or
``remote`` (an HTTP skill registry exposing ``/api/skills`` and
``/api/skills/<code>``). Remote indexes are cached in ``settings`` so a hub
going offline never breaks discovery. Installed skills record ``hub_id`` and a
``hub:<code>`` source, but the Skills registry remains fully independent from
the MCP server registry.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from .. import db
from . import skill_catalog, skill_files

BUILTIN_KIND = "builtin"
REMOTE_KIND = "remote"
KINDS = [BUILTIN_KIND, REMOTE_KIND]

# Extra marketplace-style skills offered only through the builtin extended hub.
# They demonstrate hub discovery without requiring network access.
HUB_EXTRA_SKILLS: list[dict] = [
    {"code": "pdf-extract", "name": "PDF Extract / PDF 解析", "type": "stdio",
     "version": "1.3.0", "category": "document", "author": "AILP Labs", "downloads": 2841,
     "description": "Extract text, tables and metadata from PDF documents.",
     "command": "uvx mcp-server-pdf --workspace ./data",
     "capabilities": ["pdf", "tables", "metadata"],
     "tools": [{"name": "extract_pdf", "description": "Extract text from a PDF"},
               {"name": "pdf_tables", "description": "Extract tables from a PDF"}]},
    {"code": "excel-tools", "name": "Excel Tools / 表格处理", "type": "stdio",
     "version": "2.1.0", "category": "data", "author": "AILP Labs", "downloads": 1960,
     "description": "Read and transform XLSX/CSV workbooks with formula helpers.",
     "command": "npx -y @ailp/mcp-excel", "capabilities": ["read", "write", "pivot"],
     "tools": [{"name": "read_sheet", "description": "Read a worksheet range"},
               {"name": "write_sheet", "description": "Write a worksheet range"}]},
    {"code": "slack-notify", "name": "Slack Notify / Slack 通知", "type": "http",
     "version": "1.0.4", "category": "integration", "author": "Community", "downloads": 873,
     "description": "Post workflow notifications into Slack channels.",
     "endpoint": "http://127.0.0.1:9210/mcp", "capabilities": ["notify", "message"],
     "tools": [{"name": "post_message", "description": "Post a channel message"}]},
    {"code": "translate", "name": "Translate / 多语翻译", "type": "http",
     "version": "0.8.2", "category": "ai", "author": "Community", "downloads": 1522,
     "description": "Translate text between zh/en/ja with glossary support.",
     "endpoint": "http://127.0.0.1:9211/mcp", "capabilities": ["translate", "detect"],
     "tools": [{"name": "translate_text", "description": "Translate a text"}]},
    {"code": "chart-render", "name": "Chart Render / 图表渲染", "type": "http",
     "version": "1.1.1", "category": "data", "author": "AILP Labs", "downloads": 640,
     "description": "Render bar/line/pie charts as SVG or PNG from tabular data.",
     "endpoint": "http://127.0.0.1:9212/mcp", "capabilities": ["chart", "svg", "png"],
     "tools": [{"name": "render_chart", "description": "Render a chart"}]},
    {"code": "email-sender", "name": "Email Sender / 邮件发送", "type": "stdio",
     "version": "1.4.0", "category": "integration", "author": "Community", "downloads": 1108,
     "description": "Send templated SMTP emails with attachments.",
     "command": "uvx mcp-server-email --smtp ./config/smtp.json",
     "capabilities": ["send", "template", "attach"],
     "tools": [{"name": "send_email", "description": "Send an email"}]},
    {"code": "ocr-vision", "name": "OCR Vision / 图像识别", "type": "http",
     "version": "2.0.1", "category": "ai", "author": "AILP Labs", "downloads": 2033,
     "description": "OCR invoices, ID cards and screenshots into structured data.",
     "endpoint": "http://127.0.0.1:9213/mcp", "capabilities": ["ocr", "invoice", "idcard"],
     "tools": [{"name": "recognize_image", "description": "Recognize an image"}]},
    {"code": "cron-scheduler", "name": "Cron Scheduler / 定时调度", "type": "stdio",
     "version": "0.9.0", "category": "automation", "author": "Community", "downloads": 415,
     "description": "Schedule recurring agent tasks and workflow triggers.",
     "command": "npx -y @ailp/mcp-cron", "capabilities": ["schedule", "cron", "trigger"],
     "tools": [{"name": "schedule_job", "description": "Create a cron job"},
               {"name": "list_jobs", "description": "List scheduled jobs"}]},
]

CATEGORIES = ["ai", "data", "document", "integration", "automation", "utility"]


class HubError(Exception):
    """Raised when a remote hub cannot be reached and has no cache."""


# --------------------------------------------------------------------------- #
# Hub CRUD
# --------------------------------------------------------------------------- #
def _out(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = db.loads(row, "auth_config") or {}
    out["enabled"] = bool(out.get("enabled"))
    out.pop("auth_config", None)  # never leak tokens to non-admins
    out["installed_count"] = int(db.scalar(
        "SELECT COUNT(*) FROM mcp_skills WHERE hub_id=? AND status!='uninstalled'",
        (out["id"],)) or 0)
    return out


def rows(*, enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM skill_hubs" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
    return [_out(r) for r in db.q(sql)]


def get(hub_id: int) -> dict | None:
    return _out(db.q1("SELECT * FROM skill_hubs WHERE id=?", (hub_id,)))


def get_by_code(code: str) -> dict | None:
    return _out(db.q1("SELECT * FROM skill_hubs WHERE code=?", (code,)))


def _raw(hub_id: int) -> dict | None:
    return db.q1("SELECT * FROM skill_hubs WHERE id=?", (hub_id,))


def create(body: dict, actor: str = "admin") -> dict:
    code = str(body.get("code") or "").strip()
    if not code or not all(c.isalnum() or c in "_-" for c in code):
        raise ValueError("A valid alphanumeric hub code is required")
    if get_by_code(code):
        raise ValueError("Hub code already exists")
    kind = body.get("kind") or BUILTIN_KIND
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    now = db.now()
    hid = db.insert("skill_hubs", {
        "code": code, "name": body.get("name") or code,
        "description": body.get("description") or "", "url": body.get("url"),
        "kind": kind, "auth_config": body.get("auth_config") or {},
        "enabled": int(body.get("enabled", True)),
        "sync_interval_min": int(body.get("sync_interval_min") or 60),
        "skill_count": 0, "created_by": actor, "created_at": now, "updated_at": now,
    })
    return get(hid)


def update(hub_id: int, patch: dict) -> dict:
    if not get(hub_id):
        raise ValueError("Hub not found")
    patch = {k: v for k, v in patch.items()
             if k in {"name", "description", "url", "kind", "auth_config", "enabled",
                      "sync_interval_min"}}
    if patch.get("kind") and patch["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if "enabled" in patch:
        patch["enabled"] = int(patch["enabled"])
    patch["updated_at"] = db.now()
    db.update("skill_hubs", hub_id, patch)
    return get(hub_id)


def delete(hub_id: int) -> bool:
    return db.delete("skill_hubs", hub_id) > 0


def stats() -> dict:
    all_rows = rows()
    return {"total": len(all_rows), "enabled": sum(1 for h in all_rows if h["enabled"]),
            "builtin": sum(1 for h in all_rows if h["kind"] == BUILTIN_KIND),
            "remote": sum(1 for h in all_rows if h["kind"] == REMOTE_KIND),
            "installed_from_hub": int(db.scalar(
                "SELECT COUNT(*) FROM mcp_skills WHERE hub_id IS NOT NULL "
                "AND status!='uninstalled'") or 0)}


# --------------------------------------------------------------------------- #
# Index fetching / caching / search
# --------------------------------------------------------------------------- #
def _cache_key(code: str) -> str:
    return f"hub.cache.{code}"


def _read_cache(code: str) -> dict | None:
    row = db.q1("SELECT value FROM settings WHERE key=?", (_cache_key(code),))
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return None


def _write_cache(code: str, skills: list[dict]) -> None:
    payload = {"skills": skills, "synced_at": db.now(), "ts": int(time.time())}
    db.run("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
           (_cache_key(code), db.dumps(payload), db.now()))


def _normalize(spec: dict, hub: dict) -> dict:
    files = skill_catalog.build_files(
        code=spec["code"], name=spec.get("name") or spec["code"],
        skill_type=spec.get("type") or "http", version=spec.get("version") or "1.0.0",
        description=spec.get("description") or "", endpoint=spec.get("endpoint"),
        command=spec.get("command"),
        capabilities=spec.get("capabilities") or [],
        tools=spec.get("tools") or [])
    return {
        "code": spec["code"], "name": spec.get("name") or spec["code"],
        "type": spec.get("type") or "http", "version": spec.get("version") or "1.0.0",
        "description": spec.get("description") or "",
        "endpoint": spec.get("endpoint"), "command": spec.get("command"),
        "capabilities": spec.get("capabilities") or [],
        "category": spec.get("category") or "utility",
        "author": spec.get("author") or hub["name"],
        "downloads": int(spec.get("downloads") or 0),
        "tools": spec.get("tools") or [], "tool_count": len(spec.get("tools") or []),
        "files": [f["path"] for f in files], "_files": files,
        "hub_id": hub["id"], "hub_code": hub["code"], "hub_name": hub["name"],
    }


def _builtin_skills(hub: dict) -> list[dict]:
    if hub["code"] == "official":
        return [_normalize(s, hub) for s in skill_catalog.CATALOG_SPECS]
    # extended hub: catalog + marketplace-only extras
    specs = list(skill_catalog.CATALOG_SPECS) + [
        {k: v for k, v in s.items() if k not in {"category", "author", "downloads"}}
        for s in HUB_EXTRA_SKILLS]
    out = []
    for s in specs:
        extra = next((x for x in HUB_EXTRA_SKILLS if x["code"] == s["code"]), {})
        out.append(_normalize({**s, "category": extra.get("category", "utility"),
                               "author": extra.get("author", "AILP Labs"),
                               "downloads": extra.get("downloads", 0)}, hub))
    return out


def _remote_fetch(hub: dict, path: str) -> Any:
    if not hub.get("url"):
        raise HubError("Hub has no URL configured")
    raw = _raw(hub["id"])
    headers = {"Accept": "application/json"}
    token = (raw or {}).get("auth_config")
    try:
        cfg = json.loads(token) if isinstance(token, str) else (token or {})
    except (ValueError, TypeError):
        cfg = {}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    url = str(hub["url"]).rstrip("/") + path
    resp = requests.get(url, headers=headers, timeout=6)
    resp.raise_for_status()
    return resp.json()


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def index(hub: dict, *, refresh: bool = False) -> list[dict]:
    """Return the hub skill index (fresh when possible, cached on failure)."""
    cached = _read_cache(hub["code"])
    if hub["kind"] == BUILTIN_KIND:
        skills = _builtin_skills(hub)
        _write_cache(hub["code"], [_public(s) for s in skills])
        return skills
    if not hub["enabled"] and not refresh:
        return [_normalize(s, hub) for s in (cached or {}).get("skills", [])]
    try:
        data = _remote_fetch(hub, "/api/skills")
        specs = data.get("skills", data) if isinstance(data, dict) else data
        if not isinstance(specs, list):
            raise HubError("Invalid hub index payload")
        skills = [_normalize(s, hub) for s in specs if isinstance(s, dict) and s.get("code")]
        _write_cache(hub["code"], [_public(s) for s in skills])
        db.update("skill_hubs", hub["id"],
                  {"skill_count": len(skills), "last_sync_at": db.now(),
                   "last_error": None, "updated_at": db.now()})
        return skills
    except Exception as exc:
        db.update("skill_hubs", hub["id"], {"last_error": str(exc)[:200], "updated_at": db.now()})
        if cached:
            return [_normalize(s, hub) for s in cached.get("skills", [])
                    if isinstance(s, dict) and s.get("code")]
        raise HubError(f"Hub unreachable and no cache available: {exc}") from exc


def sync(hub_id: int) -> dict:
    hub = get(hub_id)
    if not hub:
        raise ValueError("Hub not found")
    try:
        skills = index(hub, refresh=True)
        return {"ok": True, "hub": hub["code"], "count": len(skills),
                "synced_at": db.now(), "cached": False}
    except HubError as exc:
        return {"ok": False, "hub": hub["code"], "count": 0, "error": str(exc)}


def _match(item: dict, q: str, category: str | None) -> bool:
    if category and item.get("category") != category:
        return False
    if not q:
        return True
    hay = " ".join(str(item.get(k) or "") for k in
                   ("code", "name", "description", "category", "author")) + " " + \
        " ".join(str(x) for x in (item.get("capabilities") or []))
    return q.lower() in hay.lower()


def search_hub(hub_id: int, q: str = "", category: str | None = None) -> dict:
    hub = get(hub_id)
    if not hub:
        raise ValueError("Hub not found")
    try:
        items = index(hub)
        degraded = False
    except HubError:
        items, degraded = [], True
    matched = [_public(x) for x in items if _match(x, q, category)]
    installed = {r["code"] for r in db.q(
        "SELECT code FROM mcp_skills WHERE status!='uninstalled'")}
    for m in matched:
        m["installed"] = m["code"] in installed
    return {"hub": hub, "skills": matched, "total": len(matched),
            "categories": sorted({x.get("category") for x in items if x.get("category")}),
            "degraded": degraded}


def search_all(q: str = "", category: str | None = None) -> dict:
    results, errors = [], []
    for hub in rows(enabled_only=True):
        try:
            r = search_hub(hub["id"], q, category)
            results.extend(r["skills"])
            if r["degraded"]:
                errors.append(f"{hub['code']}: cached index unavailable")
        except Exception as exc:
            errors.append(f"{hub['code']}: {exc}")
    # de-duplicate by code, preferring already-installed / higher download counts
    best: dict[str, dict] = {}
    for item in results:
        cur = best.get(item["code"])
        if not cur or (item.get("downloads") or 0) > (cur.get("downloads") or 0):
            best[item["code"]] = item
    return {"skills": sorted(best.values(), key=lambda x: -(x.get("downloads") or 0)),
            "total": len(best), "hubs": [h["code"] for h in rows(enabled_only=True)],
            "errors": errors, "categories": CATEGORIES}


def find(hub: dict, code: str) -> dict | None:
    for item in index(hub):
        if item["code"] == code:
            return item
    return None


def install(hub_id: int, code: str, overrides: dict | None = None) -> dict:
    """Install one hub skill into the local Skills registry with all its files."""
    hub = get(hub_id)
    if not hub:
        raise ValueError("Hub not found")
    spec = find(hub, code)
    if not spec:
        raise ValueError(f"Skill {code} not found in hub {hub['code']}")
    overrides = overrides or {}
    existing = db.q1("SELECT * FROM mcp_skills WHERE code=?", (code,))
    if existing and (existing.get("status") or "installed") != "uninstalled":
        raise ValueError("Skill is already installed")
    now = db.now()
    fields = {
        "name": overrides.get("name") or spec["name"],
        "type": overrides.get("type") or spec["type"],
        "endpoint": overrides.get("endpoint") or spec.get("endpoint"),
        "command": overrides.get("command") or spec.get("command"),
        "version": spec["version"], "description": spec["description"],
        "manifest": {"schema": "ailp.mcp.skill/1", "code": code, "name": spec["name"],
                     "version": spec["version"], "capabilities": spec["capabilities"],
                     "transport": spec["type"], "entrypoint": spec.get("endpoint") or spec.get("command"),
                     "license": "MIT", "hub": hub["code"], "author": spec.get("author")},
        "enabled": 1, "status": "installed", "source": f"hub:{hub['code']}",
        "hub_id": hub["id"], "health": "unknown", "installed_at": now,
        "updated_at": now,
    }
    if existing:
        db.update("mcp_skills", existing["id"], fields)
        skill_id = existing["id"]
    else:
        skill_id = db.insert("mcp_skills", {**fields, "code": code,
                                            "auth_config": {}, "tools": [],
                                            "created_at": now})
    # Materialize the hub-provided file set (manifest.json, SKILL.md, ...).
    created = skill_files.install_files({**fields, "id": skill_id, "code": code})
    for item in spec.get("_files") or []:
        skill_files.put_file(skill_id, code, item["path"], item["content"])
    db.update("mcp_skills", skill_id,
              {"tools": [{"name": t["name"], "description": t.get("description", "")}
                         for t in spec.get("tools") or []]})
    return {"skill": code, "hub": hub["code"], "skill_id": skill_id,
            "files_created": created, "source": fields["source"]}


def ensure_hubs() -> dict:
    """Idempotently provision the builtin hubs. Called at startup."""
    created = 0
    for code, name, desc in (
        ("official", "Official Skill Library / 官方技能库",
         "Platform-curated skills, available fully offline."),
        ("extended", "Skill Marketplace / 技能市场",
         "Extended marketplace with community and first-party skills."),
    ):
        if not get_by_code(code):
            create({"code": code, "name": name, "description": desc,
                    "kind": BUILTIN_KIND, "enabled": True}, actor="system")
            created += 1
    if not get_by_code("community-remote"):
        create({"code": "community-remote", "name": "Remote Registry / 远程 Hub 示例",
                "description": "Template for an external HTTP skill registry "
                               "(expects /api/skills). Disabled until a URL is set.",
                "kind": REMOTE_KIND, "url": None, "enabled": False}, actor="system")
        created += 1
    return {"created": created, **stats()}
