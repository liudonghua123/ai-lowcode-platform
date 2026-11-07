"""Human-centric approval runtime for domestic workflow scenarios.

The original engine executed a DAG synchronously and auto-approved every
approval node. This runtime adds the pieces real Chinese approval flows need:
approval-roles (designated users, roles, departments, department leaders and
multi-level leader chains), countersign / or-sign / sequential signing,
parallel branches and joins, reject / return / transfer / add-sign, withdrawal,
urging, timeout handling, delegation and per-node field permissions.

Runtime state is persisted on the workflow instance plus one row per assignee in
``flow_tasks``; in-flight instances pin a graph snapshot so later edits to the
definition never change a running approval.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db
from . import form_catalog, form_rules, workflow_engine

APPROVER_RULES = [
    {"code": "users", "en": "Designated members", "zh": "指定成员"},
    {"code": "roles", "en": "Role members", "zh": "按角色"},
    {"code": "departments", "en": "Department members", "zh": "按部门"},
    {"code": "initiator", "en": "Initiator", "zh": "发起人本人"},
    {"code": "initiator_leader", "en": "Initiator's department leader", "zh": "发起人部门主管"},
    {"code": "leader_chain", "en": "Multi-level leader chain", "zh": "逐级主管"},
    {"code": "form_field", "en": "Members from a form field", "zh": "表单成员字段"},
    {"code": "previous", "en": "Previous node approver", "zh": "上一节点审批人"},
    {"code": "self_select", "en": "Chosen by initiator", "zh": "发起人自选"},
]

SIGN_MODES = [
    {"code": "any", "en": "Or-sign (one approval passes)", "zh": "或签（一人同意即通过）"},
    {"code": "all", "en": "Countersign (everyone approves)", "zh": "会签（全部同意）"},
    {"code": "ratio", "en": "Ratio countersign", "zh": "按比例会签"},
    {"code": "sequence", "en": "Sequential approval", "zh": "依次审批"},
]

EMPTY_POLICIES = [
    {"code": "skip", "en": "Skip node", "zh": "自动跳过"},
    {"code": "admin", "en": "Fallback to admin", "zh": "转交管理员"},
    {"code": "auto_approve", "en": "Auto approve", "zh": "自动通过"},
    {"code": "fail", "en": "Fail the instance", "zh": "终止流程"},
]

TIMEOUT_ACTIONS = [
    {"code": "remind", "en": "Remind only", "zh": "仅提醒"},
    {"code": "auto_approve", "en": "Auto approve", "zh": "自动同意"},
    {"code": "auto_reject", "en": "Auto reject", "zh": "自动拒绝"},
    {"code": "transfer_admin", "en": "Transfer to admin", "zh": "转交管理员"},
]

ACTIONS = ["approve", "reject", "return", "transfer", "addsign_before",
           "addsign_after", "withdraw", "urge"]

NODE_CONFIG_HINTS: dict[str, list[str]] = {
    "start": ["form_code", "initiator_scope"],
    "approval": ["approver_rule", "assignees", "sign_mode", "ratio", "leader_level",
                 "exclude_initiator", "empty_policy", "timeout_hours", "timeout_action",
                 "comment_required", "signature_required", "field_permissions",
                 "reject_policy", "allow_return", "allow_transfer", "allow_addsign"],
    "cc": ["approver_rule", "assignees"],
    "condition": ["conditions", "logic", "field", "operator", "value", "expression"],
    "parallel": [], "join": ["join_mode"], "delay": ["delay_hours"],
    "subflow": ["workflow_code"], "form": ["form_code", "assignee"],
    "ai": ["prompt", "model"], "knowledge": ["query", "top_k"],
    "http": ["method", "url", "headers", "body"],
    "notification": ["channel", "template"], "end": [],
}


def meta(lang: str = "en") -> dict:
    def lbl(items: list[dict]) -> list[dict]:
        return [{"code": i["code"], "label": i.get(lang, i["en"])} for i in items]
    return {"approver_rules": lbl(APPROVER_RULES), "sign_modes": lbl(SIGN_MODES),
            "empty_policies": lbl(EMPTY_POLICIES), "timeout_actions": lbl(TIMEOUT_ACTIONS),
            "actions": ACTIONS, "node_config": NODE_CONFIG_HINTS,
            "operators": [o["code"] for o in form_catalog.OPERATORS]}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return fallback
    return value


def _active_users() -> list[dict]:
    rows = db.q("SELECT username, dept, role_ids FROM users WHERE status='active'")
    out = []
    for r in rows:
        d = dict(r)
        d["role_ids"] = _json(d.get("role_ids"), [])
        out.append(d)
    return out


def _apply_delegations(names: list[str]) -> list[str]:
    if not names:
        return names
    now = _now()
    out = []
    for name in names:
        row = db.q1("SELECT agent FROM flow_delegations WHERE principal=? AND enabled=1 "
                    "AND (starts_at IS NULL OR starts_at<=?) AND (ends_at IS NULL OR ends_at>=?) "
                    "ORDER BY id DESC LIMIT 1", (name, now, now))
        out.append(row["agent"] if row and row["agent"] else name)
    return out


def _leaders_of(dept: str | None, levels: int) -> list[str]:
    """Walk up org_units collecting each unit's leader (逐级主管)."""
    out: list[str] = []
    code = dept
    seen: set[str] = set()
    for _ in range(max(1, levels)):
        if not code or code in seen:
            break
        seen.add(code)
        unit = db.q1("SELECT * FROM org_units WHERE code=?", (code,))
        if not unit:
            break
        if unit["leader"] and unit["leader"] not in out:
            out.append(unit["leader"])
        code = unit["parent_code"]
    return out


