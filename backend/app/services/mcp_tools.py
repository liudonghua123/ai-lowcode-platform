"""Platform tool registry shared by the MCP server, AI agents and REST API.

Every capability exposed to an LLM is declared exactly once here, with a JSON
Schema input contract and a permission requirement.
"""
from __future__ import annotations

import contextvars
import json
import time
from collections.abc import Callable

from .. import db
from ..deps import has_permission
from . import agent_admin_tools, data_scope, mcp_journal, mcp_servers, rag, workflow_engine

_current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_current_user", default=None)
_call_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_call_context", default=None)


def bind_user(user: dict | None) -> None:
    _current_user.set(user)


def current_user() -> dict | None:
    return _current_user.get()


def bind_context(*, source: str = "internal", transport: str | None = None,
                 request_id: str | None = None, method: str = "tools/call",
                 actor: str | None = None, target: str | None = None) -> None:
    """Tag the current async context so call_tool can journal the invocation."""
    _call_context.set({"source": source, "transport": transport, "request_id": request_id,
                       "method": method, "actor": actor, "target": target})


def call_context() -> dict:
    return _call_context.get() or {}


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


TOOL_SPECS: list[dict] = [
    {"name": "list_forms", "description": "List form definitions (optionally filter by status).",
     "inputSchema": _obj({"status": {"type": "string", "description": "draft | published | archived"}})},
    {"name": "get_form", "description": "Get a full form definition including its field schema.",
     "inputSchema": _obj({"code": {"type": "string", "description": "Form code"}}, ["code"])},
    {"name": "submit_form", "description": "Submit data to a published form.",
     "inputSchema": _obj({"code": {"type": "string"}, "data": {"type": "object"}}, ["code", "data"])},
    {"name": "query_records", "description": "Query form submissions / business records.",
     "inputSchema": _obj({"form_code": {"type": "string"}, "limit": {"type": "integer"}})},
    {"name": "list_workflows", "description": "List workflow definitions.",
     "inputSchema": _obj({"status": {"type": "string"}})},
    {"name": "get_workflow", "description": "Get a workflow graph by code.",
     "inputSchema": _obj({"code": {"type": "string"}}, ["code"])},
    {"name": "run_workflow", "description": "Start a workflow instance with an initial context.",
     "inputSchema": _obj({"code": {"type": "string"}, "context": {"type": "object"}}, ["code"])},
    {"name": "get_workflow_instance", "description": "Get the status and logs of a workflow instance.",
     "inputSchema": _obj({"instance_id": {"type": "integer"}}, ["instance_id"])},
    {"name": "list_collections", "description": "List knowledge base collections.",
     "inputSchema": _obj({})},
    {"name": "search_knowledge", "description": "Semantic-ish BM25 search over knowledge documents.",
     "inputSchema": _obj({"query": {"type": "string"}, "top_k": {"type": "integer"}}, ["query"])},
    {"name": "list_users", "description": "List platform users and their roles.",
     "inputSchema": _obj({})},
    {"name": "get_stats", "description": "Platform dashboard statistics.",
     "inputSchema": _obj({})},
    {"name": "who_am_i", "description": "Return my identity, roles, permissions, data scope and personal counters.",
     "inputSchema": _obj({})},
    {"name": "my_approvals", "description": "My approval tasks and their workflow progress.",
     "inputSchema": _obj({"status": {"type": "string", "description": "pending | done | all"},
                          "limit": {"type": "integer"}})},
    {"name": "my_submissions", "description": "Form submissions I created.",
     "inputSchema": _obj({"limit": {"type": "integer"}})},
    {"name": "my_instances", "description": "Approval workflow instances I started and their progress.",
     "inputSchema": _obj({"status": {"type": "string"}, "limit": {"type": "integer"}})},
    {"name": "list_startable_workflows", "description": "Published workflows that can be launched with a form.",
     "inputSchema": _obj({})},
    {"name": "get_form_schema", "description": "Rendered field schema used to build a dynamic collection form.",
     "inputSchema": _obj({"code": {"type": "string", "description": "Form code"}}, ["code"])},
    {"name": "start_workflow_instance", "description": "Start an approval instance from collected form data.",
     "inputSchema": _obj({"code": {"type": "string"}, "data": {"type": "object"}}, ["code", "data"])},
    {"name": "submit_form_data", "description": "Submit collected data to a published form.",
     "inputSchema": _obj({"code": {"type": "string"}, "data": {"type": "object"}}, ["code", "data"])},
    {"name": "act_approval_task",
     "description": "Act on one of my pending approval tasks (approve / reject / return / "
                    "transfer / addsign). Without task_id the first pending task is used.",
     "inputSchema": _obj({"action": {"type": "string", "description": "approve | reject | "
                                     "return | transfer | addsign_before | addsign_after"},
                          "instance_id": {"type": "integer"}, "task_id": {"type": "integer"},
                          "comment": {"type": "string"}, "assignee": {"type": "string"},
                          "return_to": {"type": "string"}})},
    {"name": "withdraw_instance", "description": "Withdraw one of my running instances.",
     "inputSchema": _obj({"instance_id": {"type": "integer"}, "reason": {"type": "string"}})},
    {"name": "urge_instance", "description": "Urge the current approvers of a visible instance.",
     "inputSchema": _obj({"instance_id": {"type": "integer"}, "message": {"type": "string"}})},
    {"name": "my_notifications", "description": "My in-app notifications (optionally unread only).",
     "inputSchema": _obj({"unread": {"type": "boolean"}, "limit": {"type": "integer"}})},
]

