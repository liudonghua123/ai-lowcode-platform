# ADR-0007: Skill lifecycle, editable skill files and MCP call journal

| Field | Value |
| --- | --- |
| Status | **Accepted** |
| Date | 2026-11-07 |
| Theme | MCP / observability |
| Related | [ADR-0002](0002-single-tool-registry.md), [ADR-0005](0005-mcp-transport-and-auth.md), [DAT-001](../data-model.md), [MCP-001](../mcp-skills.md) |

## Context

The first release registered third-party MCP servers as plain metadata rows (`mcp_skills`) with CRUD plus a `sync` probe. Three gaps remained:

1. **No lifecycle.** A skill was either present or deleted; there was no notion of *installing* from a catalog, *disabling* without losing configuration, or *uninstalling* while keeping the registry entry for reinstall.
2. **No skill files.** "Third-party MCP skills" implied manifest/config/tool-definition files, but nothing could be viewed or edited. Users asked to install, disable, uninstall, visualize, view and update skill-related files.
3. **No invocation history.** MCP `tools/call`, REST `/mcp/invoke` and agent tool steps executed with no durable record — debugging, auditing and usage charts were impossible.

Constraints: single-process SQLite deployment, no new services, no migration framework, and the MCP transport (fastmcp streamable HTTP) must not be broken by instrumentation.

## Decision

1. **Lifecycle state machine.** Add `status` (`installed` / `disabled` / `uninstalled` / `error`), `version`, `source`, `description`, `manifest`, `installed_at`, `updated_at` to `mcp_skills`. `enabled` is retained for compatibility and kept in sync with `status`. Endpoints: `POST /skills/install`, `/{id}/enable`, `/{id}/disable`, `/{id}/uninstall`, `/{id}/reinstall`. Uninstall removes files but keeps the row; `DELETE /skills/{id}` is the only permanent removal.
2. **Installable catalog.** `services/skill_catalog.py` declares five templates (`web-search`, `filesystem`, `sqlite-query`, `weather`, `github-issues`). `GET /skills/catalog` exposes them with install state; installing materializes a default file set.
3. **Editable file store.** New table `mcp_skill_files` (`skill_id`, `path`, `content`, `language`, `size`, `updated_at`, unique per skill+path) is authoritative. `services/skill_files.py` mirrors every write to `data/skills/<code>/`, validates paths against traversal, and offers `reload` from disk. A lazy startup bootstrap ensures existing installed skills have files.
4. **Call journal.** New table `mcp_call_logs` records `method`, `tool`, `source`, `transport`, `actor`, `arguments`, `status`, `error`, `result_preview`, `duration_ms`, `request_id`, `created_at`. `mcp_tools.call_tool()` writes one entry in a `finally` block (best-effort, never breaks a call); the ASGI middleware buffers the JSON-RPC body once and logs non-tool methods with a replaying `receive`. Sources: `mcp`, `rest`, `agent`, `internal`. Internal dashboard aggregation passes `journal=False`.
5. **Idempotent migrations.** `db.init_db()` runs `_migrate()` using `PRAGMA table_info` + `ALTER TABLE` so existing databases gain the new columns without a rebuild.

## Consequences

**Positive**

- Full lifecycle is visible and reversible; a disabled skill keeps its files and configuration.
- Skill files are real, viewable and editable from the UI, with a host-side disk mirror for inspection.
- Every invocation — including failures and permission denials — is queryable, chartable and exportable as CSV.
- All three consumers (MCP / REST / agent) share one journal, consistent with ADR-0002.
- No new infrastructure; two SQLite tables, three indexes and one service module set.

**Negative / trade-offs**

- The journal is unbounded by default; retention/rotation is an operational concern (`DELETE /mcp/calls` clears it).
- `result_preview` is truncated to 2000 characters; large payloads are not fully retained.
- fastmcp's `initialize` / `tools/list` are logged at the transport level via body buffering; the buffer is bounded by the request size and streaming responses are never buffered.
- The disk mirror is best-effort; a write failure does not fail the API call, and the SQLite table remains authoritative.
- Anonymous MCP calls are recorded with `actor: anonymous`.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Store skill files only on disk | Harder to query/version, weaker access control, complicates single-port deployment |
| Store files only in the database | Loses the "skill-related files" artifact users can inspect on the host |
| Instrument fastmcp via tool decorators only | Misses `initialize`, `tools/list` and non-tool JSON-RPC methods |
| Wrap responses to capture results | Would buffer SSE / streaming responses and risk breaking MCP clients |
| Emit structured logs to stdout instead of a table | No in-product visualization, filtering or export without an external log stack |

## Validation

`backend/tests/smoke.py` (157 assertions) verifies: journal records MCP and REST sources, failed invocations are recorded as `error`, stats/aggregates/timeline, CSV export, detail lookup and clearing; catalog listing; install creates ≥4 files; file read/create/update; path traversal rejection; enable/disable; uninstall removes all files; reinstall restores defaults; and permanent delete. Live MCP `initialize` / `tools/list` / `tools/call` remain 200 after the middleware change.
