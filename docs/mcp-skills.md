# MCP Servers, Skills & Call Journal

| Field | Value |
| --- | --- |
| ID | `MCP-001` |
| Version | 0.3.0 |
| Status | Current |
| Related | [System Architecture](architecture.md) · [AI System Design](ai-design.md) · [Data Model](data-model.md) · [API & MCP Reference](api-reference.md) · [Knowledge Upload](knowledge-upload.md) · [AI Model Services](ai-models.md) · [ADR-0007](adr/0007-mcp-skill-lifecycle-and-journal.md) · [ADR-0008](adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md) |

> 中文摘要：MCP 子系统现在由**四层**组成 —— **12 个平台工具**（统一注册表，见 AI-001）、**独立的 MCP 服务注册表**（`mcp_servers` / `/mcp/servers`，负责连接、探测同步与外部工具桥接）、**独立的技能注册表**（`mcp_skills` / `/skills`，负责目录安装、启用/禁用/卸载/重装、可视化管理与可编辑技能文件，并通过可空的 `server_id` 关联服务）、以及**全量调用日记**（`mcp_call_logs`，记录 MCP / REST / Agent / internal 四类来源，含参数、结果预览、耗时、错误与 `target`）。`mcp_tools.agent_tools()` 按智能体绑定收窄工具域。写操作受 `mcp:read` / `mcp:write` / `mcp:invoke` 约束并写入审计日志。删除服务或技能都不会连带删除另一方。

## 1. Overview

```
  MCP client ──────▶ /mcp  (fastmcp streamable HTTP)  ─┐
  REST console ────▶ /api/v1/mcp/invoke               ─┤
  AI agent ────────▶ llm.run_agent (ReAct, bound scope)─┤
                                                        ▼
                     services/mcp_tools.py ────────▶ mcp_call_logs
                     (12 tool specs + external)        (journal, target)
                          │        ▲
                          │        │ declared_tools() / call_remote_tool
                          ▼        │
            services/mcp_servers.py ──▶ mcp_servers      (independent)
            services/skill_*.py     ──▶ mcp_skills       (independent)
                                       mcp_skill_files ─▶ data/skills/<code>/
```

`MCPAuthASGIMiddleware` (pure ASGI) binds an optional bearer token, tags the context with `source` / `actor` / `request_id` / `method`, and buffers the JSON-RPC body once so the method name can be journaled without touching streaming responses.

## 2. Independent registries (ADR-0008)

MCP servers and Skills used to share `mcp_skills`; they are now separate entities with separate tables, routers and lifecycles.

| Registry | Table | Router | Responsibility |
| --- | --- | --- | --- |
| MCP servers | `mcp_servers` | `/mcp/servers` | Connection config (`transport`, `endpoint` / `command`, `auth_config`), `probe()` + `sync()` tool discovery, health/status, `invoke_on_server()` |
| Skills | `mcp_skills` | `/skills` | Lifecycle (`installed`/`disabled`/`uninstalled`/`error`), catalog, manifest, editable files, optional `server_id` link |

Isolation rules:

- `mcp_skills.server_id` is **nullable and non-owning**. `DELETE /mcp/servers/{id}` leaves skills untouched; `DELETE /skills/{id}` leaves servers untouched.
- `POST /skills/{id}/sync` refreshes a skill's tools from its linked server; a skill without `server_id` keeps its declared tools.
- `routers/mcp.py` no longer hosts skill lifecycle endpoints — it keeps only the shared transport surface (`/mcp/tools`, `/mcp/status`, `/mcp/calls*`, `/mcp/invoke`).

Runtime tool flow:

1. `mcp_servers.declared_tools(server_ids)` → `external_specs()` produces OpenAI/Anthropic-style specs for tools declared by **enabled** servers.
2. `mcp_tools.list_tools(include_external=True, server_ids=…)` merges platform `TOOL_SPECS` with those external specs; the `call_remote_tool` MCP bridge forwards a call to the owning server via `invoke_external()`.
3. `mcp_tools.agent_tools(agent, fmt)` filters that catalog to the agent's `server_ids` / `skill_ids` bindings, so unbound servers are invisible and uncallable during a ReAct loop.
4. External calls are gated by `mcp:invoke` and journaled with `target=server:<code>`.

Seed startup: `seed.ensure_registries()` idempotently provisions `platform-builtin`, `thirdparty-http` and `thirdparty-stdio` servers, the five catalog skills (linked by type) and the five AI model defaults. See [AI Model Services](ai-models.md).

## 3. Data model

| Table | Purpose | Key columns |
| --- | --- | --- |
| `mcp_servers` | Independent connection registry | `code` (unique), `name`, `transport`, `endpoint`, `command`, `auth_config` JSON, `tools` JSON, `enabled`, `health`, `last_sync_at`, `status`, `source`, `created_by` |
| `mcp_skills` | Independent Skill registry + lifecycle | `code` (unique), `name`, `type`, `enabled`, `status`, `version`, `source`, `description`, `manifest` JSON, `tools` JSON, `health`, `installed_at`, **`server_id` (nullable link)** |
| `mcp_skill_files` | Editable skill files (authoritative) | `skill_id`, `path` (unique per skill), `content`, `language`, `size`, `updated_at` |
| `mcp_call_logs` | Invocation journal | `method`, `tool`, `source`, `transport`, `actor`, `arguments` JSON, `status`, `error`, `result_preview`, `duration_ms`, `request_id`, **`target`**, `created_at` |

