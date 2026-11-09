"""Workflow API: DAG definitions, versions, long-running approval instances.

Domestic approval extensions: approval-roles and countersign rules, parallel
branches / joins, conditional groups, CC, reject / return / transfer / add-sign,
withdraw, urge, timeout sweep, delegation and per-node form field permissions.
The original synchronous ``/run`` dry-run is kept for compatibility.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..services import data_scope, flow_runtime, form_rules, workflow_engine

router = APIRouter(prefix="/workflows", tags=["Workflows"])

NODE_TYPES = [
    {"type": "start", "name": "Start / 开始", "category": "control", "color": "#6366f1",
     "config": flow_runtime.NODE_CONFIG_HINTS["start"]},
    {"type": "end", "name": "End / 结束", "category": "control", "color": "#64748b",
     "config": []},
    {"type": "form", "name": "Form / 表单节点", "category": "task", "color": "#0ea5e9",
     "config": flow_runtime.NODE_CONFIG_HINTS["form"]},
    {"type": "approval", "name": "Approval / 审批", "category": "task", "color": "#8b5cf6",
     "config": flow_runtime.NODE_CONFIG_HINTS["approval"]},
    {"type": "cc", "name": "CC / 抄送", "category": "task", "color": "#38bdf8",
     "config": flow_runtime.NODE_CONFIG_HINTS["cc"]},
    {"type": "condition", "name": "Condition / 条件分支", "category": "logic", "color": "#f59e0b",
     "config": flow_runtime.NODE_CONFIG_HINTS["condition"]},
    {"type": "parallel", "name": "Parallel / 并行分支", "category": "logic", "color": "#a855f7",
     "config": []},
    {"type": "join", "name": "Join / 分支汇聚", "category": "logic", "color": "#7c3aed",
     "config": flow_runtime.NODE_CONFIG_HINTS["join"]},
    {"type": "delay", "name": "Delay / 定时等待", "category": "logic", "color": "#f97316",
     "config": flow_runtime.NODE_CONFIG_HINTS["delay"]},
    {"type": "subflow", "name": "Subflow / 子流程", "category": "logic", "color": "#0d9488",
     "config": flow_runtime.NODE_CONFIG_HINTS["subflow"]},
    {"type": "ai", "name": "AI / 智能处理", "category": "ai", "color": "#ec4899",
     "config": flow_runtime.NODE_CONFIG_HINTS["ai"]},
    {"type": "knowledge", "name": "Knowledge / 知识检索", "category": "ai", "color": "#14b8a6",
     "config": flow_runtime.NODE_CONFIG_HINTS["knowledge"]},
    {"type": "http", "name": "HTTP / 外部接口", "category": "integration", "color": "#22c55e",
     "config": flow_runtime.NODE_CONFIG_HINTS["http"]},
    {"type": "notification", "name": "Notification / 通知", "category": "integration",
     "color": "#f97316", "config": flow_runtime.NODE_CONFIG_HINTS["notification"]},
]
OPERATORS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_contains",
             "in", "not_in", "empty", "not_empty"]


class GraphIn(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class WorkflowIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str
    description: str | None = None
    status: str = "draft"
    form_code: str | None = None
    graph: GraphIn = Field(default_factory=GraphIn)


class WorkflowPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    form_code: str | None = None
    graph: GraphIn | None = None


class RunIn(BaseModel):
    context: dict = Field(default_factory=dict)


class StartIn(BaseModel):
    form_data: dict = Field(default_factory=dict)
    selected_approvers: list[str] = Field(default_factory=list)
    variables: dict = Field(default_factory=dict)
    create_submission: bool = True


class ActIn(BaseModel):
    action: str
    comment: str | None = None
    signature: str | None = None
    assignee: str | None = None
    return_to: str | None = None


class VersionIn(BaseModel):
    note: str | None = None
    version: int | None = None


class DelegationIn(BaseModel):
    principal: str
    agent: str
    scope: str | None = None
    hours: int = 24 * 7


def _out(row: dict) -> dict:
    out = db.loads(row, "graph") or {}
    out["graph"] = out.get("graph") or {"nodes": [], "edges": []}
    out["node_count"] = len(out["graph"].get("nodes") or [])
    out["edge_count"] = len(out["graph"].get("edges") or [])
    return out


def _wf_or_404(workflow_id: int) -> dict:
    row = db.q1("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return dict(row)


def _snapshot(row: dict, actor: str, note: str | None = None) -> int:
    return db.insert("workflow_versions", {
        "workflow_id": row["id"], "version": row["version"],
        "graph": row["graph"] if isinstance(row["graph"], str) else db.dumps(row["graph"]),
        "form_code": row.get("form_code"), "note": note, "created_by": actor,
        "created_at": db.now()})


def _guard(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _instance_readable(instance_id: int, user: dict) -> dict:
    """404 (not 403) when an instance is outside the caller's data scope."""
    row = db.q1("SELECT * FROM workflow_instances WHERE id=?", (instance_id,))
    if not row or not data_scope.row_visible(user, "workflow_instances", row):
        raise HTTPException(status_code=404, detail="Instance not found")
    return dict(row)


