"""Registry of MCP servers, managed independently from Skills.

A *server* is a connection to an MCP endpoint (builtin / streamable HTTP / SSE /
stdio). A *Skill* (see ``skill_catalog``/``skill_files``) is an installable
capability package with editable files. The two are separate entities: a skill
may optionally reference a server through ``mcp_skills.server_id``, but each has
its own lifecycle, routes and UI.

Enabled servers also contribute their declared tools to the shared tool
registry, so an agent bound to specific servers can really call remote tools.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .. import db

TRANSPORTS = ("builtin", "http", "sse", "stdio")
STATUSES = ("active", "inactive", "error")


def _out(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = db.loads(row, "tools", "auth_config") or {}
    out["enabled"] = bool(out.get("enabled"))
    out["tools"] = out.get("tools") or []
    out["auth_config"] = out.get("auth_config") or {}
    out["tool_count"] = len(out["tools"])
    out.pop("auth_config_token", None)
    return out


def rows(*, enabled_only: bool = False, ids: list[int] | None = None) -> list[dict]:
    sql = "SELECT * FROM mcp_servers WHERE 1=1"
    args: list[Any] = []
    if enabled_only:
        sql += " AND enabled=1 AND status!='error'"
    if ids:
        marks = ",".join("?" for _ in ids)
        sql += f" AND id IN ({marks})"
        args.extend(ids)
    return [_out(r) or {} for r in db.q(sql + " ORDER BY id", tuple(args))]


def get(server_id: int) -> dict | None:
    return _out(db.q1("SELECT * FROM mcp_servers WHERE id=?", (server_id,)))


def get_by_code(code: str) -> dict | None:
    return _out(db.q1("SELECT * FROM mcp_servers WHERE code=?", (code,)))


def auth_token(server: dict) -> str:
    return str((server.get("auth_config") or {}).get("token") or "")


def _headers(server: dict) -> dict[str, str]:
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    token = auth_token(server)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_rpc(text: str) -> dict | None:
    """Parse a JSON-RPC response that may be plain JSON or an SSE event stream."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except ValueError:
                continue
    return None


def probe(server: dict) -> tuple[str, list[dict], str]:
    """Return (health, tools, message) after probing the server connection."""
    if server.get("transport") == "builtin":
        from . import mcp_tools  # local import avoids a module-level cycle

        tools = mcp_tools.list_tools()
        return "healthy", tools, "Synced from the platform tool registry."
    if server.get("transport") == "stdio":
        return "manual", list(server.get("tools") or []), (
            "stdio servers run on the host; declare their tools manually.")
    endpoint = server.get("endpoint")
    if not endpoint:
        return "unconfigured", list(server.get("tools") or []), "Set an endpoint to enable probing."
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "ai-lowcode-platform", "version": "0.1.0"}}}
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    try:
        with httpx.Client(timeout=8) as client:
            client.post(endpoint, json=init, headers=_headers(server))
            r = client.post(endpoint, json=listing, headers=_headers(server))
            payload = parse_rpc(r.text) or {}
            remote = ((payload.get("result") or {}).get("tools")) or []
            if remote:
                tools = [{"name": t.get("name"),
                          "description": t.get("description") or "",
                          "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}}
                         for t in remote if t.get("name")]
                return "healthy", tools, f"Discovered {len(tools)} remote tools."
            return "unreachable", list(server.get("tools") or []), (
                "Endpoint replied without a tool list; keeping declared tools.")
    except Exception as exc:  # network / protocol failures are expected for demo servers
        return "unreachable", list(server.get("tools") or []), (
            f"Probe failed: {str(exc)[:160]}. Keeping declared tools.")


def sync(server_id: int) -> dict:
    server = get(server_id)
    if not server:
        return {}
    health, tools, message = probe(server)
    db.update("mcp_servers", server_id, {
        "tools": tools, "health": health, "last_sync_at": db.now(),
        "updated_at": db.now(),
        "status": "error" if health == "unreachable" else "active",
    })
    return {"ok": True, "health": health, "tools": tools, "message": message,
            "last_sync_at": db.now()}


def declared_tools(server_ids: list[int] | None = None) -> list[dict]:
    """All tools declared by enabled servers (optionally restricted by id)."""
    out: list[dict] = []
    seen: set[str] = set()
    for server in rows(enabled_only=True, ids=server_ids):
        for tool in server.get("tools") or []:
            name = tool.get("name") if isinstance(tool, dict) else None
            if name and name not in seen:
                seen.add(name)
                out.append({"name": name, "description": tool.get("description") or "",
                            "inputSchema": tool.get("inputSchema") or
                            {"type": "object", "properties": {}},
                            "server": server["code"]})
    return out


def external_specs(names: set[str] | None = None,
                   server_ids: list[int] | None = None) -> list[dict]:
    """Tool specs (MCP shape) for remote tools not implemented by the platform."""
    from . import mcp_tools  # local import avoids a module-level cycle

    builtin = {t["name"] for t in mcp_tools.TOOL_SPECS}
    specs = []
    for tool in declared_tools(server_ids):
        if tool["name"] in builtin:
            continue
        if names is not None and tool["name"] not in names:
            continue
        specs.append({"name": tool["name"], "description": tool["description"],
                      "inputSchema": tool["inputSchema"]})
    return specs


def find_external(name: str) -> tuple[dict, dict] | None:
    """Locate the enabled server that declares a remote tool."""
    from . import mcp_tools  # local import avoids a module-level cycle

    if name in mcp_tools.HANDLERS:
        return None
    for tool in declared_tools():
        if tool["name"] != name:
            continue
        for server in rows(enabled_only=True):
            if any(isinstance(t, dict) and t.get("name") == name
                   for t in (server.get("tools") or [])):
                return server, tool
    return None


def invoke_external(server: dict, name: str, args: dict) -> dict:
    """Call ``tools/call`` on a remote streamable-HTTP MCP server."""
    endpoint = server.get("endpoint")
    if not endpoint:
        return {"error": f"Server {server['code']} has no endpoint configured",
                "server": server["code"], "tool": name}
    if server.get("transport") == "stdio":
        return {"error": "stdio servers require a host-side bridge",
                "server": server["code"], "tool": name}
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": args}}
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(endpoint, json=payload, headers=_headers(server))
            body = parse_rpc(r.text) or {}
    except Exception as exc:
        return {"error": f"Remote MCP call failed: {str(exc)[:180]}",
                "server": server["code"], "tool": name}
    if body.get("error"):
        return {"error": str(body["error"])[:300], "server": server["code"], "tool": name}
    result = body.get("result") or {}
    if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        text = "\n".join(str(c.get("text", "")) for c in content
                         if isinstance(c, dict) and c.get("type") == "text")
        return {"text": text, "server": server["code"], "tool": name}
    return {"result": result, "server": server["code"], "tool": name}


def stats() -> dict:
    by_status = {r["status"]: r["count"] for r in db.q(
        "SELECT status, COUNT(*) AS count FROM mcp_servers GROUP BY status")}
    by_transport = {r["transport"]: r["count"] for r in db.q(
        "SELECT transport, COUNT(*) AS count FROM mcp_servers GROUP BY transport")}
    return {"total": int(db.scalar("SELECT COUNT(*) FROM mcp_servers") or 0),
            "enabled": int(db.scalar("SELECT COUNT(*) FROM mcp_servers WHERE enabled=1") or 0),
            "declared_tools": len(declared_tools()),
            "by_status": by_status, "by_transport": by_transport}
