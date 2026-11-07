# ADR-0002: One registry for MCP tools, AI agents and REST invocation

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform Team |
| Related | `AI-001` §2, §6, §10 · `ARC-001` §3 · `ADR-0003`, `ADR-0005` |

## Context

The platform exposes the same capabilities through three channels: an MCP server (`tools/list`, `tools/call`), AI agents (ReAct tool calls) and a REST console (`POST /api/v1/mcp/invoke`). Requirements demand that an AI agent can **actually** submit a form or run a workflow, and that every action stays RBAC-checked. Duplicating tool definitions per channel would cause schema drift and, worse, inconsistent authorization.

## Decision

Introduce `backend/app/services/mcp_tools.py` as the **single source of truth**:

- `TOOL_SPECS` — 12 tools, each with `name`, `description` and a strict JSON Schema `inputSchema` (`additionalProperties: false`, explicit `required`).
- `PERMISSION_MAP` — tool → RBAC permission (e.g. `submit_form → form:submit`, `run_workflow → workflow:run`).
- `HANDLERS` — tool → pure Python function over `db`, `rag`, `workflow_engine`.
- `call_tool(name, args, user)` — validates the name, resolves the effective user (explicit argument or `ContextVar`), enforces `PERMISSION_MAP` via `deps.has_permission`, then dispatches.
- `list_tools(fmt)` — emits MCP shape or OpenAI function-calling shape from the same specs.
- `as_mcp_content()` — wraps results into MCP content/structuredContent.

All three consumers call `call_tool()`; the fastmcp layer only adapts typed Python signatures to schemas.

## Consequences

### Positive
- No capability drift: adding a tool automatically appears in MCP, agent tool lists and the REST catalog.
- One authorization gate; tool calls cannot bypass route-level RBAC.
- Identity is isolated per request via `contextvars.ContextVar` (`bind_user` / `current_user` with `try/finally` reset).
- The LLM sees exactly the same contracts as external MCP clients.

### Negative
- The registry is a central coupling point; a bad handler affects all three channels.
- `submit_form` / `run_workflow` are write-capable tools reachable by any caller holding the corresponding permission — human approval is not implemented (see production path in `AI-001` §14).
- Anonymous MCP calls are permitted for read-only tools; deployments must require a token if that is unacceptable.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Define tools separately in fastmcp decorators and in the agent prompt | Guaranteed schema/permission drift; hard to audit |
| Let agents call REST endpoints with a service account | Loses per-user attribution; duplicates auth logic |
| Generate tools dynamically from OpenAPI | Couples AI contracts to HTTP details and leaks internal endpoints |

## Verification

`backend/tests/smoke.py` asserts MCP `tools/list` returns the 12 tools, `tools/call` and `/mcp/invoke` produce identical results, act/hybrid agents execute ≥2 real tool calls, and RBAC denial is enforced at the tool layer. Result: **157 passed / 0 failed**.