def resolve_assignees(node: dict, state: dict, *, previous: str | None = None) -> tuple[list[str], str]:
    """Resolve the assignee list for a node; returns (names, policy_used)."""
    cfg = node.get("config") or {}
    rule = cfg.get("approver_rule") or "roles"
    actor = state.get("initiator") or "admin"
    form_data = state.get("form_data") or {}
    names: list[str] = []
    users = _active_users()

    if rule == "users":
        names = [str(x) for x in (cfg.get("assignees") or []) if x]
    elif rule == "roles":
        wanted = {str(x) for x in (cfg.get("roles") or cfg.get("assignees") or [])}
        if not wanted and cfg.get("approver_role"):  # legacy definitions
            wanted = {str(cfg["approver_role"])}
        for u in users:
            roles = {str(x) for x in (u["role_ids"] or [])}
            # accept role codes or numeric role ids
            role_codes = {str(x) for x in _roles_for_ids(roles)}
            if wanted & (roles | role_codes):
                names.append(u["username"])
    elif rule == "departments":
        wanted = {str(x) for x in (cfg.get("departments") or cfg.get("assignees") or [])}
        names = [u["username"] for u in users if str(u["dept"]) in wanted]
    elif rule == "initiator":
        names = [actor]
    elif rule in {"initiator_leader", "leader_chain"}:
        dept = next((u["dept"] for u in users if u["username"] == actor), None)
        names = _leaders_of(dept, int(cfg.get("leader_level") or 1))
    elif rule == "form_field":
        value = form_data.get(cfg.get("form_field") or cfg.get("field") or "")
        if isinstance(value, list):
            names = [str(x) for x in value if x]
        elif value:
            names = [str(value)]
    elif rule == "previous":
        names = [previous] if previous else []
    elif rule == "self_select":
        names = [str(x) for x in (state.get("selected_approvers") or []) if x]

    # de-duplicate, drop initiator if requested, then apply delegation
    seen: set[str] = set()
    names = [x for x in names if not (x in seen or seen.add(x))]
    if cfg.get("exclude_initiator"):
        names = [x for x in names if x != actor]
    names = _apply_delegations(names)

    policy = cfg.get("empty_policy") or "skip"
    if not names:
        if policy == "admin":
            names, policy = ["admin"], "admin"
        elif policy == "auto_approve":
            policy = "auto_approve"
        elif policy == "fail":
            policy = "fail"
        else:
            policy = "skip"
    return names, policy


def _roles_for_ids(ids: set[str]) -> list[str]:
    out = []
    for rid in ids:
        row = db.q1("SELECT code FROM roles WHERE id=? OR code=?", (rid, rid))
        if row:
            out.append(row["code"])
    return out


def _edges_from(graph: dict, node_id: str) -> list[dict]:
    return [e for e in (graph.get("edges") or []) if e.get("source") == node_id]