# System-wide capabilities live in their own module so the agent tool catalog
# grows with the platform without editing this dispatcher.
TOOL_SPECS.extend(agent_admin_tools.SPECS)

# Tools that mutate business data — blocked for the read-only auditor role.
WRITE_TOOLS = {"submit_form", "run_workflow", "start_workflow_instance", "submit_form_data",
               "act_approval_task", "withdraw_instance", "urge_instance"}
WRITE_TOOLS.update(agent_admin_tools.WRITE_TOOLS)

PERMISSION_MAP = {
    "list_forms": "form:read", "get_form": "form:read", "submit_form": "form:submit",
    "query_records": "form:read", "list_workflows": "workflow:read",
    "get_workflow": "workflow:read", "run_workflow": "workflow:run",
    "get_workflow_instance": "workflow:read", "list_collections": "knowledge:read",
    "search_knowledge": "knowledge:read", "list_users": "rbac:read",
    "get_stats": "dashboard:view",
    "list_startable_workflows": "workflow:read", "get_form_schema": "form:read",
    "start_workflow_instance": "workflow:run", "submit_form_data": "form:submit",
    "act_approval_task": "workflow:run", "withdraw_instance": "workflow:run",
    "urge_instance": "workflow:run", "my_notifications": None,
}

PERMISSION_MAP.update(agent_admin_tools.PERMISSIONS)
# Attach the required permission to every spec so tools/list, the agent runtime
# and the capability matrix can all be derived from one place.
for _spec in TOOL_SPECS:
    _spec.setdefault("permission", PERMISSION_MAP.get(_spec["name"]))


def _tool_allowed(name: str, user: dict | None) -> bool:
    """A tool is visible only when its human operator has the permission."""
    if user is None:
        return True  # unauthenticated MCP handshake still gets the full schema
    needed = PERMISSION_MAP.get(name)
    return not needed or has_permission(user, needed)


def capability_matrix(user: dict | None = None) -> dict:
    """Group the whole platform tool catalog by capability domain."""
    groups: dict[str, dict] = {}
    for spec in TOOL_SPECS:
        perm = spec.get("permission") or "authenticated"
        domain = perm.split(":")[0]
        entry = groups.setdefault(domain, {"tools": [], "permissions": set()})
        entry["tools"].append({"name": spec["name"], "description": spec["description"],
                               "permission": spec.get("permission"),
                               "available": _tool_allowed(spec["name"], user)})
        if spec.get("permission"):
            entry["permissions"].add(spec["permission"])
    return {
        "domains": {k: {"tools": v["tools"], "permissions": sorted(v["permissions"]),
                        "total": len(v["tools"]),
                        "available": sum(1 for t in v["tools"] if t["available"])}
                    for k, v in sorted(groups.items())},
        "total_tools": len(TOOL_SPECS),
        "available_tools": sum(1 for s in TOOL_SPECS if _tool_allowed(s["name"], user)),
        "permission_driven": True,
    }


