"""MCP call journal.

Every tool invocation (MCP ``tools/call``, REST ``/mcp/invoke`` and AI agent
tool steps) is recorded here together with non-invocation JSON-RPC methods.
Writing is best-effort: a journal failure must never break a tool call.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from .. import db

SOURCES = ("mcp", "rest", "agent", "internal")
STATUSES = ("success", "error")


def _preview(value: object, limit: int = 2000) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def record(*, method: str, tool: str | None = None, source: str = "internal",
           transport: str | None = None, actor: str | None = None,
           arguments: dict | None = None, status: str = "success",
           error: str | None = None, result: object = None,
           duration_ms: int = 0, request_id: str | None = None,
           target: str | None = None) -> int:
    """Persist one journal entry. Returns the row id, or 0 on failure."""
    try:
        try:
            safe_args = json.loads(json.dumps(arguments or {}, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            safe_args = {"_unserializable": True}
        return db.insert("mcp_call_logs", {
            "request_id": request_id,
            "method": method,
            "tool": tool,
            "source": source if source in SOURCES else "internal",
            "transport": transport,
            "actor": actor,
            "arguments": safe_args,
            "status": status if status in STATUSES else "error",
            "error": (error or "")[:500] or None,
            "result_preview": _preview(result),
            "target": target,
            "duration_ms": round(float(duration_ms), 2),
            "created_at": db.now(),
        })
    except Exception:
        return 0


def _out(row: dict) -> dict:
    out = db.loads(row, "arguments") or {}
    preview = out.pop("result_preview", None)
    if isinstance(preview, str) and preview:
        try:
            out["result"] = json.loads(preview)
        except ValueError:
            out["result"] = preview
    else:
        out["result"] = None
    return out


def _where(tool: str | None, source: str | None, status: str | None,
           actor: str | None, method: str | None, q: str | None) -> tuple[str, list]:
    where, args = "WHERE 1=1", []
    for field, value in (("tool", tool), ("source", source), ("status", status),
                         ("actor", actor), ("method", method)):
        if value:
            where += f" AND {field}=?"
            args.append(value)
    if q:
        where += (" AND (tool LIKE ? OR method LIKE ? OR actor LIKE ?"
                  " OR arguments LIKE ? OR error LIKE ? OR result_preview LIKE ?)")
        args += [f"%{q}%"] * 6
    return where, args


def query(*, limit: int = 100, offset: int = 0, tool: str | None = None,
          source: str | None = None, status: str | None = None,
          actor: str | None = None, method: str | None = None,
          q: str | None = None) -> dict:
    where, args = _where(tool, source, status, actor, method, q)
    total = int(db.scalar(f"SELECT COUNT(*) FROM mcp_call_logs {where}", tuple(args)) or 0)
    cap = min(max(limit, 1), 500)
    rows = db.q(f"SELECT * FROM mcp_call_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                tuple(args) + (cap, max(offset, 0)))
    return {"calls": [_out(r) for r in rows], "total": total,
            "limit": cap, "offset": max(offset, 0)}


def get(call_id: int) -> dict | None:
    row = db.q1("SELECT * FROM mcp_call_logs WHERE id=?", (call_id,))
    return _out(row) if row else None


def export(*, limit: int = 5000, **filters: str | None) -> list[dict]:
    where, args = _where(filters.get("tool"), filters.get("source"),
                         filters.get("status"), filters.get("actor"),
                         filters.get("method"), filters.get("q"))
    rows = db.q(f"SELECT * FROM mcp_call_logs {where} ORDER BY id DESC LIMIT ?",
                tuple(args) + (min(limit, 10000),))
    return [_out(r) for r in rows]


def stats() -> dict:
    total = int(db.scalar("SELECT COUNT(*) FROM mcp_call_logs") or 0)
    success = int(db.scalar("SELECT COUNT(*) FROM mcp_call_logs WHERE status='success'") or 0)
    avg = float(db.scalar("SELECT AVG(duration_ms) FROM mcp_call_logs") or 0)
    today = datetime.now(UTC).date().isoformat()
    today_count = int(db.scalar(
        "SELECT COUNT(*) FROM mcp_call_logs WHERE SUBSTR(created_at,1,10)=?", (today,)) or 0)
    by_tool = db.q(
        "SELECT COALESCE(tool, method) AS name, COUNT(*) AS count, "
        "SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END) AS errors, "
        "ROUND(AVG(duration_ms)) AS avg_ms FROM mcp_call_logs "
        "GROUP BY COALESCE(tool, method) ORDER BY count DESC LIMIT 12")
    by_source = db.q(
        "SELECT source, COUNT(*) AS count FROM mcp_call_logs GROUP BY source ORDER BY count DESC")
    timeline = db.q(
        "SELECT SUBSTR(created_at,1,10) AS day, COUNT(*) AS count, "
        "SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END) AS errors "
        "FROM mcp_call_logs GROUP BY day ORDER BY day DESC LIMIT 7")
    return {
        "total": total, "success": success, "errors": total - success,
        "success_rate": round(success / total * 100, 1) if total else 100.0,
        "avg_duration_ms": round(avg, 1), "today": today_count,
        "by_tool": by_tool, "by_source": by_source,
        "timeline": list(reversed(timeline)),
        "sources": list(SOURCES), "statuses": list(STATUSES),
        "tools": [r["name"] for r in by_tool],
    }


def clear() -> int:
    cur = db.run("DELETE FROM mcp_call_logs")
    return cur.rowcount


def ensure_demo() -> int:
    """Seed a few illustrative entries so the journal is not empty on first boot."""
    if int(db.scalar("SELECT COUNT(*) FROM mcp_call_logs") or 0):
        return 0
    samples = [
        ("initialize", None, "mcp", "success", {}, {"protocolVersion": "2025-06-18"}, 8.4, None),
        ("tools/list", None, "mcp", "success", {}, {"tools": 12}, 12.1, None),
        ("tools/call", "get_stats", "mcp", "success", {}, {"forms": 3}, 3.2, None),
        ("invoke", "search_knowledge", "rest", "success", {"query": "leave policy"},
         {"hits": 2}, 5.7, None),
        ("agent.tool", "list_forms", "agent", "success", {}, {"total": 3}, 2.9, None),
        ("invoke", "run_workflow", "rest", "error", {"code": "unknown_flow"}, None, 1.1,
         "ValueError: Workflow not found: unknown_flow"),
    ]
    base = datetime.now(UTC) - timedelta(minutes=14)
    for index, (method, tool, source, status, args, result, ms, error) in enumerate(samples):
        db.insert("mcp_call_logs", {
            "request_id": f"demo-{index:02d}", "method": method, "tool": tool,
            "source": source, "transport": "streamable-http" if source == "mcp" else "http",
            "actor": "admin" if source != "mcp" else "anonymous",
            "arguments": args, "status": status, "error": error,
            "result_preview": _preview(result), "duration_ms": ms,
            "created_at": (base + timedelta(minutes=index * 2)).isoformat(timespec="seconds"),
        })
    return len(samples)