def _condition_branch(node: dict, state: dict) -> str:
    cfg = node.get("config") or {}
    data = {**(state.get("form_data") or {}), **(state.get("variables") or {}),
            **(state.get("context") or {})}
    if cfg.get("conditions"):
        rule = {"logic": cfg.get("logic") or "and", "conditions": cfg["conditions"]}
        return "true" if form_rules.check_rule(rule, data) else "false"
    return "true" if workflow_engine.evaluate_condition(cfg, data) else "false"


def _next_targets(node: dict, graph: dict, state: dict) -> list[str]:
    edges = _edges_from(graph, node["id"])
    ntype = node.get("type")
    if ntype == "condition":
        branch = _condition_branch(node, state)
        picked = [e for e in edges if str(e.get("condition") or "").lower() == branch]
        if not picked:
            picked = [e for e in edges if not e.get("condition")]
        return [e["target"] for e in picked]
    if ntype == "parallel":
        return [e["target"] for e in edges]
    return [edges[0]["target"]] if edges else []


def _log(instance_id: int, entry: dict) -> None:
    row = db.q1("SELECT logs FROM workflow_instances WHERE id=?", (instance_id,))
    logs = _json(row["logs"], []) if row else []
    logs.append({"at": _now(), **entry})
    db.update("workflow_instances", instance_id, {"logs": logs})


def _update_state(instance_id: int, **patch: Any) -> None:
    db.update("workflow_instances", instance_id, patch)


def _snapshot(instance_id: int) -> dict:
    row = db.q1("SELECT * FROM workflow_instances WHERE id=?", (instance_id,))
    if not row:
        raise ValueError("Instance not found")
    return {
        "row": dict(row),
        "graph": _json(row["graph"], {}) or {},
        "form_data": _json(row["form_data"], {}) or {},
        "variables": _json(row["variables"], {}) or {},
        "context": _json(row["context"], {}) or {},
        "current_nodes": _json(row["current_nodes"], []) or [],
        "logs": _json(row["logs"], []) or [],
        "initiator": row["started_by"],
        "workflow_version": row["workflow_version"],
        "form_code": row["form_code"],
    }


def _create_tasks(instance_id: int, node: dict, names: list[str], *,
                  round_no: int = 1, node_type: str = "approval") -> list[int]:
    cfg = node.get("config") or {}
    hours = cfg.get("timeout_hours")
    due = (datetime.now(UTC) + timedelta(hours=float(hours))).isoformat(timespec="seconds") if hours else None
    ids = []
    for seq, name in enumerate(names):
        ids.append(db.insert("flow_tasks", {
            "instance_id": instance_id, "node_id": node["id"],
            "node_name": node.get("name") or node["id"], "node_type": node_type,
            "assignee": name, "seq": seq, "status": "pending",
            "due_at": due, "created_at": _now(), "round": round_no,
        }))
    return ids