def _list_forms(args: dict) -> dict:
    status = args.get("status")
    rows = db.q("SELECT * FROM forms" + (" WHERE status=?" if status else "") + " ORDER BY id",
                (status,) if status else ())
    forms = []
    for r in rows:
        loaded = db.loads(r, "schema") or {}
        forms.append({"id": r["id"], "code": r["code"], "name": r["name"],
                      "status": r["status"], "description": r["description"],
                      "fields": len(loaded.get("schema") or []), "version": r["version"]})
    return {"forms": forms, "total": len(forms)}


def _get_form(args: dict) -> dict:
    row = db.q1("SELECT * FROM forms WHERE code=?", (args.get("code"),))
    if not row:
        raise ValueError(f"Form not found: {args.get('code')}")
    return db.loads(row, "schema", "layout") or {}


def _submit_form(args: dict) -> dict:
    row = db.q1("SELECT * FROM forms WHERE code=?", (args.get("code"),))
    if not row:
        raise ValueError(f"Form not found: {args.get('code')}")
    if row["status"] != "published":
        raise ValueError("Form is not published")
    data = args.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    missing = [f.get("label") or f.get("key") for f in schema
               if f.get("required") and not data.get(f.get("key"))]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(str(m) for m in missing)}")
    user = current_user()
    sid = db.insert("form_submissions", {"form_id": row["id"], "data": data,
                                         "status": "submitted",
                                         "submitted_by": (user or {}).get("username") or "mcp",
                                         "created_at": db.now()})
    return {"submission_id": sid, "form": row["code"], "status": "submitted"}


def _query_records(args: dict) -> dict:
    limit = min(int(args.get("limit") or 20), 100)
    frag, scope_args = data_scope.owner_clause(current_user(), "form_submissions", "s")
    extra = f" AND {frag}" if frag else ""
    if args.get("form_code"):
        rows = db.q(
            "SELECT s.*,f.code AS form_code,f.name AS form_name FROM form_submissions s "
            "JOIN forms f ON f.id=s.form_id WHERE f.code=?" + extra +
            " ORDER BY s.id DESC LIMIT ?", (args["form_code"], *scope_args, limit))
    else:
        rows = db.q(
            "SELECT s.*,f.code AS form_code,f.name AS form_name FROM form_submissions s "
            "JOIN forms f ON f.id=s.form_id WHERE 1=1" + extra +
            " ORDER BY s.id DESC LIMIT ?", (*scope_args, limit))
    return {"records": [db.loads(r, "data") for r in rows], "count": len(rows)}


def _list_workflows(args: dict) -> dict:
    status = args.get("status")
    rows = db.q("SELECT * FROM workflows" + (" WHERE status=?" if status else "") + " ORDER BY id",
                (status,) if status else ())
    out = []
    for r in rows:
        g = (db.loads(r, "graph") or {}).get("graph") or {}
        out.append({"id": r["id"], "code": r["code"], "name": r["name"],
                    "status": r["status"], "description": r["description"],
                    "nodes": len(g.get("nodes") or []), "edges": len(g.get("edges") or []),
                    "version": r["version"]})
    return {"workflows": out, "total": len(out)}


def _get_workflow(args: dict) -> dict:
    row = db.q1("SELECT * FROM workflows WHERE code=?", (args.get("code"),))
    if not row:
        raise ValueError(f"Workflow not found: {args.get('code')}")
    return db.loads(row, "graph") or {}


def _run_workflow(args: dict) -> dict:
    row = db.q1("SELECT * FROM workflows WHERE code=?", (args.get("code"),))
    if not row:
        raise ValueError(f"Workflow not found: {args.get('code')}")
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    errors = workflow_engine.validate_graph(graph)
    if errors:
        raise ValueError("Invalid workflow: " + "; ".join(errors))
    user = current_user()
    actor = (user or {}).get("username") or "mcp"
    iid = db.insert("workflow_instances", {
        "workflow_id": row["id"], "status": "running", "context": args.get("context") or {},
        "logs": [], "started_by": actor, "started_at": db.now()})
    result = workflow_engine.run(graph, args.get("context") or {}, actor)
    db.update("workflow_instances", iid, {
        "status": result["status"], "context": result["context"], "logs": result["logs"],
        "finished_at": db.now()})
    return {"instance_id": iid, "workflow": row["code"], "status": result["status"],
            "steps": len(result["logs"]), "context": result["context"]}


