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
from ..services import flow_runtime, form_rules, workflow_engine

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


@router.get("/tasks", summary="Approval task center: pending / done tasks")
def task_center(status: str = Query("pending"), assignee: str | None = None,
                all_users: bool = False, limit: int = 100,
                user: dict = Depends(deps.require("workflow:read"))):
    who = assignee or (None if all_users else user["username"])
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
def get_instance(instance_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    row = db.q1("SELECT * FROM workflow_instances WHERE id=?", (instance_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")
    return flow_runtime.instance_view(instance_id)


@router.get("/instances/{instance_id}/tasks", summary="Tasks of an instance")
def instance_tasks(instance_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    return {"tasks": flow_runtime.instance_view(instance_id)["tasks"], "total": len(
        flow_runtime.instance_view(instance_id)["tasks"])}


@router.get("/instances/{instance_id}/timeline", summary="Approval timeline of an instance")
def instance_timeline(instance_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    view = flow_runtime.instance_view(instance_id)
    return {"instance_id": instance_id, "status": view["status"],
            "logs": view["logs"], "current_nodes": view["current_nodes"]}


@router.get("/instances/{instance_id}/form-schema", summary="Form schema with node field permissions")
def instance_form_schema(instance_id: int, node_id: str | None = None,
                         _user: dict = Depends(deps.require("workflow:read"))):
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
                   _user: dict = Depends(deps.require("workflow:read"))):
    _wf_or_404(workflow_id)
    sql, args = "SELECT * FROM workflow_instances WHERE workflow_id=?", [workflow_id]
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