def _enter(instance_id: int, node_ids: list[str], state: dict, *, depth: int = 0) -> str:
    """Enter a set of nodes, creating tasks or advancing; returns instance status."""
    if depth > 60:
        _log(instance_id, {"event": "guard", "error": "max depth exceeded"})
        return "rejected"
    graph = state["graph"]
    nodes = {n["id"]: n for n in (graph.get("nodes") or [])}
    active = list(state["current_nodes"])
    status = state["row"]["status"]

    for nid in node_ids:
        node = nodes.get(nid)
        if not node:
            continue
        ntype = node.get("type")
        cfg = node.get("config") or {}
        if ntype == "end":
            active = [x for x in active if x != nid]
            status = "approved"
            _log(instance_id, {"event": "end", "node": nid, "name": node.get("name")})
            continue
        if ntype == "join":
            mode = cfg.get("join_mode") or "all"
            arrivals = int((state["variables"].get("join_arrivals") or {}).get(nid, 0)) + 1
            arrivals_map = dict(state["variables"].get("join_arrivals") or {})
            arrivals_map[nid] = arrivals
            incoming = [e for e in (graph.get("edges") or []) if e.get("target") == nid]
            needed = len(incoming) if mode == "all" else 1
            state["variables"]["join_arrivals"] = arrivals_map
            _update_state(instance_id, variables=state["variables"])
            _log(instance_id, {"event": "join", "node": nid, "arrivals": arrivals, "needed": needed})
            if arrivals < needed:
                continue
            state["variables"].get("join_arrivals", {}).pop(nid, None)
            _update_state(instance_id, variables=state["variables"])
            return _enter(instance_id, _next_targets(node, graph, state), state, depth=depth + 1)
        if ntype in {"approval", "cc"}:
            prev = state["variables"].get("last_approver")
            names, policy = resolve_assignees(node, state, previous=prev)
            if ntype == "cc" or not names:
                _log(instance_id, {"event": "cc" if ntype == "cc" else "no_assignee",
                                   "node": nid, "policy": policy, "names": names})
                if policy == "fail":
                    status = "rejected"
                    _log(instance_id, {"event": "failed", "node": nid, "reason": "empty approver"})
                    break
                return _enter(instance_id, _next_targets(node, graph, state), state, depth=depth + 1)
            sign_mode = cfg.get("sign_mode") or cfg.get("mode") or "any"
            if sign_mode == "sequence":
                # Only the first approver is activated; the rest are chained in order.
                state["variables"][f"sequence_remaining:{nid}"] = names[1:]
                names = names[:1]
            round_no = int((state["variables"].get("rounds") or {}).get(nid, 0)) + 1
            rounds = dict(state["variables"].get("rounds") or {})
            rounds[nid] = round_no
            state["variables"]["rounds"] = rounds
            _update_state(instance_id, variables=state["variables"])
            _create_tasks(instance_id, node, names, round_no=round_no,
                          node_type="cc" if ntype == "cc" else "approval")
            if nid not in active:
                active.append(nid)
            _log(instance_id, {"event": "tasks", "node": nid, "name": node.get("name"),
                               "assignees": names, "sign_mode": sign_mode, "round": round_no})
            continue
        # automatic nodes
        try:
            update = workflow_engine._execute_node(node, {**state["context"], **state["form_data"]})
            state["context"].update(update)
            _update_state(instance_id, context=state["context"])
            _log(instance_id, {"event": "node", "node": nid, "type": ntype, "output": update})
        except Exception as exc:
            _log(instance_id, {"event": "node_failed", "node": nid, "error": str(exc)})
            status = "rejected"
            break
        if ntype == "reject_end":
            status = "rejected"
        targets = _next_targets(node, graph, state)
        if not targets and ntype != "end":
            status = "approved" if ntype == "condition" else status
        sub = _enter(instance_id, targets, state, depth=depth + 1)
        if sub in {"approved", "rejected"}:
            status = sub

    _update_state(instance_id, current_nodes=active, status=status)
    state["current_nodes"] = active
    if status in {"approved", "rejected"}:
        _update_state(instance_id, finished_at=_now())
    return status


def start_instance(workflow: dict, form_data: dict | None = None, actor: str = "admin",
                   selected_approvers: list[str] | None = None,
                   variables: dict | None = None) -> dict:
    """Create a long-running approval instance and open its first tasks."""
    graph = _json(workflow["graph"], {}) or {}
    errors = workflow_engine.validate_graph(graph)
    if errors:
        raise ValueError("Invalid graph: " + "; ".join(errors))
    starts = [n for n in (graph.get("nodes") or []) if n.get("type") == "start"]
    if not starts:
        raise ValueError("Workflow has no start node")
    start_cfg = starts[0].get("config") or {}
    form_code = start_cfg.get("form_code") or workflow.get("form_code")
    payload = dict(form_data or {})
    if form_code:
        form = db.q1("SELECT * FROM forms WHERE code=?", (form_code,))
        if form:
            schema = _json(form["schema"], []) or []
            result = form_rules.validate_data(schema, payload, form_id=form["id"])
            if result["errors"]:
                raise ValueError("; ".join(e["message"] for e in result["errors"]))
            payload = result["data"]

    now = _now()
    iid = db.insert("workflow_instances", {
        "workflow_id": workflow["id"], "status": "running",
        "context": {**payload, "initiator": actor}, "logs": [],
        "graph": graph, "form_data": payload, "form_code": form_code,
        "current_nodes": [], "variables": dict(variables or {}),
        "workflow_version": workflow.get("version") or 1,
        "started_by": actor, "started_at": now,
    })
    state = _snapshot(iid)
    state["variables"]["initiator"] = actor
    state["variables"]["selected_approvers"] = selected_approvers or []
    _update_state(iid, variables=state["variables"])
    _log(iid, {"event": "started", "actor": actor, "workflow": workflow["code"],
               "version": workflow.get("version") or 1, "form_code": form_code})
    state = _snapshot(iid)
    state["initiator"] = actor
    state["selected_approvers"] = selected_approvers or []
    status = _enter(iid, _next_targets(starts[0], graph, state), state)
    return instance_view(iid, status)


