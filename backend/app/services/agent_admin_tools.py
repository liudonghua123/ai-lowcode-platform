"""Administrative / system-wide tools exposed to AI agents.

Keeping these in a separate module means new platform capabilities can be added
to the agent tool catalog without touching the core dispatcher. Every spec
declares the permission it requires; ``mcp_tools`` filters the catalog per user
and re-checks on invocation, so an agent can only do what its human operator is
allowed to do (query, apply, approve, configure, create, ...).
"""
from __future__ import annotations

import json
from collections.abc import Callable

from .. import db
from . import mcp_servers, model_providers, registry, skill_catalog, skill_files, skill_hubs


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


def _s(desc: str, properties: dict, required: list[str] | None = None,
       permission: str | None = None) -> dict:
    return {"name": "", "description": desc, "inputSchema": _obj(properties, required),
            "permission": permission}


SPECS: list[dict] = [
    # --- MCP server registry ------------------------------------------------ #
    {**_s("List registered MCP servers and their health.",
          {"enabled_only": {"type": "boolean"}}, permission="mcp:read"), "name": "list_mcp_servers"},
    {**_s("Get one MCP server by code.", {"code": {"type": "string"}},
          ["code"], "mcp:read"), "name": "get_mcp_server"},
    {**_s("Register a new MCP server.",
          {"code": {"type": "string"}, "name": {"type": "string"},
           "transport": {"type": "string", "description": "http | sse | stdio"},
           "endpoint": {"type": "string"}, "command": {"type": "string"},
           "description": {"type": "string"}}, ["code", "name"], "mcp:write"),
     "name": "create_mcp_server"},
    {**_s("Probe an MCP server and refresh its declared tool list.",
          {"code": {"type": "string"}}, ["code"], "mcp:write"), "name": "sync_mcp_server"},
    # --- Skills registry ---------------------------------------------------- #
    {**_s("List installed skills (independent of MCP servers).",
          {"status": {"type": "string"}}, permission="skill:read"), "name": "list_skills"},
    {**_s("Get one skill with manifest, tools and files.",
          {"code": {"type": "string"}}, ["code"], "skill:read"), "name": "get_skill"},
    {**_s("Install a skill from the built-in catalog.",
          {"code": {"type": "string"}, "name": {"type": "string"}},
          ["code"], "skill:write"), "name": "install_skill"},
    {**_s("Update an installed skill (enable / disable / rename / describe).",
          {"code": {"type": "string"}, "patch": {"type": "object"}},
          ["code", "patch"], "skill:write"), "name": "update_skill"},
    {**_s("List the editable files of a skill.",
          {"code": {"type": "string"}}, ["code"], "skill:read"), "name": "list_skill_files"},
    {**_s("Read one editable skill file.",
          {"code": {"type": "string"}, "path": {"type": "string"}},
          ["code", "path"], "skill:read"), "name": "read_skill_file"},
    {**_s("Create or overwrite one editable skill file (visual editor backing API).",
          {"code": {"type": "string"}, "path": {"type": "string"},
           "content": {"type": "string"}},
          ["code", "path", "content"], "skill:write"), "name": "write_skill_file"},
    # --- Skill Hubs --------------------------------------------------------- #
    {**_s("List skill hubs (registries to discover skills from).",
          {}, permission="skill:read"), "name": "list_skill_hubs"},
    {**_s("Search skills across all enabled hubs by keyword / category.",
          {"q": {"type": "string"}, "category": {"type": "string"}},
          permission="skill:read"), "name": "search_skill_hub"},
    {**_s("Install a skill discovered on a hub into the local registry.",
          {"code": {"type": "string"}, "hub_code": {"type": "string"}},
          ["code"], "skill:write"), "name": "add_skill_from_hub"},
    {**_s("Create or update a skill hub.",
          {"hub_code": {"type": "string"}, "name": {"type": "string"},
           "kind": {"type": "string", "description": "builtin | remote"},
           "url": {"type": "string"}, "enabled": {"type": "boolean"}},
          ["hub_code"], "skill:write"), "name": "manage_skill_hub"},
    # --- Settings & AI model services --------------------------------------- #
    {**_s("List configured AI model service providers.",
          {}, permission="settings:read"), "name": "list_ai_providers"},
    {**_s("Read platform settings.", {}, permission="settings:read"),
     "name": "get_platform_settings"},
    {**_s("Update platform settings (merged with existing values).",
          {"settings": {"type": "object"}}, ["settings"], "settings:write"),
     "name": "update_platform_settings"},
    # --- RBAC / organization ------------------------------------------------ #
    {**_s("List roles and their permissions.", {}, permission="rbac:read"),
     "name": "list_roles"},
    {**_s("List member groups used by group-based approver rules.",
          {}, permission="rbac:read"), "name": "list_user_groups"},
    {**_s("Create a member group.",
          {"code": {"type": "string"}, "name": {"type": "string"},
           "members": {"type": "array", "items": {"type": "string"}},
           "tags": {"type": "array", "items": {"type": "string"}}},
          ["code", "name"], "rbac:write"), "name": "create_user_group"},
    {**_s("List approval delegation rules.", {}, permission="rbac:read"),
     "name": "list_delegations"},
    {**_s("Create an approval delegation (while active, tasks go to the agent).",
          {"principal": {"type": "string"}, "agent": {"type": "string"},
           "scope": {"type": "string"}, "ends_at": {"type": "string"}},
          ["principal", "agent"], "rbac:write"), "name": "create_delegation"},
    # --- Audit / knowledge -------------------------------------------------- #
    {**_s("Query recent audit logs.",
          {"actor": {"type": "string"}, "action": {"type": "string"},
           "limit": {"type": "integer"}}, permission="audit:read"),
     "name": "query_audit_logs"},
    {**_s("List knowledge base documents.",
          {"collection_code": {"type": "string"}, "limit": {"type": "integer"}},
          permission="knowledge:read"), "name": "list_kb_documents"},
    # --- Design-time assets & registry -------------------------------------- #
    {**_s("Get the extensible form component / workflow node registry.",
          {"kind": {"type": "string", "description": "components | nodes | all"}},
          permission=None), "name": "list_registry"},
    {**_s("Create a new form definition.",
          {"code": {"type": "string"}, "name": {"type": "string"},
           "description": {"type": "string"}, "schema": {"type": "array",
           "items": {"type": "object"}}}, ["code", "name"], "form:write"),
     "name": "create_form"},
    {**_s("Create a new workflow definition with a start/end graph.",
          {"code": {"type": "string"}, "name": {"type": "string"},
           "description": {"type": "string"}}, ["code", "name"], "workflow:write"),
     "name": "create_workflow"},
    {**_s("Register a custom component or node type at runtime.",
          {"kind": {"type": "string", "description": "components | nodes"},
           "spec": {"type": "object"}}, ["kind", "spec"], "form:write"),
     "name": "register_custom_type"},
    {**_s("Read or update my notification preferences.",
          {"action": {"type": "string", "description": "get | set"},
           "events": {"type": "object"}}, permission=None),
     "name": "notification_prefs"},
    {**_s("Summary of every capability the current role can use.",
          {}, permission=None), "name": "my_capabilities"},
]

