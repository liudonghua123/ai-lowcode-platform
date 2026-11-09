"""DAG workflow engine: validation, condition routing and step-by-step execution."""
from __future__ import annotations

from typing import Any

from . import registry

# The palette is derived from the declarative registry so new node types
# (including runtime-registered custom ones) need no changes in this module.
NODE_TYPES = registry.node_codes()


def allowed_node_types() -> list[str]:
    """Dynamic whitelist — custom types registered at runtime are included."""
    return registry.node_codes()


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
        if n.get("type") not in allowed_node_types():
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
    """Return a partial context update produced by the node.

    Execution is delegated to the declarative registry: adding a node type
    never requires touching this engine (see ``registry.NODE_EXECUTORS``).
    """
    return registry.execute_node(node, context)


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