def _pending_tasks(instance_id: int, node_id: str | None = None,
                   round_no: int | None = None) -> list[dict]:
    sql = "SELECT * FROM flow_tasks WHERE instance_id=? AND status='pending'"
    args: list[Any] = [instance_id]
    if node_id:
        sql += " AND node_id=?"
        args.append(node_id)
    if round_no is not None:
        sql += " AND round=?"
        args.append(round_no)
    return [dict(r) for r in db.q(sql + " ORDER BY seq, id", tuple(args))]


def _node_of(state: dict, node_id: str) -> dict:
    return next((n for n in (state["graph"].get("nodes") or []) if n["id"] == node_id), {})


def act(instance_id: int, task_id: int, action: str, actor: str,
        payload: dict | None = None) -> dict:
    """Apply a human action to a task and advance the instance."""
    payload = payload or {}
    state = _snapshot(instance_id)
    if state["row"]["status"] not in {"running"}:
        raise ValueError("Instance is not running")
    task = db.q1("SELECT * FROM flow_tasks WHERE id=? AND instance_id=?", (task_id, instance_id))
    if not task:
        raise ValueError("Task not found")
    if task["status"] != "pending":
        raise ValueError("Task is not pending")
    assignees = _apply_delegations([task["assignee"]])
    if actor not in assignees and actor not in {"admin", "system"}:
        raise ValueError("Only the assignee can act on this task")
    node = _node_of(state, task["node_id"])
    cfg = node.get("config") or {}
    if action in {"approve", "reject"} and cfg.get("comment_required") and not payload.get("comment"):
        raise ValueError("Approval comment is required")
    if action in {"approve"} and cfg.get("signature_required") and not payload.get("signature"):
        raise ValueError("Handwritten signature is required")

    now = _now()
    if action == "approve":
        db.update("flow_tasks", task_id, {"status": "approved", "decision": "approved",
                                          "comment": payload.get("comment"),
                                          "signature": payload.get("signature"), "acted_at": now})
    elif action == "reject":
        db.update("flow_tasks", task_id, {"status": "rejected", "decision": "rejected",
                                          "comment": payload.get("comment"), "acted_at": now})
    elif action == "return":
        db.update("flow_tasks", task_id, {"status": "returned", "decision": "returned",
                                          "comment": payload.get("comment"), "acted_at": now})
    elif action == "transfer":
        target = payload.get("assignee")
        if not target:
            raise ValueError("Transfer target is required")
        db.update("flow_tasks", task_id, {"status": "transferred", "decision": "transferred",
                                          "comment": payload.get("comment"), "acted_at": now,
                                          "delegated_from": task["assignee"]})
        db.insert("flow_tasks", {"instance_id": instance_id, "node_id": task["node_id"],
                                 "node_name": task["node_name"], "node_type": task["node_type"],
                                 "assignee": target, "seq": task["seq"], "status": "pending",
                                 "due_at": task["due_at"], "created_at": now,
                                 "round": task["round"], "delegated_from": task["assignee"]})
        _log(instance_id, {"event": "transfer", "node": task["node_id"],
                           "from": task["assignee"], "to": target, "actor": actor})
        return instance_view(instance_id)
    elif action in {"addsign_before", "addsign_after"}:
        target = payload.get("assignee")
        if not target:
            raise ValueError("Added approver is required")
        seq = task["seq"] - 0.5 if action == "addsign_before" else task["seq"] + 0.5
        db.insert("flow_tasks", {"instance_id": instance_id, "node_id": task["node_id"],
                                 "node_name": task["node_name"], "node_type": task["node_type"],
                                 "assignee": target, "seq": seq, "status": "pending",
                                 "due_at": task["due_at"], "created_at": now,
                                 "round": task["round"]})
        _log(instance_id, {"event": "addsign", "node": task["node_id"], "actor": actor,
                           "assignee": target, "position": action})
        return instance_view(instance_id)
    else:
        raise ValueError(f"Unsupported action: {action}")

    _log(instance_id, {"event": action, "node": task["node_id"], "actor": actor,
                       "task": task_id, "comment": payload.get("comment")})
    state["variables"]["last_approver"] = task["assignee"]

    if action == "return":
        return _handle_return(instance_id, state, task, payload)
    if action == "reject":
        policy = cfg.get("reject_policy") or "terminate"
        if policy == "return":
            return _handle_return(instance_id, state, task, payload)
        db.run("UPDATE flow_tasks SET status='skipped' WHERE instance_id=? AND node_id=? "
               "AND status='pending'", (instance_id, task["node_id"]))
        _update_state(instance_id, status="rejected", current_nodes=[], finished_at=now)
        return instance_view(instance_id, "rejected")

    # Decide whether the node is complete.
    sign_mode = cfg.get("sign_mode") or cfg.get("mode") or "any"
    group = [dict(r) for r in db.q(
        "SELECT * FROM flow_tasks WHERE instance_id=? AND node_id=? AND round=?",
        (instance_id, task["node_id"], task["round"]))]
    pending = [t for t in group if t["status"] == "pending"]
    approved = [t for t in group if t["status"] == "approved"]
    total = len(group)
    passed = False
    if sign_mode == "any":
        passed = bool(approved)
    elif sign_mode == "all":
        passed = not pending and len(approved) == total
    elif sign_mode == "ratio":
        ratio = float(cfg.get("ratio") or 0.5)
        passed = (len(approved) / total if total else 0) >= ratio
    elif sign_mode == "sequence":
        remaining = state["variables"].get(f"sequence_remaining:{task['node_id']}") or []
        if remaining:
            nxt = remaining.pop(0)
            state["variables"][f"sequence_remaining:{task['node_id']}"] = remaining
            _update_state(instance_id, variables=state["variables"])
            db.insert("flow_tasks", {"instance_id": instance_id, "node_id": task["node_id"],
                                     "node_name": task["node_name"], "node_type": "approval",
                                     "assignee": nxt, "seq": len(group), "status": "pending",
                                     "due_at": task["due_at"], "created_at": now,
                                     "round": task["round"]})
            _log(instance_id, {"event": "sequence_next", "node": task["node_id"], "assignee": nxt})
            return instance_view(instance_id)
        passed = not pending

    if passed:
        db.run("UPDATE flow_tasks SET status='skipped' WHERE instance_id=? AND node_id=? "
               "AND status='pending'", (instance_id, task["node_id"]))
        state = _snapshot(instance_id)
        state["initiator"] = state["row"]["started_by"]
        state["selected_approvers"] = state["variables"].get("selected_approvers") or []
        state["current_nodes"] = [x for x in state["current_nodes"] if x != task["node_id"]]
        _update_state(instance_id, current_nodes=state["current_nodes"])
        status = _enter(instance_id, _next_targets(node, state["graph"], state), state)
        return instance_view(instance_id, status)
    return instance_view(instance_id)