PERMISSIONS: dict[str, str | None] = {s["name"]: s.get("permission") for s in SPECS}
WRITE_TOOLS = {s["name"] for s in SPECS
               if (s.get("permission") or "").rsplit(":", 1)[-1]
               in {"write", "publish", "config", "delete", "submit", "run"}}


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def _actor() -> str:
    from . import mcp_tools
    return (mcp_tools.current_user() or {}).get("username") or "agent"


def _skill_row(code: str) -> dict | None:
    return db.q1("SELECT * FROM mcp_skills WHERE code=?", (code,))


def _list_mcp_servers(a: dict) -> dict:
    rows = mcp_servers.rows(enabled_only=bool(a.get("enabled_only")))
    return {"servers": rows, "total": len(rows), "stats": mcp_servers.stats()}


def _get_mcp_server(a: dict) -> dict:
    row = mcp_servers.get_by_code(a["code"])
    if not row:
        raise ValueError(f"MCP server not found: {a['code']}")
    return {"server": row}


def _create_mcp_server(a: dict) -> dict:
    code = a["code"]
    if mcp_servers.get_by_code(code):
        raise ValueError("MCP server code already exists")
    transport = a.get("transport") or ("stdio" if a.get("command") else "http")
    now = db.now()
    sid = db.insert("mcp_servers", {
        "code": code, "name": a["name"], "description": a.get("description") or "",
        "transport": transport, "endpoint": a.get("endpoint"), "command": a.get("command"),
        "auth_config": {}, "tools": [], "enabled": 1, "health": "unknown",
        "status": "active", "source": "agent", "created_by": _actor(),
        "created_at": now, "updated_at": now})
    return {"server": mcp_servers.get(sid), "created": True}