# --------------------------------------------------------------------------- #
# Metadata (static paths must precede /{workflow_id})
# --------------------------------------------------------------------------- #
@router.get("/meta", summary="Node palette and approval-rule metadata")
def workflow_meta(lang: str = Query("en", pattern="^(en|zh)$"),
                  _user: dict = Depends(deps.require("workflow:read"))):
    return {"node_types": NODE_TYPES, "operators": OPERATORS, **flow_runtime.meta(lang)}


@router.get("/node-types", summary="Node palette metadata for the canvas")
def node_types(_user: dict = Depends(deps.require("workflow:read"))):
    return {"node_types": NODE_TYPES, "operators": OPERATORS}


# --------------------------------------------------------------------------- #
# Workflow portal: startable catalogue, my instances, public share links
# --------------------------------------------------------------------------- #
def _start_form(workflow: dict) -> tuple[str | None, dict | None, list[dict]]:
    """Resolve the form bound to a workflow (definition or its start node)."""
    graph = (db.loads(workflow, "graph") or {}).get("graph") or {}
    start = next((n for n in (graph.get("nodes") or []) if n.get("type") == "start"), {})
    code = (start.get("config") or {}).get("form_code") or workflow.get("form_code")
    if not code:
        return None, None, []
    form = db.q1("SELECT * FROM forms WHERE code=?", (code,))
    if not form:
        return code, None, []
    schema = (db.loads(form, "schema") or {}).get("schema") or []
    return code, form, schema


@router.get("/catalog", summary="Startable workflow catalogue for the portal (with share links)")
def workflow_catalog(status: str = Query("published"),
                     user: dict = Depends(deps.require("workflow:read"))):
    sql, args = "SELECT * FROM workflows WHERE 1=1", []
    if status != "all":
        sql += " AND status=?"
        args.append(status)
    rows = db.q(sql + " ORDER BY id DESC", tuple(args))
    out = []
    for r in rows:
        fcode, form, schema = _start_form(r)
        graph = (db.loads(r, "graph") or {}).get("graph") or {}
        out.append({
            "id": r["id"], "code": r["code"], "name": r["name"],
            "description": r["description"], "status": r["status"], "version": r["version"],
            "form_code": fcode, "form_name": form["name"] if form else None,
            "form_status": form["status"] if form else None,
            "field_count": len(schema), "node_count": len(graph.get("nodes") or []),
            "startable": r["status"] == "published",
            "requires_auth": True, "start_path": f"/#/start/{r['code']}",
        })
    return {"workflows": out, "total": len(out),
            "scope": data_scope.scope_for(user, "workflow_instances")}


def _instance_rows(user: dict, *, status: str | None, q: str | None,
                   workflow_id: int | None, date_from: str | None,
                   date_to: str | None, limit: int) -> list[dict]:
    frag, scope_args = data_scope.owner_clause(user, "workflow_instances")
    sql = "SELECT * FROM workflow_instances WHERE 1=1"
    args: list = list(scope_args)
    if frag:
        sql += " AND " + frag
    if status and status != "all":
        sql += " AND status=?"
        args.append(status)
    if workflow_id:
        sql += " AND workflow_id=?"
        args.append(workflow_id)
    if date_from:
        sql += " AND started_at>=?"
        args.append(date_from)
    if date_to:
        sql += " AND started_at<=?"
        args.append(date_to + "T23:59:59" if len(date_to) == 10 else date_to)
    if q:
        sql += " AND (form_data LIKE ? OR form_code LIKE ?)"
        args += [f"%{q}%"] * 2
    return db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 300)))


