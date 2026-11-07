"""MCP transport surface: tool catalog, server status, call journal and REST invoke.

MCP *servers* are managed separately under ``/mcp/servers``; installable
*Skills* are managed under ``/skills``. This router owns only the shared MCP
concerns (tools, status, journal, invocation).
"""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import Response

from .. import db, deps
from ..config import settings
from ..services import mcp_journal, mcp_servers, mcp_tools

router = APIRouter(prefix="/mcp", tags=["MCP"])


class InvokeIn(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)
    target: str | None = None


# --------------------------------------------------------------------------- #
# Tool catalog + server status
# --------------------------------------------------------------------------- #
@router.get("/tools", summary="Platform + enabled-server MCP tool catalog")
def tools(_user: dict = Depends(deps.require("mcp:read"))):
    specs = mcp_tools.list_tools()
    return {"tools": specs, "total": len(specs),
            "builtin_tools": len(mcp_tools.TOOL_SPECS),
            "external_tools": len(specs) - len(mcp_tools.TOOL_SPECS),
            "permissions": mcp_tools.PERMISSION_MAP}


@router.get("/status", summary="MCP transport status")
def status(_user: dict = Depends(deps.require("mcp:read"))):
    servers = mcp_servers.stats()
    by_status = {r["status"]: r["count"] for r in db.q(
        "SELECT status, COUNT(*) AS count FROM mcp_skills GROUP BY status")}
    return {"enabled": settings.mcp_enabled, "endpoint": "/mcp",
            "transport": "streamable-http", "stateless": settings.mcp_stateless,
            "protocol_version": "2025-06-18",
            "tool_count": len(mcp_tools.list_tools()),
            "builtin_tool_count": len(mcp_tools.TOOL_SPECS),
            "external_servers": settings.mcp_external_servers,
            "servers": servers,
            "skills": int(db.scalar("SELECT COUNT(*) FROM mcp_skills") or 0),
            "skill_statuses": by_status,
            "journal": {"enabled": True,
                        "total": int(db.scalar("SELECT COUNT(*) FROM mcp_call_logs") or 0),
                        "sources": list(mcp_journal.SOURCES)}}


# --------------------------------------------------------------------------- #
# Call journal  (static routes MUST precede /calls/{call_id})
# --------------------------------------------------------------------------- #
@router.get("/calls", summary="Query the MCP call journal")
def list_calls(tool: str | None = None, source: str | None = None,
               status: str | None = None, actor: str | None = None,
               method: str | None = None, q: str | None = None,
               limit: int = 100, offset: int = 0,
               _user: dict = Depends(deps.require("mcp:read"))):
    return mcp_journal.query(limit=limit, offset=offset, tool=tool, source=source,
                             status=status, actor=actor, method=method, q=q)


@router.get("/calls/stats", summary="MCP call journal statistics")
def call_stats(_user: dict = Depends(deps.require("mcp:read"))):
    return mcp_journal.stats()


@router.get("/calls/export", summary="Export the MCP call journal as CSV")
def export_calls(tool: str | None = None, source: str | None = None,
                 status: str | None = None, q: str | None = None,
                 _user: dict = Depends(deps.require("mcp:read"))):
    rows = mcp_journal.export(tool=tool, source=source, status=status, q=q)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "source", "method", "tool", "target", "actor",
                     "status", "duration_ms", "arguments", "error"])
    for row in rows:
        writer.writerow([row.get("id"), row.get("created_at"), row.get("source"),
                         row.get("method"), row.get("tool") or "", row.get("target") or "",
                         row.get("actor") or "", row.get("status"), row.get("duration_ms"),
                         json.dumps(row.get("arguments") or {}, ensure_ascii=False),
                         row.get("error") or ""])
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="mcp-call-journal.csv"'})


@router.get("/calls/{call_id}", summary="Get one MCP call journal entry")
def get_call(call_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    row = mcp_journal.get(call_id)
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return row


@router.delete("/calls", summary="Clear the MCP call journal")
def clear_calls(user: dict = Depends(deps.require("mcp:write")), request: Request = None):
    deleted = mcp_journal.clear()
    deps.audit(user["username"], "mcp.journal.clear", "mcp_call_logs",
               {"deleted": deleted}, request=request)
    return {"ok": True, "deleted": deleted}


# --------------------------------------------------------------------------- #
# Invoke
# --------------------------------------------------------------------------- #
@router.post("/invoke", summary="Invoke a platform or registered MCP tool over REST")
def invoke(body: InvokeIn, user: dict = Depends(deps.require("mcp:invoke")),
           request: Request = None):
    mcp_tools.bind_context(source="rest", transport="http", method="invoke",
                           actor=user["username"], request_id=db.uid()[:12],
                           target=body.target)
    try:
        result = mcp_tools.call_tool(body.tool, body.arguments, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    deps.audit(user["username"], "mcp.invoke", f"tool:{body.tool}",
               {"arguments": body.arguments, "target": body.target}, request=request)
    return {"tool": body.tool, "result": result}
