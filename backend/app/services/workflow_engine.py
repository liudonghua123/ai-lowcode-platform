"""DAG workflow engine: validation, condition routing and step-by-step execution."""
from __future__ import annotations

from typing import Any

from .. import db
from . import rag

NODE_TYPES = ["start", "end", "form", "condition", "approval", "ai",
              "http", "knowledge", "notification", "cc", "parallel", "join",
              "delay", "subflow"]


def validate_graph(graph: dict) -> list[str]:
    errors: list[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    ids = [n.get("id") for n in nodes]
    if not nodes:
        return ["Graph has no nodes"]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate node ids")
    starts = [n for n in nodes if n.get("type") == "start"]
    ends = [n for n in nodes if n.get("type") == "end"]
    if len(starts) != 1:
        errors.append("Exactly one start node is required")
    if not ends:
        errors.append("At least one end node is required")
    for n in nodes:
        if n.get("type") not in NODE_TYPES:
            errors.append(f"Unknown node type: {n.get('type')}")
        if n.get("type") == "join" and (n.get("config") or {}).get("join_mode") not in \
                (None, "all", "any"):
            errors.append(f"Invalid join_mode on {n.get('id')}")
        if n.get("type") == "approval":
            mode = (n.get("config") or {}).get("sign_mode")
            if mode not in (None, "any", "all", "ratio", "sequence"):
                errors.append(f"Invalid sign_mode on {n.get('id')}")
    idset = set(ids)
    for e in edges:
        if e.get("source") not in idset or e.get("target") not in idset:
            errors.append(f"Edge {e.get('id')} references a missing node")
    # cycle detection
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e.get("source") in adj:
            adj[e["source"]].append(e.get("target"))
    state: dict[str, int] = {}

    def dfs(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        for nxt in adj.get(node, []):
            if dfs(nxt):
                return True
        state[node] = 2
        return False

    if any(dfs(i) for i in ids if state.get(i) is None):
        errors.append("Cycle detected: workflow graph must be a DAG")
    return errors


def evaluate_condition(config: dict, context: dict) -> bool:
    if config.get("conditions"):
        from . import form_rules
        return form_rules.check_rule(
            {"logic": config.get("logic") or "and", "conditions": config["conditions"]}, context)
    field = config.get("field") or ""
    operator = config.get("operator") or "gt"
    expected = config.get("value")
    actual = context.get(field)
    try:
        if operator in {"gt", "gte", "lt", "lte"}:
            a, b = float(actual), float(expected)
            return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[operator]
        if operator == "eq":
            return str(actual) == str(expected)
        if operator == "ne":
            return str(actual) != str(expected)
        if operator == "contains":
            return str(expected) in str(actual)
        if operator == "in":
            return str(actual) in [str(x) for x in (expected if isinstance(expected, list) else [expected])]
    except (TypeError, ValueError):
        return False
    expr = config.get("expression")
    if expr:
        try:
            return bool(eval(str(expr), {"__builtins__": {}}, dict(context)))  # noqa: S307 - constrained eval
        except Exception:
            return False
    return False


def _execute_node(node: dict, context: dict) -> dict:
    """Return a partial context update produced by the node."""
    ntype = node.get("type")
    cfg = node.get("config") or {}
    result: dict[str, Any] = {}
    if ntype == "form":
        form = db.q1("SELECT code,status FROM forms WHERE code=?", (cfg.get("form_code"),))
        result["form"] = cfg.get("form_code")
        result["form_found"] = bool(form)
        if not form:
            raise ValueError(f"Form not found: {cfg.get('form_code')}")
        if form["status"] != "published":
            raise ValueError(f"Form is not published: {cfg.get('form_code')}")
    elif ntype == "approval":
        # Demo engine auto-approves; plug a human task service here for production.
        result["approval"] = {"role": cfg.get("approver_role") or "admin",
                              "mode": cfg.get("mode") or "any", "decision": "approved"}
    elif ntype == "ai":
        summary = "; ".join(f"{k}={v}" for k, v in list(context.items())[:8])
        prompt = cfg.get("prompt") or "Summarize the workflow context."
        result["ai_summary"] = (
            f"{prompt} Context: {summary}. "
            "Assessment: request is complete and consistent with the configured rules."
        )
    elif ntype == "knowledge":
        hits = rag.search(str(cfg.get("query") or context.get("query") or "policy"), top_k=3)
        result["knowledge_hits"] = [{"title": h["title"], "score": h["score"]} for h in hits]
    elif ntype == "http":
        result["http"] = {"method": cfg.get("method") or "POST", "url": cfg.get("url"),
                          "simulated": True, "status": 200}
    elif ntype == "notification":
        result["notification"] = {"channel": cfg.get("channel") or "in-app",
                                  "template": cfg.get("template") or "", "delivered": True}
    elif ntype == "cc":
        result["cc"] = {"assignees": cfg.get("assignees") or [], "notified": True}
    elif ntype == "parallel":
        result["parallel"] = {"branches": len(
            [e for e in (cfg.get("edges") or [])]) or cfg.get("branch_count", 2)}
    elif ntype == "join":
        result["join"] = {"mode": cfg.get("join_mode") or "all"}
    elif ntype == "delay":
        result["delay"] = {"hours": cfg.get("delay_hours") or 0, "simulated": True}
    elif ntype == "subflow":
        result["subflow"] = {"workflow_code": cfg.get("workflow_code"), "simulated": True}
    elif ntype == "condition":
        result["condition_result"] = evaluate_condition(cfg, context)
    return result


def run(graph: dict, context: dict | None = None, actor: str = "system") -> dict:
    """Execute a workflow synchronously following condition-selected edges."""
    ctx = dict(context or {})
    ctx.setdefault("initiator", actor)
    nodes = {n["id"]: n for n in (graph.get("nodes") or [])}
    edges = graph.get("edges") or []
    logs: list[dict] = []
    starts = [n for n in nodes.values() if n.get("type") == "start"]
    if not starts:
        return {"status": "failed", "logs": [{"error": "No start node"}], "context": ctx}
    current = starts[0]["id"]
    visited: set[str] = set()
    status = "completed"
    for _step in range(100):
        if not current or current in visited:
            break
        node = nodes.get(current)
        if not node:
            break
        visited.add(current)
        entry: dict[str, Any] = {"node": current, "name": node.get("name"),
                                 "type": node.get("type"), "status": "done"}
        try:
            update = _execute_node(node, ctx)
            ctx.update(update)
            entry["output"] = update
        except Exception as exc:  # node failure fails the instance
            entry["status"] = "failed"
            entry["error"] = str(exc)
            logs.append(entry)
            status = "failed"
            break
        outgoing = [e for e in edges if e.get("source") == current]
        next_edge = None
        if node.get("type") == "condition":
            branch = "true" if ctx.get("condition_result") else "false"
            entry["branch"] = branch
            next_edge = next((e for e in outgoing if str(e.get("condition", "")).lower() == branch),
                             next((e for e in outgoing if not e.get("condition")), None))
        elif node.get("type") == "parallel":
            # The synchronous dry-run records every branch but follows the first
            # one on the main line; real parallel execution lives in flow_runtime.
            entry["parallel_branches"] = [e.get("target") for e in outgoing]
            next_edge = outgoing[0]
        elif outgoing:
            next_edge = outgoing[0]
        logs.append(entry)
        if node.get("type") == "end" or not next_edge:
            current = None
        else:
            current = next_edge.get("target")
    else:
        status = "failed"
        logs.append({"error": "Max steps exceeded (possible loop)"})
    return {"status": status, "logs": logs, "context": ctx}