def _get_workflow_instance(args: dict) -> dict:
    row = db.q1("SELECT * FROM workflow_instances WHERE id=?", (args.get("instance_id"),))
    if not row or not data_scope.row_visible(current_user(), "workflow_instances", row):
        raise ValueError("Instance not found or not visible")
    return db.loads(row, "context", "logs") or {}


def _list_collections(_args: dict) -> dict:
    rows = db.q("SELECT c.*, (SELECT COUNT(*) FROM kb_documents d WHERE d.collection_id=c.id) "
                "AS document_count FROM kb_collections c ORDER BY c.id")
    return {"collections": rows, "total": len(rows)}


def _search_knowledge(args: dict) -> dict:
    hits = rag.search(str(args.get("query") or ""), top_k=min(int(args.get("top_k") or 4), 10))
    return {"hits": hits, "count": len(hits), "context": rag.build_context(hits)}


def _list_users(_args: dict) -> dict:
    rows = db.q("SELECT id,username,email,display_name,status,dept,role_ids,provider,last_login_at "
                "FROM users ORDER BY id")
    users = []
    for r in rows:
        u = db.loads(r, "role_ids") or {}
        codes = [db.q1("SELECT code FROM roles WHERE id=?", (rid,)) or {} for rid in (u.get("role_ids") or [])]
        users.append({**u, "role_ids": u.get("role_ids") or [],
                      "roles": [c.get("code") for c in codes if c.get("code")],
                      "password_hash": None})
    return {"users": users, "total": len(users)}


def _get_stats(_args: dict) -> dict:
    user = current_user()
    own = data_scope.role(user) == "self"
    username = (user or {}).get("username") or ""

    def count(table: str, owner: str | None = None) -> int:
        if own and owner:
            return int(db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {owner}=?",
                                 (username,)) or 0)
        return int(db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)

    return {
        "forms": count("forms"), "form_submissions": count("form_submissions", "submitted_by"),
        "workflows": count("workflows"), "workflow_instances": count("workflow_instances", "started_by"),
        "kb_collections": count("kb_collections"), "kb_documents": count("kb_documents"),
        "agents": count("agents"), "mcp_skills": count("mcp_skills"),
        "users": count("users"), "roles": count("roles"),
        "audit_logs": count("audit_logs", "actor"),
        "published_forms": int(db.scalar("SELECT COUNT(*) FROM forms WHERE status='published'") or 0),
        "published_workflows": int(db.scalar("SELECT COUNT(*) FROM workflows WHERE status='published'") or 0),
    }


def _who_am_i(_args: dict) -> dict:
    from . import agent_intents
    return agent_intents.identity(current_user())


def _my_approvals(args: dict) -> dict:
    username = (current_user() or {}).get("username") or ""
    status = args.get("status") or "all"
    limit = min(int(args.get("limit") or 30), 100)
    sql = ("SELECT t.*, i.status AS instance_status, i.started_by AS initiator, "
           "i.form_code, i.started_at, w.code AS workflow_code, w.name AS workflow_name "
           "FROM flow_tasks t JOIN workflow_instances i ON i.id=t.instance_id "
           "JOIN workflows w ON w.id=i.workflow_id WHERE t.assignee=?")
    params: list = [username]
    if status == "pending":
        sql += " AND t.status='pending'"
    elif status == "done":
        sql += " AND t.status!='pending'"
    rows = [dict(r) for r in db.q(
        sql + " ORDER BY CASE WHEN t.status='pending' THEN 0 ELSE 1 END, t.id DESC LIMIT ?",
        (*params, limit))]
    return {"approvals": rows, "total": len(rows),
            "pending": sum(1 for r in rows if r.get("status") == "pending")}


