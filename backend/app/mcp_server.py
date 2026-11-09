"""MCP exposure for the whole platform (streamable HTTP at /mcp).

Primary backend: ``fastmcp`` (real MCP SDK, full JSON Schema generation).
Fallback backend: a self-contained JSON-RPC ASGI implementation, so MCP keeps
working even when the optional SDK is not installed.
Both share the single tool registry in ``services.mcp_tools``.
"""
from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import db
from .config import settings
from .services import mcp_tools

SERVER_INFO = {"name": "ai-lowcode-platform", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-06-18"


# --------------------------------------------------------------------------- #
# Backend A: fastmcp SDK
# --------------------------------------------------------------------------- #
def _build_fastmcp() -> tuple[list[Any], Any, str]:
    from fastmcp import FastMCP

    mcp = FastMCP(
        "ai-lowcode-platform",
        instructions=(
            "AI Low-Code Platform MCP server. Use these tools to list and submit forms, "
            "run approval workflows, search the knowledge base, query business records "
            "and read platform statistics."
        ),
    )

    @mcp.tool
    def list_forms(status: str | None = None) -> dict:
        """List form definitions, optionally filtered by draft/published/archived."""
        return mcp_tools.call_tool("list_forms", {"status": status} if status else {})

    @mcp.tool
    def get_form(code: str) -> dict:
        """Get a full form definition including its field schema."""
        return mcp_tools.call_tool("get_form", {"code": code})

    @mcp.tool
    def submit_form(code: str, data: dict) -> dict:
        """Submit data to a published form."""
        return mcp_tools.call_tool("submit_form", {"code": code, "data": data})

    @mcp.tool
    def query_records(form_code: str | None = None, limit: int = 20) -> dict:
        """Query form submissions / business records."""
        args = {"limit": limit}
        if form_code:
            args["form_code"] = form_code
        return mcp_tools.call_tool("query_records", args)

    @mcp.tool
    def list_workflows(status: str | None = None) -> dict:
        """List workflow definitions."""
        return mcp_tools.call_tool("list_workflows", {"status": status} if status else {})

    @mcp.tool
    def get_workflow(code: str) -> dict:
        """Get a workflow DAG by code."""
        return mcp_tools.call_tool("get_workflow", {"code": code})

    @mcp.tool
    def run_workflow(code: str, context: dict | None = None) -> dict:
        """Start a workflow instance with an initial context."""
        return mcp_tools.call_tool("run_workflow", {"code": code, "context": context or {}})

    @mcp.tool
    def get_workflow_instance(instance_id: int) -> dict:
        """Get status and logs of a workflow instance."""
        return mcp_tools.call_tool("get_workflow_instance", {"instance_id": instance_id})

    @mcp.tool
    def list_collections() -> dict:
        """List knowledge base collections."""
        return mcp_tools.call_tool("list_collections", {})

    @mcp.tool
    def search_knowledge(query: str, top_k: int = 4) -> dict:
        """Search the knowledge base and return grounded excerpts."""
        return mcp_tools.call_tool("search_knowledge", {"query": query, "top_k": top_k})

    @mcp.tool
    def list_users() -> dict:
        """List platform users and their roles."""
        return mcp_tools.call_tool("list_users", {})

    @mcp.tool
    def get_stats() -> dict:
        """Platform dashboard statistics."""
        return mcp_tools.call_tool("get_stats", {})

    @mcp.tool
    def call_remote_tool(name: str, arguments: dict | None = None) -> dict:
        """Invoke a tool declared by a registered third-party MCP server."""
        return mcp_tools.call_tool(name, arguments or {})

    http_app = mcp.http_app(
        path="/mcp",
        stateless_http=settings.mcp_stateless,
        json_response=settings.mcp_json_response,
    )
    return list(http_app.routes), http_app, "fastmcp"


# --------------------------------------------------------------------------- #
# Backend B: dependency-free JSON-RPC implementation
# --------------------------------------------------------------------------- #
def _resources() -> list[dict]:
    res = [{"uri": "platform://stats", "name": "Platform statistics",
            "mimeType": "application/json", "description": "Live dashboard counters"}]
    for row in db.q("SELECT code,name FROM forms"):
        res.append({"uri": f"platform://forms/{row['code']}", "name": row["name"],
                    "mimeType": "application/json", "description": "Form definition"})
    for row in db.q("SELECT code,name FROM workflows"):
        res.append({"uri": f"platform://workflows/{row['code']}", "name": row["name"],
                    "mimeType": "application/json", "description": "Workflow definition"})
    return res


def _read_resource(uri: str) -> dict:
    if uri == "platform://stats":
        return mcp_tools.call_tool("get_stats", {})
    if uri.startswith("platform://forms/"):
        return mcp_tools.call_tool("get_form", {"code": uri.split("/")[-1]})
    if uri.startswith("platform://workflows/"):
        return mcp_tools.call_tool("get_workflow", {"code": uri.split("/")[-1]})
    raise ValueError(f"Unknown resource: {uri}")


PROMPTS = [
    {"name": "analyze_workflow", "description": "Analyze a workflow definition and suggest improvements",
     "arguments": [{"name": "code", "description": "Workflow code", "required": True}]},
    {"name": "answer_from_kb", "description": "Answer a question grounded in the knowledge base",
     "arguments": [{"name": "question", "description": "User question", "required": True}]},
]


async def _rpc_endpoint(request):
    if request.method == "GET":
        return JSONResponse({"name": SERVER_INFO["name"], "version": SERVER_INFO["version"],
                             "transport": "streamable-http (builtin)", "protocolVersion": PROTOCOL_VERSION,
                             "tools": len(mcp_tools.TOOL_SPECS)})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    method, params, mid = body.get("method"), body.get("params") or {}, body.get("id")
    try:
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {"listChanged": False}, "resources": {},
                                      "prompts": {}},
                      "serverInfo": SERVER_INFO,
                      "instructions": "AI Low-Code Platform MCP server."}
        elif method in {"notifications/initialized", "notifications/cancelled"}:
            return Response(status_code=202)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": mcp_tools.list_tools(user=mcp_tools.current_user())}
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                result = mcp_tools.as_mcp_content(mcp_tools.call_tool(name, args))
            except Exception as exc:
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        elif method == "resources/list":
            result = {"resources": _resources()}
        elif method == "resources/read":
            result = {"contents": [{"uri": params.get("uri"), "mimeType": "application/json",
                                    "text": json.dumps(_read_resource(params.get("uri") or ""),
                                                       ensure_ascii=False)}]}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": [
                {"uriTemplate": "platform://forms/{code}", "name": "Form definition"},
                {"uriTemplate": "platform://workflows/{code}", "name": "Workflow definition"}]}
        elif method == "prompts/list":
            result = {"prompts": PROMPTS}
        elif method == "prompts/get":
            question = (params.get("arguments") or {}).get("question") or \
                       (params.get("arguments") or {}).get("code") or ""
            result = {"description": f"Prompt: {params.get('name')}",
                      "messages": [{"role": "user", "content": {"type": "text", "text": str(question)}}]}
        else:
            return JSONResponse({"jsonrpc": "2.0", "id": mid,
                                 "error": {"code": -32601, "message": f"Method not found: {method}"}})
    except Exception as exc:
        return JSONResponse({"jsonrpc": "2.0", "id": mid,
                             "error": {"code": -32603, "message": str(exc)}})
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": result})


def _build_builtin() -> tuple[list[Any], Any, str]:
    routes = [Route("/mcp", _rpc_endpoint, methods=["GET", "POST"])]
    return routes, None, "builtin-jsonrpc"


def build_mcp() -> tuple[list[Any], Any, str]:
    """Return (routes, http_app_or_none, mode)."""
    if settings.mcp_enabled:
        try:
            return _build_fastmcp()
        except Exception as exc:  # pragma: no cover - dependency present in normal installs
            print(f"[mcp] fastmcp unavailable ({exc}); using builtin JSON-RPC transport")
    return _build_builtin()