@router.get("/mine/instances", summary="My launched instances with status / text / date filters")
def my_instances(status: str | None = None, q: str | None = None,
                 workflow_id: int | None = None, date_from: str | None = None,
                 date_to: str | None = None, limit: int = 100,
                 user: dict = Depends(deps.require("workflow:read"))):
    rows = _instance_rows(user, status=status, q=q, workflow_id=workflow_id,
                          date_from=date_from, date_to=date_to, limit=limit)
    wfs = {r["id"]: r for r in db.q("SELECT id,code,name FROM workflows")}
    counts = {r["instance_id"]: r for r in db.q(
        "SELECT instance_id, COUNT(*) AS c, "
        "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS p "
        "FROM flow_tasks GROUP BY instance_id")}
    out = []
    for r in rows:
        d = db.loads(r, "context", "logs", "graph", "form_data", "current_nodes", "variables") or {}
        wf = wfs.get(r["workflow_id"], {})
        d["workflow_code"] = wf.get("code")
        d["workflow_name"] = wf.get("name")
        d["task_count"] = int((counts.get(r["id"]) or {}).get("c") or 0)
        d["pending_count"] = int((counts.get(r["id"]) or {}).get("p") or 0)
        out.append(d)
    return {"instances": out, "total": len(out),
            "scope": data_scope.scope_for(user, "workflow_instances")}


@router.get("/mine/stats", summary="Portal counters for the current user")
def my_stats(user: dict = Depends(deps.require("workflow:read"))):
    frag, args = data_scope.owner_clause(user, "workflow_instances")
    rows = db.q("SELECT status, COUNT(*) AS c FROM workflow_instances WHERE 1=1" +
                (f" AND {frag}" if frag else "") + " GROUP BY status", tuple(args))
    by_status = {r["status"]: r["c"] for r in rows}
    if data_scope.can_read_all(user, "flow_tasks"):
        pending = int(db.scalar("SELECT COUNT(*) FROM flow_tasks WHERE status='pending'") or 0)
    else:
        pending = int(db.scalar("SELECT COUNT(*) FROM flow_tasks WHERE status='pending' "
                                "AND assignee=?", (user["username"],)) or 0)
    return {"by_status": by_status, "total": sum(by_status.values()),
            "running": by_status.get("running", 0), "pending_approvals": pending,
            "startable_workflows": int(db.scalar(
                "SELECT COUNT(*) FROM workflows WHERE status='published'") or 0)}


@router.get("/share-info/{code}",
            summary="Public launch info: share URL that requires authentication")
def share_info(code: str, request: Request):
    from urllib.parse import quote
    row = db.q1("SELECT * FROM workflows WHERE code=?", (code,))
    if not row or row["status"] != "published":
        raise HTTPException(status_code=404, detail="Workflow not found or not published")
    fcode, form, _ = _start_form(row)
    start_path = f"/#/start/{code}"
    return {
        "workflow_id": row["id"],
        "code": code, "name": row["name"], "description": row["description"],
        "form_code": fcode, "form_name": form["name"] if form else None,
        "requires_auth": True, "start_path": start_path,
        "login_path": f"/#/login?next={quote('/start/' + code)}",
        "share_url": str(request.base_url).rstrip("/") + start_path,
        "note": "Opening this link without a session redirects to sign-in, then returns "
                "here with the start form. Prefill is optional via ?data=<base64 json>.",
    }