def _my_submissions(args: dict) -> dict:
    username = (current_user() or {}).get("username") or ""
    limit = min(int(args.get("limit") or 20), 100)
    rows = db.q("SELECT s.id,s.form_id,s.data,s.status,s.submitted_by,s.serial_no,"
                "s.created_at,f.code AS form_code,f.name AS form_name "
                "FROM form_submissions s JOIN forms f ON f.id=s.form_id "
                "WHERE s.submitted_by=? ORDER BY s.id DESC LIMIT ?", (username, limit))
    return {"submissions": [db.loads(r, "data") for r in rows], "total": len(rows)}


def _my_instances(args: dict) -> dict:
    username = (current_user() or {}).get("username") or ""
    status = args.get("status")
    limit = min(int(args.get("limit") or 20), 100)
    sql = ("SELECT i.*, w.code AS workflow_code, w.name AS workflow_name "
           "FROM workflow_instances i JOIN workflows w ON w.id=i.workflow_id "
           "WHERE i.started_by=?")
    params: list = [username]
    if status and status != "all":
        sql += " AND i.status=?"
        params.append(status)
    rows = db.q(sql + " ORDER BY i.id DESC LIMIT ?", (*params, limit))
    return {"instances": [db.loads(r, "context", "logs", "form_data", "current_nodes")
                          for r in rows], "total": len(rows)}


def _list_startable_workflows(_args: dict) -> dict:
    rows = db.q("SELECT * FROM workflows WHERE status='published' ORDER BY id")
    out = []
    for r in rows:
        fcode = r.get("form_code")
        form = db.q1("SELECT name,status,schema FROM forms WHERE code=?", (fcode,)) if fcode else None
        out.append({"id": r["id"], "code": r["code"], "name": r["name"],
                    "description": r["description"], "form_code": fcode,
                    "form_name": form["name"] if form else None,
                    "field_count": len((db.loads(form, "schema") or {}).get("schema") or [])
                    if form else 0,
                    "start_path": f"/#/start/{r['code']}"})
    return {"workflows": out, "total": len(out)}


def _get_form_schema(args: dict) -> dict:
    from . import form_rules
    row = db.q1("SELECT * FROM forms WHERE code=?", (args.get("code"),))
    if not row:
        raise ValueError(f"Form not found: {args.get('code')}")
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    return {"form": {"id": row["id"], "code": row["code"], "name": row["name"],
                     "version": row["version"], "status": row["status"]},
            **form_rules.render_schema(schema)}


def _start_workflow_instance(args: dict) -> dict:
    from . import agent_intents
    user = current_user()
    if not user:
        raise PermissionError("Authentication required")
    result = agent_intents.execute("start_workflow", str(args.get("code") or ""),
                                   dict(args.get("data") or {}), user)
    return {"instance_id": result["instance_id"], "workflow": result["code"],
            "status": result["status"], "pending": len(result["pending"]),
            "answer": result["answer"]}


def _submit_form_data(args: dict) -> dict:
    from . import agent_intents
    user = current_user()
    if not user:
        raise PermissionError("Authentication required")
    result = agent_intents.execute("submit_form", str(args.get("code") or ""),
                                   dict(args.get("data") or {}), user)
    return {"submission_id": result["submission_id"], "form": result["code"],
            "status": "submitted", "answer": result["answer"]}




def _act_approval_task(args: dict) -> dict:
    """Approve / reject / return / transfer / add-sign; defaults to first pending task."""
    from . import flow_runtime
    username = (current_user() or {}).get("username") or ""
    action = args.get("action") or "approve"
    if action not in flow_runtime.ACTIONS or action in {"withdraw", "urge"}:
        raise ValueError(f"Unsupported action: {action}")
    task_id, instance_id = args.get("task_id"), args.get("instance_id")
    if not task_id:
        sql = ("SELECT t.id, t.instance_id FROM flow_tasks t "
               "JOIN workflow_instances i ON i.id=t.instance_id "
               "WHERE t.assignee=? AND t.status='pending'")
        params: list = [username]
        if instance_id:
            sql += " AND t.instance_id=?"
            params.append(instance_id)
        row = db.q1(sql + " ORDER BY t.id LIMIT 1", params)
        if not row:
            raise ValueError("No pending approval task found for you")
        task_id, instance_id = row["id"], row["instance_id"]
    elif not instance_id:
        row = db.q1("SELECT instance_id FROM flow_tasks WHERE id=?", (task_id,))
        if not row:
            raise ValueError(f"Task not found: {task_id}")
        instance_id = row["instance_id"]
    payload = {"comment": args.get("comment"), "assignee": args.get("assignee"),
               "signature": args.get("signature"), "return_to": args.get("return_to")}
    view = flow_runtime.act(instance_id, task_id, action, username, payload)
    pending = [t.get("assignee") for t in view.get("tasks") or []
               if t.get("status") == "pending"]
    return {"ok": True, "instance_id": instance_id, "task_id": task_id, "action": action,
            "instance_status": view.get("status"), "pending": pending}


