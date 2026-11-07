"""Visual workflow orchestration API: DAG definitions, validation and execution."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..services import workflow_engine

router = APIRouter(prefix="/workflows", tags=["Workflows"])

NODE_TYPES = [
    {"type": "start", "name": "Start / 开始", "category": "control", "color": "#6366f1",
     "config": []},
    {"type": "end", "name": "End / 结束", "category": "control", "color": "#64748b",
     "config": []},
    {"type": "form", "name": "Form / 表单节点", "category": "task", "color": "#0ea5e9",
     "config": ["form_code", "assignee"]},
    {"type": "condition", "name": "Condition / 条件分支", "category": "logic", "color": "#f59e0b",
     "config": ["field", "operator", "value", "expression"]},
    {"type": "approval", "name": "Approval / 审批", "category": "task", "color": "#8b5cf6",
     "config": ["approver_role", "mode"]},
    {"type": "ai", "name": "AI / 智能处理", "category": "ai", "color": "#ec4899",
     "config": ["prompt", "model"]},
    {"type": "knowledge", "name": "Knowledge / 知识检索", "category": "ai", "color": "#14b8a6",
     "config": ["query", "top_k"]},
    {"type": "http", "name": "HTTP / 外部接口", "category": "integration", "color": "#22c55e",
     "config": ["method", "url", "headers", "body"]},
    {"type": "notification", "name": "Notification / 通知", "category": "integration", "color": "#f97316",
     "config": ["channel", "template"]},
]
OPERATORS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"]


class GraphIn(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class WorkflowIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str
    description: str | None = None
    status: str = "draft"
    graph: GraphIn = Field(default_factory=GraphIn)


class WorkflowPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    graph: GraphIn | None = None


class RunIn(BaseModel):
    context: dict = Field(default_factory=dict)


def _out(row: dict) -> dict:
    out = db.loads(row, "graph") or {}
    out["graph"] = out.get("graph") or {"nodes": [], "edges": []}
    return out


@router.get("/node-types", summary="Node palette metadata for the canvas")
def node_types(_user: dict = Depends(deps.require("workflow:read"))):
    return {"node_types": NODE_TYPES, "operators": OPERATORS}


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
                                  "graph": body.graph.model_dump(), "version": 1,
                                  "created_by": user["username"], "created_at": db.now(),
                                  "updated_at": db.now()})
    deps.audit(user["username"], "workflow.create", f"workflow:{body.code}",
               {"nodes": len(body.graph.nodes)}, request=request)
    return _out(db.q1("SELECT * FROM workflows WHERE id=?", (wid,)))


@router.get("/instances/{instance_id}", summary="Get a workflow instance")
def get_instance(instance_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    row = db.q1("SELECT * FROM workflow_instances WHERE id=?", (instance_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")
    return db.loads(row, "context", "logs")


@router.get("/{workflow_id}", summary="Get a workflow by id")
def get_workflow(workflow_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    row = db.q1("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _out(row)


@router.put("/{workflow_id}", summary="Update a workflow definition")
def update_workflow(workflow_id: int, body: WorkflowPatch,
                    user: dict = Depends(deps.require("workflow:write")), request: Request = None):
    row = db.q1("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    patch = body.model_dump(exclude_none=True)
    if "graph" in patch:
        errors = workflow_engine.validate_graph(patch["graph"])
        if errors:
            raise HTTPException(status_code=400, detail="Invalid graph: " + "; ".join(errors))
    patch["version"] = row["version"] + 1
    patch["updated_at"] = db.now()
    db.update("workflows", workflow_id, patch)
    deps.audit(user["username"], "workflow.update", f"workflow:{row['code']}",
               {"version": patch["version"]}, request=request)
    return _out(db.q1("SELECT * FROM workflows WHERE id=?", (workflow_id,)))


@router.delete("/{workflow_id}", summary="Delete a workflow")
def delete_workflow(workflow_id: int, user: dict = Depends(deps.require("workflow:write")),
                    request: Request = None):
    row = db.q1("SELECT code FROM workflows WHERE id=?", (workflow_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.run("DELETE FROM workflow_instances WHERE workflow_id=?", (workflow_id,))
    db.delete("workflows", workflow_id)
    deps.audit(user["username"], "workflow.delete", f"workflow:{row['code']}", {}, request=request)
    return {"ok": True}


@router.post("/{workflow_id}/validate", summary="Validate a graph without running it")
def validate_workflow(workflow_id: int, _user: dict = Depends(deps.require("workflow:read"))):
    row = db.q1("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    errors = workflow_engine.validate_graph(graph)
    return {"valid": not errors, "errors": errors,
            "nodes": len(graph.get("nodes") or []), "edges": len(graph.get("edges") or [])}


@router.post("/{workflow_id}/run", status_code=201, summary="Execute a workflow")
def run_workflow(workflow_id: int, body: RunIn,
                 user: dict = Depends(deps.require("workflow:run")), request: Request = None):
    row = db.q1("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    errors = workflow_engine.validate_graph(graph)
    if errors:
        raise HTTPException(status_code=400, detail="Invalid graph: " + "; ".join(errors))
    iid = db.insert("workflow_instances", {
        "workflow_id": workflow_id, "status": "running", "context": body.context,
        "logs": [], "started_by": user["username"], "started_at": db.now()})
    result = workflow_engine.run(graph, body.context, user["username"])
    db.update("workflow_instances", iid, {"status": result["status"],
                                          "context": result["context"], "logs": result["logs"],
                                          "finished_at": db.now()})
    deps.audit(user["username"], "workflow.run", f"workflow:{row['code']}",
               {"instance": iid, "status": result["status"]}, request=request)
    return {"instance_id": iid, "workflow": row["code"], **result}


@router.get("/{workflow_id}/instances", summary="List instances of a workflow")
def list_instances(workflow_id: int, limit: int = 50,
                   _user: dict = Depends(deps.require("workflow:read"))):
    rows = db.q("SELECT * FROM workflow_instances WHERE workflow_id=? ORDER BY id DESC LIMIT ?",
                (workflow_id, min(limit, 200)))
    return {"instances": [db.loads(r, "context", "logs") for r in rows], "total": len(rows)}