@router.get("/tasks", summary="Approval task center: pending / done tasks")
def task_center(status: str = Query("pending"), assignee: str | None = None,
                all_users: bool = False, limit: int = 100,
                user: dict = Depends(deps.require("workflow:read"))):
    if data_scope.can_read_all(user, "flow_tasks"):
        who = assignee or (None if all_users else user["username"])
    else:
        who = user["username"]  # self-scope users cannot query other people's tasks
    sql = "SELECT * FROM flow_tasks WHERE 1=1"
    args: list = []
    if status != "all":
        sql += " AND status=?"
        args.append(status)
    if who:
        sql += " AND assignee=?"
        args.append(who)
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 300)))
    tasks = [dict(r) for r in rows]
    instances = {r["id"]: dict(r) for r in db.q(
        "SELECT id, workflow_id, status, started_by, form_code, started_at "
        "FROM workflow_instances")}
    for t in tasks:
        inst = instances.get(t["instance_id"], {})
        t["instance_status"] = inst.get("status")
        t["form_code"] = inst.get("form_code")
        t["initiator"] = inst.get("started_by")
    return {"tasks": tasks, "total": len(tasks), "assignee": who}


@router.post("/instances/sweep-timeouts", summary="Apply timeout policies to overdue tasks")
def sweep_timeouts(user: dict = Depends(deps.require("workflow:run")), request: Request = None):
    result = flow_runtime.sweep_timeouts()
    deps.audit(user["username"], "workflow.timeout_sweep", "workflow", result, request=request)
    return result


@router.get("/instances/{instance_id}", summary="Get a workflow instance with tasks and timeline")
def get_instance(instance_id: int, user: dict = Depends(deps.require("workflow:read"))):
    _instance_readable(instance_id, user)
    return flow_runtime.instance_view(instance_id)


@router.get("/instances/{instance_id}/tasks", summary="Tasks of an instance")
def instance_tasks(instance_id: int, user: dict = Depends(deps.require("workflow:read"))):
    _instance_readable(instance_id, user)
    tasks = flow_runtime.instance_view(instance_id)["tasks"]
    return {"tasks": tasks, "total": len(tasks)}


@router.get("/instances/{instance_id}/timeline", summary="Approval timeline of an instance")
def instance_timeline(instance_id: int, user: dict = Depends(deps.require("workflow:read"))):
    _instance_readable(instance_id, user)
    view = flow_runtime.instance_view(instance_id)
    return {"instance_id": instance_id, "status": view["status"],
            "logs": view["logs"], "current_nodes": view["current_nodes"]}


@router.get("/instances/{instance_id}/form-schema", summary="Form schema with node field permissions")
def instance_form_schema(instance_id: int, node_id: str | None = None,
                         user: dict = Depends(deps.require("workflow:read"))):
    _instance_readable(instance_id, user)
    return _guard(flow_runtime.form_schema_for_node, instance_id, node_id)


@router.post("/instances/{instance_id}/withdraw", summary="Initiator withdraws a running instance")
def withdraw(instance_id: int, reason: str = "", user: dict = Depends(deps.require("workflow:run")),
             request: Request = None):
    result = _guard(flow_runtime.withdraw, instance_id, user["username"], reason)
    deps.audit(user["username"], "workflow.withdraw", "workflow",
               {"instance": instance_id, "reason": reason}, request=request)
    return result


@router.post("/instances/{instance_id}/urge", summary="Urge current approvers")
def urge(instance_id: int, message: str = "", user: dict = Depends(deps.require("workflow:run")),
         request: Request = None):
    result = _guard(flow_runtime.urge, instance_id, user["username"], message)
    deps.audit(user["username"], "workflow.urge", "workflow",
               {"instance": instance_id}, request=request)
    return result


@router.post("/instances/{instance_id}/tasks/{task_id}/act",
             summary="Approve / reject / return / transfer / add-sign a task")
def act_task(instance_id: int, task_id: int, body: ActIn,
             user: dict = Depends(deps.require("workflow:run")), request: Request = None):
    if body.action not in flow_runtime.ACTIONS or body.action in {"withdraw", "urge"}:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {body.action}")
    payload = {"comment": body.comment, "signature": body.signature,
               "assignee": body.assignee, "return_to": body.return_to}
    result = _guard(flow_runtime.act, instance_id, task_id, body.action,
                    user["username"], payload)
    deps.audit(user["username"], f"workflow.{body.action}", "workflow",
               {"instance": instance_id, "task": task_id}, request=request)
    return result


