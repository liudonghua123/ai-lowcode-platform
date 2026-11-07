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
from . import mcp_journal, rag, workflow_engine

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
                 actor: str | None = None) -> None:
    """Tag the current async context so call_tool can journal the invocation."""
    _call_context.set({"source": source, "transport": transport, "request_id": request_id,
                       "method": method, "actor": actor})


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
]

PERMISSION_MAP = {
    "list_forms": "form:read", "get_form": "form:read", "submit_form": "form:submit",
    "query_records": "form:read", "list_workflows": "workflow:read",
    "get_workflow": "workflow:read", "run_workflow": "workflow:run",
    "get_workflow_instance": "workflow:read", "list_collections": "knowledge:read",
    "search_knowledge": "knowledge:read", "list_users": "rbac:read",
    "get_stats": "dashboard:view",
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
    if args.get("form_code"):
        rows = db.q(
            "SELECT s.*,f.code AS form_code,f.name AS form_name FROM form_submissions s "
            "JOIN forms f ON f.id=s.form_id WHERE f.code=? ORDER BY s.id DESC LIMIT ?",
            (args["form_code"], limit))
    else:
        rows = db.q(
            "SELECT s.*,f.code AS form_code,f.name AS form_name FROM form_submissions s "
            "JOIN forms f ON f.id=s.form_id ORDER BY s.id DESC LIMIT ?", (limit,))
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
    if not row:
        raise ValueError("Instance not found")
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
    count = lambda table: int(db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)  # noqa: E731
    return {
        "forms": count("forms"), "form_submissions": count("form_submissions"),
        "workflows": count("workflows"), "workflow_instances": count("workflow_instances"),
        "kb_collections": count("kb_collections"), "kb_documents": count("kb_documents"),
        "agents": count("agents"), "mcp_skills": count("mcp_skills"),
        "users": count("users"), "roles": count("roles"), "audit_logs": count("audit_logs"),
        "published_forms": int(db.scalar("SELECT COUNT(*) FROM forms WHERE status='published'") or 0),
        "published_workflows": int(db.scalar("SELECT COUNT(*) FROM workflows WHERE status='published'") or 0),
    }


HANDLERS: dict[str, Callable[[dict], dict]] = {
    "list_forms": _list_forms, "get_form": _get_form, "submit_form": _submit_form,
    "query_records": _query_records, "list_workflows": _list_workflows,
    "get_workflow": _get_workflow, "run_workflow": _run_workflow,
    "get_workflow_instance": _get_workflow_instance, "list_collections": _list_collections,
    "search_knowledge": _search_knowledge, "list_users": _list_users,
    "get_stats": _get_stats,
}


def list_tools(fmt: str = "mcp") -> list[dict]:
    if fmt == "openai":
        return [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["inputSchema"]}} for t in TOOL_SPECS]
    return [{"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in TOOL_SPECS]


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
        if name not in HANDLERS:
            raise ValueError(f"Unknown tool: {name}")
        if effective_user:
            needed = PERMISSION_MAP.get(name)
            if needed and not has_permission(effective_user, needed):
                raise PermissionError(f"Permission denied for tool {name}: needs {needed}")
        previous = _current_user.set(user) if user is not None else None
        try:
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
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                request_id=ctx.get("request_id"))


def as_mcp_content(result: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result, "isError": False}