def _sync_mcp_server(a: dict) -> dict:
    row = mcp_servers.get_by_code(a["code"])
    if not row:
        raise ValueError(f"MCP server not found: {a['code']}")
    return mcp_servers.sync(int(row["id"]))


def _list_skills(a: dict) -> dict:
    status = a.get("status")
    rows = db.q("SELECT * FROM mcp_skills" + (" WHERE status=?" if status else "") +
                " ORDER BY id", (status,) if status else ())
    out = []
    for r in rows:
        r = db.loads(r, "tools", "auth_config", "manifest") or {}
        out.append({k: r.get(k) for k in
                    ("id", "code", "name", "type", "version", "status", "source",
                     "description", "hub_id", "server_id")} |
                   {"enabled": bool(r.get("enabled")), "tool_count": len(r.get("tools") or [])})
    return {"skills": out, "total": len(out)}


def _get_skill(a: dict) -> dict:
    row = _skill_row(a["code"])
    if not row:
        raise ValueError(f"Skill not found: {a['code']}")
    skill = db.loads(row, "tools", "auth_config", "manifest") or {}
    skill.pop("auth_config", None)
    return {"skill": skill, "files": skill_files.list_files(skill["id"])}


def _install_skill(a: dict) -> dict:
    code = a["code"]
    spec = skill_catalog.find(code)
    if not spec:
        raise ValueError(f"Unknown catalog skill: {code}")
    existing = _skill_row(code)
    if existing and (existing.get("status") or "installed") != "uninstalled":
        raise ValueError("Skill already installed")
    now = db.now()
    fields = {"name": a.get("name") or spec["name"], "type": spec["type"],
              "endpoint": spec.get("endpoint"), "command": spec.get("command"),
              "version": spec["version"], "description": spec["description"],
              "manifest": {"schema": "ailp.mcp.skill/1", "capabilities": spec["capabilities"]},
              "enabled": 1, "status": "installed", "source": "agent",
              "health": "unknown", "installed_at": now, "updated_at": now}
    if existing:
        db.update("mcp_skills", existing["id"], fields)
        sid = existing["id"]
    else:
        sid = db.insert("mcp_skills", {**fields, "code": code,
                                       "auth_config": {}, "tools": [], "created_at": now})
    created = skill_files.install_files({**fields, "id": sid, "code": code})
    return {"skill": code, "installed": True, "files_created": created}


def _update_skill(a: dict) -> dict:
    row = _skill_row(a["code"])
    if not row:
        raise ValueError(f"Skill not found: {a['code']}")
    allowed = {"name", "description", "version", "enabled", "status", "endpoint", "command"}
    patch = {k: v for k, v in (a.get("patch") or {}).items() if k in allowed}
    if "enabled" in patch:
        patch["enabled"] = int(bool(patch["enabled"]))
    patch["updated_at"] = db.now()
    db.update("mcp_skills", row["id"], patch)
    return {"skill": a["code"], "updated": patch}