def _handle_return(instance_id: int, state: dict, task: dict, payload: dict) -> dict:
    """Return to initiator / previous node / a named node and reopen its tasks."""
    target = payload.get("return_to") or "initiator"
    graph = state["graph"]
    start = next((n for n in (graph.get("nodes") or []) if n.get("type") == "start"), {})
    if target == "initiator":
        node_ids = _next_targets(start, graph, state)
    elif target == "previous":
        previous = [e["source"] for e in (graph.get("edges") or []) if e.get("target") == task["node_id"]]
        node_ids = previous or _next_targets(start, graph, state)
    elif str(target).startswith("node:"):
        node_ids = [str(target).split(":", 1)[1]]
    else:
        node_ids = [target] if target in {n["id"] for n in (graph.get("nodes") or [])} else \
            _next_targets(start, graph, state)
    db.run("UPDATE flow_tasks SET status='skipped' WHERE instance_id=? AND status='pending'",
           (instance_id,))
    _update_state(instance_id, status="running", current_nodes=[],
                  variables=state["variables"], finished_at=None)
    _log(instance_id, {"event": "returned", "from": task["node_id"],
                       "to": node_ids, "actor": state["row"]["started_by"],
                       "comment": payload.get("comment")})
    fresh = _snapshot(instance_id)
    fresh["initiator"] = state["row"]["started_by"]
    fresh["selected_approvers"] = state["variables"].get("selected_approvers") or []
    status = _enter(instance_id, node_ids, fresh)
    return instance_view(instance_id, status)