10 indexes total: `idx_submissions_form`, `idx_instances_wf`, `idx_kbdocs_collection`, `idx_audit_created`, `idx_mcp_calls_created`, `idx_mcp_calls_tool`, `idx_skill_files_skill`, `idx_ai_providers_category`, `idx_mcp_servers_enabled`, `idx_kbdocs_file_type`. `db.init_db()` runs `SCHEMA` → `_migrate()` → `INDEX_SCHEMA`, so indexes on newly migrated columns (`file_type`, `enabled`, `target`) are created only after the columns exist. New columns on existing databases are added by `PRAGMA table_info` + `ALTER TABLE`.

## 4. MCP server registry

`services/mcp_servers.py` and `routers/mcp_servers.py`:

| Operation | Endpoint / function | Notes |
| --- | --- | --- |
| List / summary | `GET /mcp/servers`, `GET /mcp/servers/summary` | `stats()` returns enabled/healthy totals |
| Register / update / delete | `POST`, `PUT /mcp/servers/{id}`, `DELETE /mcp/servers/{id}` | `code` unique; `auth_config` JSON |
| Probe | `probe(server)` | `initialize` + `tools/list` over HTTP/SSE, `parse_rpc()` tolerant of SSE framing, returns `(health, tools, message)` |
| Sync | `POST /mcp/servers/{id}/sync` | Refreshes `tools`, `health`, `last_sync_at` |
| Tools | `GET /mcp/servers/{id}/tools` | Declared tool list |
| Enable / disable | `POST /mcp/servers/{id}/enable`, `/disable` | Disabled servers drop out of `list_tools(include_external=True)` |
| Invoke | `POST /mcp/servers/{id}/invoke` | Rejects tools not declared by that server; binds `target=server:<code>` |
| Bridge | `mcp_server.py::call_remote_tool(name, arguments)` | MCP-facing entry for external tools |

Permissions: reads `mcp:read`; register/sync/enable/delete `mcp:write`; invocation `mcp:invoke`. All mutations are audited.

## 5. Skill lifecycle state machine

| State | `enabled` | Files | Meaning |
| --- | --- | --- | --- |
| `installed` | 1 | present | Available; may be synced and invoked |
| `disabled` | 0 | present | Temporarily off; configuration retained |
| `uninstalled` | 0 | removed | Installation removed; registry row kept for reinstall |
| `error` | 0 | any | Reserved for failed installs/probes |

Transitions:

- `POST /skills/install` → `installed` (creates the row if absent, or re-installs an `uninstalled` one) and materializes the default file set.
- `POST /skills/{id}/disable` → `disabled`; `enable` → `installed` (ensures files exist).
- `POST /skills/{id}/uninstall` → `uninstalled`, deletes DB files and the disk directory, clears `tools` / `health`.
- `POST /skills/{id}/reinstall` → `installed`, regenerates the default files.
- `POST /skills/{id}/sync` → refreshes tools from the linked MCP server (no-op without `server_id`).
- `DELETE /skills/{id}` → permanent removal of registry row + files (servers survive).

`POST /skills` (manual registration) also installs files; `PUT /skills/{id}` may patch metadata, `status` or `server_id`.

## 6. Installable catalog

`GET /skills/catalog` returns five built-in templates, each with `installed` / `status` flags:

| Code | Type | Version | Capabilities |
| --- | --- | --- | --- |
| `web-search` | http | 1.2.0 | search, fetch, citation |
| `filesystem` | stdio | 1.0.0 | read, list, stat |
| `sqlite-query` | stdio | 0.9.1 | query, schema |
| `weather` | http | 2.0.0 | forecast, current |
| `github-issues` | http | 1.1.0 | search, read |

Each install creates five editable files: `SKILL.md`, `manifest.json`, `config.json`, `tools.json`, `README.md`. Custom skills registered manually receive a generic file set derived from their metadata. Catalog skills are linked by `seed.ensure_registries()` to `thirdparty-http` or `thirdparty-stdio` servers.

## 7. Editable skill files

| Operation | Endpoint | Permission |
| --- | --- | --- |
| List files + disk path | `GET /skills/{id}/files` | `mcp:read` |
| Read one file | `GET /skills/{id}/files/{path}` | `mcp:read` |
| Create / update | `PUT /skills/{id}/files/{path}` | `mcp:write` |
| Delete | `DELETE /skills/{id}/files/{path}` | `mcp:write` |
| Re-read disk mirror | `POST /skills/{id}/files/reload` | `mcp:write` |