def _list_skill_files(a: dict) -> dict:
    row = _skill_row(a["code"])
    if not row:
        raise ValueError(f"Skill not found: {a['code']}")
    files = skill_files.list_files(row["id"])
    return {"files": files, "total": len(files)}


def _read_skill_file(a: dict) -> dict:
    row = _skill_row(a["code"])
    if not row:
        raise ValueError(f"Skill not found: {a['code']}")
    f = skill_files.get_file(row["id"], a["path"])
    if not f:
        raise ValueError(f"File not found: {a['path']}")
    return {"path": f["path"], "content": f["content"], "language": f["language"]}


def _write_skill_file(a: dict) -> dict:
    row = _skill_row(a["code"])
    if not row:
        raise ValueError(f"Skill not found: {a['code']}")
    f = skill_files.put_file(row["id"], row["code"], a["path"], a.get("content") or "")
    return {"path": f["path"], "size": f["size"]}


def _list_skill_hubs(_a: dict) -> dict:
    return {"hubs": skill_hubs.rows(), "stats": skill_hubs.stats(),
            "categories": skill_hubs.CATEGORIES}


def _search_skill_hub(a: dict) -> dict:
    return skill_hubs.search_all(a.get("q") or "", a.get("category"))


def _add_skill_from_hub(a: dict) -> dict:
    hubs = skill_hubs.rows(enabled_only=True)
    code = a.get("hub_code")
    candidates = [h for h in hubs if not code or h["code"] == code]
    last_error = None
    for hub in candidates:
        try:
            return skill_hubs.install(hub["id"], a["code"])
        except (ValueError, skill_hubs.HubError) as exc:
            last_error = str(exc)
    raise ValueError(last_error or "No enabled hub contains that skill")


def _manage_skill_hub(a: dict) -> dict:
    code = a["hub_code"]
    existing = skill_hubs.get_by_code(code)
    if existing:
        return {"hub": skill_hubs.update(existing["id"],
                                         {k: a[k] for k in ("name", "kind", "url", "enabled")
                                          if k in a}), "updated": True}
    return {"hub": skill_hubs.create({"code": code, "name": a.get("name") or code,
                                      "kind": a.get("kind") or "remote",
                                      "url": a.get("url"),
                                      "enabled": a.get("enabled", True)}, actor=_actor()),
            "created": True}


def _list_ai_providers(_a: dict) -> dict:
    rows = db.q("SELECT id,code,name,category,vendor,model,enabled,is_default "
                "FROM ai_providers ORDER BY category,id")
    return {"providers": [dict(r, enabled=bool(r["enabled"]),
                               is_default=bool(r["is_default"])) for r in rows],
            "total": len(rows), "meta": model_providers.meta()}


def _get_platform_settings(_a: dict) -> dict:
    row = db.q1("SELECT value,updated_at FROM settings WHERE key='platform_settings'")
    value = {}
    if row:
        try:
            value = json.loads(row["value"])
        except (ValueError, TypeError):
            value = {}
    return {"settings": value, "updated_at": row["updated_at"] if row else None}


def _update_platform_settings(a: dict) -> dict:
    current = _get_platform_settings({})["settings"]
    merged = {**current, **(a.get("settings") or {})}
    db.run("INSERT INTO settings(key,value,updated_at) VALUES('platform_settings',?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
           (db.dumps(merged), db.now()))
    return {"settings": merged, "updated": True}


def _list_roles(_a: dict) -> dict:
    rows = db.q("SELECT id,code,name,description,builtin,mfa_required,permission_ids "
                "FROM roles ORDER BY id")
    return {"roles": [db.loads(r, "permission_ids") for r in rows], "total": len(rows)}