def withdraw(instance_id: int, actor: str, reason: str = "") -> dict:
    state = _snapshot(instance_id)
    if state["row"]["started_by"] != actor and actor != "admin":
        raise ValueError("Only the initiator can withdraw")
    if state["row"]["status"] != "running":
        raise ValueError("Only running instances can be withdrawn")
    db.run("UPDATE flow_tasks SET status='skipped' WHERE instance_id=? AND status='pending'",
           (instance_id,))
    _update_state(instance_id, status="canceled", current_nodes=[], finished_at=_now())
    _log(instance_id, {"event": "withdrawn", "actor": actor, "reason": reason})
    return instance_view(instance_id, "canceled")


def urge(instance_id: int, actor: str, message: str = "") -> dict:
    state = _snapshot(instance_id)
    if state["row"]["status"] != "running":
        raise ValueError("Only running instances can be urged")
    tasks = _pending_tasks(instance_id)
    _log(instance_id, {"event": "urged", "actor": actor, "message": message,
                       "assignees": [t["assignee"] for t in tasks]})
    return {"instance_id": instance_id, "urged": len(tasks),
            "assignees": [t["assignee"] for t in tasks]}


def sweep_timeouts() -> dict:
    """Apply configured timeout policies to overdue pending tasks."""
    now = _now()
    rows = [dict(r) for r in db.q(
        "SELECT * FROM flow_tasks WHERE status='pending' AND due_at IS NOT NULL AND due_at<?",
        (now,))]
    handled = 0
    for task in rows:
        state = _snapshot(task["instance_id"])
        node = _node_of(state, task["node_id"])
        action = (node.get("config") or {}).get("timeout_action") or "remind"
        _log(task["instance_id"], {"event": "timeout", "node": task["node_id"],
                                    "task": task["id"], "action": action})
        if action == "auto_approve":
            act(task["instance_id"], task["id"], "approve", "system",
                {"comment": "Auto approved on timeout"})
        elif action == "auto_reject":
            act(task["instance_id"], task["id"], "reject", "system",
                {"comment": "Auto rejected on timeout"})
        elif action == "transfer_admin":
            act(task["instance_id"], task["id"], "transfer", "system", {"assignee": "admin"})
        handled += 1
    return {"checked": len(rows), "handled": handled, "at": now}


def form_schema_for_node(instance_id: int, node_id: str | None = None) -> dict:
    """Return the form schema with the active node's field permissions applied."""
    state = _snapshot(instance_id)
    form = db.q1("SELECT * FROM forms WHERE code=?", (state["form_code"],))
    if not form:
        return {"fields": [], "permissions": {}, "form_code": state["form_code"]}
    schema = _json(form["schema"], []) or []
    active = node_id or (state["current_nodes"] or [None])[0]
    node = _node_of(state, active) if active else {}
    rendered = form_rules.render_schema(schema, node_config=node.get("config"),
                                        data=state["form_data"])
    rendered["form_code"] = state["form_code"]
    rendered["node_id"] = active
    return rendered


def instance_view(instance_id: int, status: str | None = None) -> dict:
    state = _snapshot(instance_id)
    tasks = [dict(r) for r in db.q(
        "SELECT * FROM flow_tasks WHERE instance_id=? ORDER BY round, seq, id", (instance_id,))]
    row = state["row"]
    return {
        "id": instance_id, "workflow_id": row["workflow_id"],
        "status": status or row["status"], "form_code": row["form_code"],
        "form_data": state["form_data"], "variables": state["variables"],
        "context": state["context"], "current_nodes": state["current_nodes"],
        "workflow_version": row["workflow_version"], "started_by": row["started_by"],
        "started_at": row["started_at"], "finished_at": row["finished_at"],
        "logs": state["logs"], "tasks": tasks,
        "pending": [t for t in tasks if t["status"] == "pending"],
    }
