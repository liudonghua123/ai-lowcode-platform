# ADR-0005: fastmcp streamable HTTP with a built-in fallback and ASGI auth binding

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform Team |
| Related | `AI-001` §9, §10 · `ARC-001` §6 · `ADR-0002` |

## Context

The platform must expose a real MCP endpoint (`/mcp`) plus a registry for third-party MCP skills. Requirements also demand that every action remain RBAC-checked. Two practical problems arose during implementation:

1. The installed SDK is **`fastmcp` 4.1.6 / MCP 2.x**; the older `mcp.server.fastmcp` import path does not exist. The correct API is `FastMCP(...).http_app(path="/mcp")`.
2. `fastmcp`'s `StreamableHTTPSessionManager` requires its **lifespan** to be entered; merely extending FastAPI's route list raises `RuntimeError: task group was not initialized`.

Additionally, MCP clients are external processes — identity must be attached without breaking the ASGI app chain.

## Decision

- **Primary transport:** `mcp_server._build_fastmcp()` registers the 12 registry tools as typed `@mcp.tool` functions and returns `mcp.http_app(path="/mcp", stateless_http=..., json_response=...)`.
- **Lifespan integration:** `main.py` enters `async with mcp_http_app.lifespan(mcp_http_app): yield` inside the FastAPI lifespan, then extends `app.router.routes` with the returned routes.
- **Fallback transport:** `build_mcp()` catches any fastmcp failure and returns a dependency-free JSON-RPC ASGI route implementing `initialize`, `ping`, `tools/list`, `tools/call`, `resources/*`, `prompts/*` and notifications. MCP keeps working even without the optional SDK.
- **Authentication:** `MCPAuthASGIMiddleware` is a **pure ASGI** wrapper (not `BaseHTTPMiddleware`) that, for `/mcp` requests, decodes an optional bearer token, loads the user and calls `mcp_tools.bind_user(user)`. Tool calls then pass through `PERMISSION_MAP`. Anonymous read-only use remains possible.
- **Third-party skills:** `mcp_skills` table + `/mcp/skills` CRUD and `/mcp/skills/{id}/sync`, kept in a separate namespace from platform tools. A later revision added an installable catalog, `install`/`enable`/`disable`/`uninstall`/`reinstall`, editable skill files (`mcp_skill_files` + disk mirror) and a full call journal (`mcp_call_logs`); see [ADR-0007](0007-mcp-skill-lifecycle-and-journal.md).
- **Call journal:** the ASGI middleware buffers the JSON-RPC body once (replaying it to the transport) to log non-tool methods, while `mcp_tools.call_tool()` logs every tool invocation with arguments, result preview, status and duration. Sources are `mcp`, `rest`, `agent` and `internal`; writes are best-effort so journaling can never break a tool call.

## Consequences

### Positive
- Real MCP SDK compliance (JSON Schema from signatures, resources, prompts) with a resilient fallback.
- One process serves REST, MCP, docs and SPA; no extra port.
- External MCP clients work while platform authorization is preserved.
- Pure-ASGI middleware avoids `BaseHTTPMiddleware` streaming pitfalls.

### Negative
- Lifespan coupling: fastmcp initialization must stay inside FastAPI's lifespan; upgrading the SDK requires re-verifying this integration.
- Anonymous MCP read access is permissive by default.
- The builtin fallback advertises a fixed `PROTOCOL_VERSION` (`2025-06-18`) while fastmcp negotiates with the client.
- Third-party skill sync is metadata-level (tool catalog), not a full proxy to external MCP servers.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Stdio-only MCP server | Cannot be reached by browser/HTTP clients or the single-port design |
| Separate MCP port/process | More deployment complexity; breaks the single-port goal |
| `BaseHTTPMiddleware` for auth | Known streaming/context issues with SSE-style transports |
| Require a token for all MCP calls | Would block trivial external clients; made optional instead |

## Verification

Live checks: `POST /mcp` `initialize` → 200 with capabilities + `serverInfo`, `tools/list` → 12 tools, `tools/call` → RBAC-checked result; `/docs` and `/openapi.json` still work; SPA catch-all protects `/mcp`. Smoke suite asserts all three MCP methods plus REST invoke and skill sync.