def _list_user_groups(_a: dict) -> dict:
    rows = db.q("SELECT id,code,name,description,members,tags,enabled FROM user_groups ORDER BY id")
    return {"groups": [db.loads(r, "members", "tags") for r in rows], "total": len(rows)}


def _create_user_group(a: dict) -> dict:
    code = a["code"]
    if db.q1("SELECT id FROM user_groups WHERE code=?", (code,)):
        raise ValueError("Group code already exists")
    gid = db.insert("user_groups", {"code": code, "name": a["name"], "description": "",
                                    "members": a.get("members") or [],
                                    "tags": a.get("tags") or [], "enabled": 1,
                                    "created_by": _actor(), "created_at": db.now()})
    return {"group": db.loads(db.q1("SELECT * FROM user_groups WHERE id=?", (gid,)),
                              "members", "tags"), "created": True}


def _list_delegations(_a: dict) -> dict:
    rows = db.q("SELECT * FROM flow_delegations ORDER BY id DESC LIMIT 100")
    return {"delegations": rows, "total": len(rows)}


def _create_delegation(a: dict) -> dict:
    did = db.insert("flow_delegations", {"principal": a["principal"], "agent": a["agent"],
                                         "scope": a.get("scope"), "starts_at": db.now(),
                                         "ends_at": a.get("ends_at"), "enabled": 1,
                                         "created_by": _actor(), "created_at": db.now()})
    return {"delegation_id": did, "created": True}