def _withdraw_instance(args: dict) -> dict:
    from . import flow_runtime
    username = (current_user() or {}).get("username") or ""
    iid = args.get("instance_id")
    if not iid:
        row = db.q1("SELECT id FROM workflow_instances WHERE started_by=? AND status='running' "
                    "ORDER BY id DESC LIMIT 1", (username,))
        if not row:
            raise ValueError("No running instance of yours to withdraw")
        iid = row["id"]
    view = flow_runtime.withdraw(int(iid), username, args.get("reason") or "")
    return {"ok": True, "instance_id": iid, "instance_status": view.get("status")}


def _urge_instance(args: dict) -> dict:
    from . import flow_runtime
    username = (current_user() or {}).get("username") or ""
    iid = args.get("instance_id")
    if not iid:
        # most recent running instance of mine, else one pending on me
        row = db.q1("SELECT id FROM workflow_instances WHERE started_by=? AND status='running' "
                    "ORDER BY id DESC LIMIT 1", (username,))
        if not row:
            row = db.q1("SELECT instance_id AS id FROM flow_tasks WHERE assignee=? AND "
                        "status='pending' ORDER BY id DESC LIMIT 1", (username,))
        if not row:
            raise ValueError("No visible running instance to urge")
        iid = row["id"]
    row = db.q1("SELECT * FROM workflow_instances WHERE id=?", (iid,))
    user = current_user() or {"username": username}
    if not row or not data_scope.row_visible(user, "workflow_instances", row):
        raise ValueError(f"Instance not found: {iid}")
    result = flow_runtime.urge(int(iid), username, args.get("message") or "")
    return {"ok": True, **result}


def _my_notifications(args: dict) -> dict:
    from . import notify
    username = (current_user() or {}).get("username") or ""
    limit = min(int(args.get("limit") or 20), 100)
    sql = "SELECT * FROM notifications WHERE recipient=?"
    if args.get("unread"):
        sql += " AND read_at IS NULL"
    rows = [dict(r) for r in db.q(sql + " ORDER BY id DESC LIMIT ?", (username, limit))]
    return {"notifications": rows, "total": len(rows),
            "unread": notify.unread_count(username)}


HANDLERS: dict[str, Callable[[dict], dict]] = {
    "list_forms": _list_forms, "get_form": _get_form, "submit_form": _submit_form,
    "query_records": _query_records, "list_workflows": _list_workflows,
    "get_workflow": _get_workflow, "run_workflow": _run_workflow,
    "get_workflow_instance": _get_workflow_instance, "list_collections": _list_collections,
    "search_knowledge": _search_knowledge, "list_users": _list_users,
    "get_stats": _get_stats,
    "who_am_i": _who_am_i, "my_approvals": _my_approvals,
    "my_submissions": _my_submissions, "my_instances": _my_instances,
    "list_startable_workflows": _list_startable_workflows,
    "get_form_schema": _get_form_schema,
    "start_workflow_instance": _start_workflow_instance,
    "submit_form_data": _submit_form_data,
    "act_approval_task": _act_approval_task, "withdraw_instance": _withdraw_instance,
    "urge_instance": _urge_instance, "my_notifications": _my_notifications,
}

HANDLERS.update(agent_admin_tools.HANDLERS)


def _merged_specs(names: set[str] | None = None,
                  server_ids: list[int] | None = None) -> list[dict]:
    """Platform tools + tools declared by enabled MCP servers."""
    specs = [t for t in TOOL_SPECS if names is None or t["name"] in names]
    if server_ids is not None and not server_ids:
        return specs
    builtin = {t["name"] for t in TOOL_SPECS}
    for t in mcp_servers.external_specs(names, server_ids):
        if t["name"] not in builtin:
            specs.append(t)
    return specs