@router.post("/delegations", status_code=201, summary="Create an approval delegation rule")
def create_delegation(body: DelegationIn, user: dict = Depends(deps.require("workflow:write")),
                      request: Request = None):
    from datetime import UTC, datetime, timedelta
    now = datetime.now(UTC)
    did = db.insert("flow_delegations", {"principal": body.principal, "agent": body.agent,
                                         "scope": body.scope, "starts_at": now.isoformat(timespec="seconds"),
                                         "ends_at": (now + timedelta(hours=body.hours)).isoformat(timespec="seconds"),
                                         "enabled": 1, "created_by": user["username"],
                                         "created_at": db.now()})
    deps.audit(user["username"], "workflow.delegation", "workflow",
               {"principal": body.principal, "agent": body.agent}, request=request)
    return {"id": did, "principal": body.principal, "agent": body.agent}


@router.get("/delegations", summary="List approval delegation rules")
def list_delegations(_user: dict = Depends(deps.require("workflow:read"))):
    rows = db.q("SELECT * FROM flow_delegations ORDER BY id DESC")
    return {"delegations": [dict(r) for r in rows], "total": len(rows)}


@router.delete("/delegations/{delegation_id}", summary="Disable a delegation rule")
def delete_delegation(delegation_id: int, user: dict = Depends(deps.require("workflow:write")),
                      request: Request = None):
    db.update("flow_delegations", delegation_id, {"enabled": 0})
    deps.audit(user["username"], "workflow.delegation.disable", "workflow",
               {"id": delegation_id}, request=request)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Definitions
# --------------------------------------------------------------------------- #
@router.get("", summary="List workflows")
def list_workflows(status: str | None = None, q: str | None = None,
                   _user: dict = Depends(deps.require("workflow:read"))):
    sql, args = "SELECT * FROM workflows WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        sql += " AND (name LIKE ? OR code LIKE ?)"
        args += [f"%{q}%"] * 2
    rows = db.q(sql + " ORDER BY id DESC", tuple(args))
    return {"workflows": [_out(r) for r in rows], "total": len(rows)}


@router.post("", status_code=201, summary="Create a workflow definition")
def create_workflow(body: WorkflowIn, user: dict = Depends(deps.require("workflow:write")),
                    request: Request = None):
    if db.q1("SELECT id FROM workflows WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Workflow code already exists")
    if body.form_code and not db.q1("SELECT id FROM forms WHERE code=?", (body.form_code,)):
        raise HTTPException(status_code=400, detail=f"Linked form not found: {body.form_code}")
    errors = workflow_engine.validate_graph(body.graph.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail="Invalid graph: " + "; ".join(errors))
    wid = db.insert("workflows", {"code": body.code, "name": body.name,
                                  "description": body.description, "status": body.status,
                                  "form_code": body.form_code, "graph": body.graph.model_dump(),
                                  "version": 1, "created_by": user["username"],
                                  "created_at": db.now(), "updated_at": db.now()})
    _snapshot(_wf_or_404(wid), user["username"], "initial")
    deps.audit(user["username"], "workflow.create", f"workflow:{body.code}",
               {"nodes": len(body.graph.nodes)}, request=request)
    return _out(_wf_or_404(wid))