def _query_audit_logs(a: dict) -> dict:
    clauses, params = [], []
    for key in ("actor", "action"):
        if a.get(key):
            clauses.append(f"{key} LIKE ?")
            params.append(f"%{a[key]}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit = max(1, min(int(a.get("limit") or 20), 200))
    rows = db.q("SELECT * FROM audit_logs" + where + " ORDER BY id DESC LIMIT ?",
                tuple(params) + (limit,))
    return {"logs": [db.loads(r, "detail") for r in rows], "total": len(rows)}


def _list_kb_documents(a: dict) -> dict:
    limit = max(1, min(int(a.get("limit") or 20), 200))
    if a.get("collection_code"):
        rows = db.q("SELECT d.* FROM kb_documents d JOIN kb_collections c "
                    "ON d.collection_id=c.id WHERE c.code=? ORDER BY d.id DESC LIMIT ?",
                    (a["collection_code"], limit))
    else:
        rows = db.q("SELECT * FROM kb_documents ORDER BY id DESC LIMIT ?", (limit,))
    return {"documents": [{k: r.get(k) for k in
                           ("id", "title", "source", "status", "file_type", "created_at")}
                          for r in rows], "total": len(rows)}


def _list_registry(a: dict) -> dict:
    payload = registry.registry_payload()
    kind = a.get("kind")
    if kind == "components":
        return {"components": payload["components"], "total": payload["component_count"]}
    if kind == "nodes":
        return {"nodes": payload["nodes"], "total": payload["node_count"]}
    return payload


def _create_form(a: dict) -> dict:
    code = a["code"]
    if db.q1("SELECT id FROM forms WHERE code=?", (code,)):
        raise ValueError("Form code already exists")
    now = db.now()
    fid = db.insert("forms", {"code": code, "name": a["name"],
                              "description": a.get("description") or "",
                              "status": "draft", "schema": a.get("schema") or [],
                              "layout": {}, "print_template": {}, "settings": {},
                              "version": 1, "created_by": _actor(),
                              "created_at": now, "updated_at": now})
    return {"form": {"id": fid, "code": code, "name": a["name"], "status": "draft"},
            "created": True}


def _create_workflow(a: dict) -> dict:
    code = a["code"]
    if db.q1("SELECT id FROM workflows WHERE code=?", (code,)):
        raise ValueError("Workflow code already exists")
    graph = {"nodes": [{"id": "n1", "type": "start", "name": "Start", "x": 60, "y": 180,
                        "config": {}},
                       {"id": "n2", "type": "end", "name": "End", "x": 420, "y": 180,
                        "config": {}}],
             "edges": [{"id": "e1", "source": "n1", "target": "n2"}]}
    now = db.now()
    wid = db.insert("workflows", {"code": code, "name": a["name"],
                                  "description": a.get("description") or "",
                                  "status": "draft", "graph": graph, "version": 1,
                                  "created_by": _actor(),
                                  "created_at": now, "updated_at": now})
    return {"workflow": {"id": wid, "code": code, "name": a["name"], "status": "draft"},
            "created": True}


def _register_custom_type(a: dict) -> dict:
    kind = a["kind"]
    if kind not in {"components", "nodes"}:
        raise ValueError("kind must be components | nodes")
    spec = a.get("spec") or {}
    key = "type" if kind == "nodes" else "code"
    if not spec.get(key):
        raise ValueError(f"spec.{key} is required")
    return {"registered": registry.register_custom(kind, spec),
            "total": len(registry.custom_components() if kind == "components"
                         else registry.custom_nodes())}


def _notification_prefs(a: dict) -> dict:
    from . import mcp_tools
    username = (mcp_tools.current_user() or {}).get("username")
    if not username:
        raise ValueError("Authentication required")
    if a.get("action") == "set":
        db.run("INSERT INTO notify_prefs(username,events,updated_at) VALUES(?,?,?) "
               "ON CONFLICT(username) DO UPDATE SET events=excluded.events, "
               "updated_at=excluded.updated_at",
               (username, db.dumps(a.get("events") or {}), db.now()))
        return {"updated": True, "events": a.get("events") or {}}
    row = db.q1("SELECT events,updated_at FROM notify_prefs WHERE username=?", (username,))
    return {"events": (db.loads(row, "events") or {}).get("events") or {} if row else {},
            "updated_at": row["updated_at"] if row else None}


def _my_capabilities(_a: dict) -> dict:
    from . import mcp_tools
    user = mcp_tools.current_user() or {}
    tools = mcp_tools.list_tools(user=user, include_external=False)
    # Use the same permission-derived domain grouping as the UI capability
    # matrix, so the agent's self-description matches what the user sees.
    matrix = mcp_tools.capability_matrix(user)
    groups = {domain: [t["name"] for t in info["tools"] if t["available"]]
              for domain, info in matrix["domains"].items()}
    return {"user": user.get("username"), "roles": user.get("role_codes"),
            "data_scope": user.get("data_scope"), "tool_count": len(tools),
            "capability_groups": groups,
            "total_registered": matrix["total_tools"],
            "permission_driven": matrix["permission_driven"]}


HANDLERS: dict[str, Callable[[dict], dict]] = {
    "list_mcp_servers": _list_mcp_servers, "get_mcp_server": _get_mcp_server,
    "create_mcp_server": _create_mcp_server, "sync_mcp_server": _sync_mcp_server,
    "list_skills": _list_skills, "get_skill": _get_skill,
    "install_skill": _install_skill, "update_skill": _update_skill,
    "list_skill_files": _list_skill_files, "read_skill_file": _read_skill_file,
    "write_skill_file": _write_skill_file,
    "list_skill_hubs": _list_skill_hubs, "search_skill_hub": _search_skill_hub,
    "add_skill_from_hub": _add_skill_from_hub, "manage_skill_hub": _manage_skill_hub,
    "list_ai_providers": _list_ai_providers,
    "get_platform_settings": _get_platform_settings,
    "update_platform_settings": _update_platform_settings,
    "list_roles": _list_roles, "list_user_groups": _list_user_groups,
    "create_user_group": _create_user_group, "list_delegations": _list_delegations,
    "create_delegation": _create_delegation, "query_audit_logs": _query_audit_logs,
    "list_kb_documents": _list_kb_documents, "list_registry": _list_registry,
    "create_form": _create_form, "create_workflow": _create_workflow,
    "register_custom_type": _register_custom_type,
    "notification_prefs": _notification_prefs, "my_capabilities": _my_capabilities,
}