def list_tools(fmt: str = "mcp", *, names: set[str] | None = None,
               server_ids: list[int] | None = None,
               include_external: bool = True,
               user: dict | None = None) -> list[dict]:
    specs = _merged_specs(names, server_ids) if include_external else \
        [t for t in TOOL_SPECS if names is None or t["name"] in names]
    # Permission-driven catalog: an agent (or MCP client) only sees tools its
    # bound user is actually allowed to invoke.
    effective = user if user is not None else current_user()
    specs = [t for t in specs if _tool_allowed(t["name"], effective)]
    if fmt == "catalog":
        return [{"name": t["name"], "description": t["description"],
                 "inputSchema": t["inputSchema"], "permission": t.get("permission")}
                for t in specs]
    if fmt == "openai":
        return [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["inputSchema"]}} for t in specs]
    return [{"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in specs]


def agent_tools(agent: dict, fmt: str = "openai") -> list[dict]:
    """Build the tool set available to one agent from its bound servers / skills.

    With explicit bindings only tools declared by the selected servers and
    skills are exposed. Without bindings every enabled server contributes its
    tools (backwards-compatible default for existing agents).
    """
    if agent.get("mode") not in {"act", "hybrid"}:
        return []
    server_ids = [int(x) for x in (agent.get("server_ids") or [])]
    skill_ids = [int(x) for x in (agent.get("skill_ids") or [])]
    scope = server_ids or None
    names: set[str] | None = None
    if server_ids or skill_ids:
        names = {t["name"] for t in mcp_servers.declared_tools(scope)}
        if skill_ids:
            marks = ",".join("?" for _ in skill_ids)
            for row in db.q(f"SELECT tools, server_id FROM mcp_skills WHERE id IN ({marks})",
                            tuple(skill_ids)):
                loaded = db.loads(row, "tools") or {}
                for tool in loaded.get("tools") or []:
                    if isinstance(tool, dict) and tool.get("name"):
                        names.add(tool["name"])
                linked = row.get("server_id")
                if linked:
                    names |= {t["name"] for t in mcp_servers.declared_tools([int(linked)])}
        available = {t["name"] for t in list_tools("mcp", server_ids=scope)}
        names &= available
        if not names:
            names = None  # bindings declare nothing callable → keep the safe default
    return list_tools(fmt, names=names, server_ids=scope)


def call_tool(name: str, args: dict | None = None, user: dict | None = None,
              *, journal: bool = True) -> dict:
    """Execute a registered tool and optionally write one journal entry.

    The journal is written in ``finally`` so failed calls (validation errors,
    permission denials, handler exceptions) are recorded as well.
    """
    args = args or {}
    effective_user = user if user is not None else current_user()
    ctx = call_context()
    actor = ctx.get("actor") or (effective_user or {}).get("username") or "anonymous"
    started = time.perf_counter()
    status, error, result = "success", None, None
    try:
        external = None
        if name not in HANDLERS:
            external = mcp_servers.find_external(name)
            if not external:
                raise ValueError(f"Unknown tool: {name}")
        if effective_user:
            if data_scope.read_only(effective_user) and name in WRITE_TOOLS:
                raise PermissionError("The audit administrator role is read-only")
            needed = PERMISSION_MAP.get(name) or ("mcp:invoke" if external else None)
            if needed and not has_permission(effective_user, needed):
                raise PermissionError(f"Permission denied for tool {name}: needs {needed}")
        previous = _current_user.set(user) if user is not None else None
        try:
            if external:
                server, _spec = external
                result = mcp_servers.invoke_external(server, name, args)
            else:
                result = HANDLERS[name](args)
        finally:
            if previous is not None:
                _current_user.reset(previous)
        return result
    except Exception as exc:
        status, error = "error", str(exc)
        raise
    finally:
        if journal:
            mcp_journal.record(
                method=ctx.get("method") or "tools/call", tool=name,
                source=ctx.get("source") or "internal", transport=ctx.get("transport"),
                actor=actor, arguments=args, status=status, error=error, result=result,
                target=ctx.get("target"),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                request_id=ctx.get("request_id"))


def as_mcp_content(result: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result, "isError": False}