@router.get("/{workflow_id}", summary="Get a workflow by id")
def get_workflow(workflow_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    return _out(_wf_or_404(workflow_id))


@router.put("/{workflow_id}", summary="Update a workflow definition (auto version snapshot)")
def update_workflow(workflow_id: int, body: WorkflowPatch,
                    user: dict = Depends(deps.require("workflow:write")), request: Request = None):
    row = _wf_or_404(workflow_id)
    patch = body.model_dump(exclude_none=True)
    if patch.get("form_code") and not db.q1("SELECT id FROM forms WHERE code=?",
                                            (patch["form_code"],)):
        raise HTTPException(status_code=400,
                            detail=f"Linked form not found: {patch['form_code']}")
    if "graph" in patch:
        errors = workflow_engine.validate_graph(patch["graph"])
        if errors:
            raise HTTPException(status_code=400, detail="Invalid graph: " + "; ".join(errors))
    patch["version"] = row["version"] + 1
    patch["updated_at"] = db.now()
    db.update("workflows", workflow_id, patch)
    _snapshot(_wf_or_404(workflow_id), user["username"], f"before update v{row['version']}")
    deps.audit(user["username"], "workflow.update", f"workflow:{row['code']}",
               {"version": patch["version"]}, request=request)
    return _out(_wf_or_404(workflow_id))


@router.delete("/{workflow_id}", summary="Delete a workflow, versions and instances")
def delete_workflow(workflow_id: int, user: dict = Depends(deps.require("workflow:write")),
                    request: Request = None):
    row = _wf_or_404(workflow_id)
    db.run("DELETE FROM flow_tasks WHERE instance_id IN "
           "(SELECT id FROM workflow_instances WHERE workflow_id=?)", (workflow_id,))
    db.run("DELETE FROM workflow_instances WHERE workflow_id=?", (workflow_id,))
    db.run("DELETE FROM workflow_versions WHERE workflow_id=?", (workflow_id,))
    db.delete("workflows", workflow_id)
    deps.audit(user["username"], "workflow.delete", f"workflow:{row['code']}", {}, request=request)
    return {"ok": True}


@router.post("/{workflow_id}/publish", summary="Publish a workflow definition")
def publish_workflow(workflow_id: int, user: dict = Depends(deps.require("workflow:write")),
                     request: Request = None):
    row = _wf_or_404(workflow_id)
    errors = workflow_engine.validate_graph((db.loads(row, "graph") or {}).get("graph") or {})
    if errors:
        raise HTTPException(status_code=400, detail="Invalid graph: " + "; ".join(errors))
    db.update("workflows", workflow_id, {"status": "published", "updated_at": db.now()})
    _snapshot(_wf_or_404(workflow_id), user["username"], "published")
    deps.audit(user["username"], "workflow.publish", f"workflow:{row['code']}", {}, request=request)
    return _out(_wf_or_404(workflow_id))


@router.get("/{workflow_id}/versions", summary="List workflow definition snapshots")
def versions(workflow_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    _wf_or_404(workflow_id)
    rows = db.q("SELECT * FROM workflow_versions WHERE workflow_id=? ORDER BY version DESC",
                (workflow_id,))
    return {"versions": [db.loads(r, "graph") for r in rows], "total": len(rows)}


@router.post("/{workflow_id}/versions", status_code=201,
             summary="Snapshot or restore a workflow version")
def save_version(workflow_id: int, body: VersionIn,
                 user: dict = Depends(deps.require("workflow:write")), request: Request = None):
    row = _wf_or_404(workflow_id)
    if body.version is not None:
        snap = db.q1("SELECT * FROM workflow_versions WHERE workflow_id=? AND version=?",
                     (workflow_id, body.version))
        if not snap:
            raise HTTPException(status_code=404, detail="Version not found")
        snap = db.loads(snap, "graph")
        version = row["version"] + 1
        db.update("workflows", workflow_id, {"graph": snap.get("graph") or {},
                                             "form_code": snap.get("form_code"),
                                             "version": version, "updated_at": db.now()})
        _snapshot(_wf_or_404(workflow_id), user["username"],
                  f"restored from v{body.version}")
        deps.audit(user["username"], "workflow.restore", f"workflow:{row['code']}",
                   {"version": version, "from": body.version}, request=request)
        return _out(_wf_or_404(workflow_id))
    _snapshot(row, user["username"], body.note)
    return {"ok": True, "version": row["version"]}


@router.post("/{workflow_id}/validate", summary="Validate a graph without running it")
def validate_workflow(workflow_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    row = _wf_or_404(workflow_id)
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    errors = workflow_engine.validate_graph(graph)
    return {"valid": not errors, "errors": errors,
            "nodes": len(graph.get("nodes") or []), "edges": len(graph.get("edges") or [])}


@router.get("/{workflow_id}/start-schema",
            summary="Dynamic start form schema (replaces raw JSON submission)")
def start_schema(workflow_id: int,
                 platform: str = Query("desktop", pattern="^(desktop|mobile)$"),
                 user: dict = Depends(deps.require("workflow:read"))):
    row = _wf_or_404(workflow_id)
    form_code, form, schema = _start_form(row)
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    base = {
        "workflow": {"id": row["id"], "code": row["code"], "name": row["name"],
                     "status": row["status"], "version": row["version"],
                     "node_count": len(graph.get("nodes") or [])},
        "start_path": f"/#/start/{row['code']}", "requires_auth": True,
        "platform": platform,
    }
    if not form:
        return {**base, "form": None, "fields": [], "permissions": {}, "columns": 2,
                "hint": "This workflow has no bound form; it can be started directly."}
    rendered = form_rules.render_schema(schema, platform=platform)
    return {
        **base,
        "form": {"id": form["id"], "code": form["code"], "name": form["name"],
                 "version": form["version"], "status": form["status"],
                 "field_count": len(schema)},
        **rendered,
    }


@router.post("/{workflow_id}/start", status_code=201,
             summary="Start a long-running approval instance")
def start_workflow(workflow_id: int, body: StartIn,
                   user: dict = Depends(deps.require("workflow:run")), request: Request = None):
    row = _wf_or_404(workflow_id)
    view = _guard(flow_runtime.start_instance, row, body.form_data, user["username"],
                  body.selected_approvers, body.variables)
    if body.create_submission and view.get("form_code"):
        form = db.q1("SELECT * FROM forms WHERE code=?", (view["form_code"],))
        if form:
            schema = (db.loads(form, "schema") or {}).get("schema") or []
            checked = form_rules.validate_data(schema, view["form_data"],
                                               form_id=form["id"], check_unique=False)
            sid = db.insert("form_submissions", {
                "form_id": form["id"], "data": view["form_data"],
                "computed": checked["computed"], "status": "submitted",
                "submitted_by": user["username"], "form_version": form["version"],
                "flow_instance_id": view["id"], "updated_at": db.now(),
                "created_at": db.now()})
            view["submission_id"] = sid
    deps.audit(user["username"], "workflow.start", f"workflow:{row['code']}",
               {"instance": view["id"], "nodes": len(view["current_nodes"])}, request=request)
    return view


@router.post("/{workflow_id}/run", status_code=201, summary="Synchronous dry-run of a workflow")
def run_workflow(workflow_id: int, body: RunIn,
                 user: dict = Depends(deps.require("workflow:run")), request: Request = None):
    row = _wf_or_404(workflow_id)
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    errors = workflow_engine.validate_graph(graph)
    if errors:
        raise HTTPException(status_code=400, detail="Invalid graph: " + "; ".join(errors))
    iid = db.insert("workflow_instances", {
        "workflow_id": workflow_id, "status": "running", "context": body.context,
        "logs": [], "graph": graph, "form_data": {}, "form_code": row.get("form_code"),
        "started_by": user["username"], "started_at": db.now(),
        "workflow_version": row["version"]})
    result = workflow_engine.run(graph, body.context, user["username"])
    db.update("workflow_instances", iid, {"status": "completed" if result["status"] == "completed"
                                          else result["status"],
                                          "context": result["context"], "logs": result["logs"],
                                          "finished_at": db.now()})
    deps.audit(user["username"], "workflow.run", f"workflow:{row['code']}",
               {"instance": iid, "status": result["status"]}, request=request)
    return {"instance_id": iid, "workflow": row["code"], **result}


@router.get("/{workflow_id}/instances", summary="List instances of a workflow")
def list_instances(workflow_id: int, limit: int = 50, status: str | None = None,
                   user: dict = Depends(deps.require("workflow:read"))):
    _wf_or_404(workflow_id)
    frag, scope_args = data_scope.owner_clause(user, "workflow_instances")
    sql = "SELECT * FROM workflow_instances WHERE workflow_id=?" + (f" AND {frag}" if frag else "")
    args: list = [workflow_id, *scope_args]
    if status:
        sql += " AND status=?"
        args.append(status)
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 200)))
    out = []
    for r in rows:
        d = db.loads(r, "context", "logs", "graph", "form_data", "current_nodes", "variables") or {}
        d["task_count"] = int(db.scalar("SELECT COUNT(*) FROM flow_tasks WHERE instance_id=?",
                                        (r["id"],)) or 0)
        out.append(d)
    return {"instances": out, "total": len(out)}