Path rules (`services/skill_files.validate_path`): relative paths only, `[A-Za-z0-9._/-]`, no `..` segments, no double slashes, resolved target must stay inside `data/skills/<code>/`. Content is capped at 200,000 characters. Language is inferred from the extension (`md` → markdown, `json` → json, …).

The UI (`pages/Skills.tsx`) provides a two-pane file manager: a file tree on the left, an editor on the right, plus new-file, save, delete and reload-from-disk actions. The disk mirror is best-effort — SQLite remains authoritative.

## 8. Call journal

### 8.1 What is recorded

| Source | Origin | Example `method` |
| --- | --- | --- |
| `mcp` | `/mcp` JSON-RPC (authenticated or anonymous) | `initialize`, `tools/list`, `tools/call`, `resources/read`, `prompts/get` |
| `rest` | `POST /api/v1/mcp/invoke` | `invoke` |
| `agent` | ReAct tool loop in `llm.run_agent` | `agent.tool` |
| `internal` | In-process aggregation (rare; dashboard stats pass `journal=False`) | `tools/call` |

`tools/call` and `resources/read` are written by `mcp_tools.call_tool()` with **arguments, result preview, status, error, duration and `target`**; all other JSON-RPC methods are written by the ASGI middleware at transport level. External server calls carry `target=server:<code>`; the CSV export includes a `target` column. A `finally` block guarantees failed calls (validation errors, permission denials, handler exceptions) are logged with `status=error`. Journal writes are best-effort and never break the tool call.

### 8.2 Query & visualization

| Endpoint | Purpose |
| --- | --- |
| `GET /mcp/calls` | Filters: `tool`, `source`, `status`, `actor`, `method`, `q`, `limit`, `offset` |
| `GET /mcp/calls/stats` | Totals, success rate, avg latency, today, `by_tool`, `by_source`, 7-day `timeline`, filter vocabularies |
| `GET /mcp/calls/export` | CSV export (`text/csv`, attachment) |
| `GET /mcp/calls/{id}` | Full entry with parsed `arguments` / `result` |
| `DELETE /mcp/calls` | Clear the journal (`mcp:write`, audited) |

The frontend journal tab (`pages/McpServers.tsx`) shows four KPI cards, a per-tool horizontal bar chart, a 7-day timeline, source badges, a filterable table and a detail dialog with JSON arguments/result/error.

### 8.3 Operational notes

- No automatic retention: use `DELETE /mcp/calls` or schedule cleanup. `result_preview` is truncated to 2000 characters.
- On a fresh (empty) journal, `mcp_journal.ensure_demo()` seeds six illustrative entries so the UI is not blank; they are real rows and can be cleared.
- `GET /mcp/status` exposes journal and registry aggregate counts.

## 9. RBAC & audit

| Permission | Grants |
| --- | --- |
| `mcp:read` | Tool catalog, status, server/skill list/detail/catalog, file listing/reading, journal queries/export |
| `mcp:write` | Server registration/sync/enable/delete, skill registration/install/lifecycle, file create/update/delete/reload, skill deletion, journal clearing |
| `mcp:invoke` | REST tool invocation and external MCP tool calls |

Tool-level authorization still uses `PERMISSION_MAP` inside `call_tool` (see ADR-0002). All lifecycle, file and journal-clear actions are written to `audit_logs` via `deps.audit()` with actions such as `mcp.skill.install`, `mcp.skill.files.write`, `mcp.journal.clear`. Related registries have their own gates: `/ai/providers` reads use `mcp:read` and writes `settings:write` ([AIM-001](ai-models.md)); `/knowledge/upload` uses `knowledge:write` ([KNB-001](knowledge-upload.md)).

## 10. Validation

`backend/tests/smoke.py` — **110 assertions**, including journal recording/statistics/export/clear, catalog, install with file creation, file CRUD, path-traversal rejection, enable/disable/uninstall/reinstall and permanent delete; MCP server independent registration, sync, tools, invoke rejection, enable and delete; skill deletion leaving servers intact; agent bindings with stale-id cleanup; AI provider categories/defaults/key masking; multi-format upload and unsupported-format rejection. `POST /mcp` `initialize` / `tools/list` / `tools/call` remain 200 after the ASGI body-buffering change. `pnpm typecheck`, `pnpm build`, `pnpm check:i18n` (635 en/zh keys), `pnpm build` and `ruff check app tests` all pass.

## 11. Production considerations

- Rotate or truncate `mcp_call_logs`; add a retention job for high-traffic deployments.
- Require `Authorization: Bearer` on `/mcp` for untrusted clients so journal entries carry real actors.
- Treat `data/skills/` as runtime state (gitignored); back up `mcp_skill_files` (the authoritative copy).
- Replace the demo catalog with a signed/verified registry before allowing arbitrary third-party skills; treat registered MCP servers as trusted endpoints and review `call_remote_tool` exposure.
- Remove the legacy `endpoint` / `command` / `type` columns from `mcp_skills` in a future major release (they are retained only for backward compatibility).
- Keep `SECRET_KEY` strong and serve over HTTPS; WebAuthn/passkey, MCP bearer tokens and provider API keys all depend on transport security.
