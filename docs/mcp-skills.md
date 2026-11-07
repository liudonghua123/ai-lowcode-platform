# MCP Skills & Call Journal

| Field | Value |
| --- | --- |
| ID | `MCP-001` |
| Version | 0.2.0 |
| Status | Current |
| Related | [System Architecture](architecture.md) · [AI System Design](ai-design.md) · [Data Model](data-model.md) · [API & MCP Reference](api-reference.md) · [ADR-0007](adr/0007-mcp-skill-lifecycle-and-journal.md) |

> 中文摘要：MCP 子系统包含三层能力 —— **12 个平台工具**（统一注册表，见 AI-001）、**第三方技能生命周期**（目录安装、启用/禁用/卸载/重装、可视化管理、可编辑技能文件与磁盘镜像）、以及**全量调用日记**（记录 MCP / REST / Agent / internal 四类来源的每次调用，含参数、结果预览、耗时与错误，支持筛选、统计图表与 CSV 导出）。所有写操作受 `mcp:read` / `mcp:write` / `mcp:invoke` 权限约束，并写入审计日志。

## 1. Overview

```
                    ┌──────────────────────────────────────────┐
  MCP client ──────▶│ /mcp  (fastmcp streamable HTTP)          │
  REST console ────▶│ /api/v1/mcp/invoke                       │──┐
  AI agent ────────▶│ llm.run_agent (ReAct tool loop)          │  │
                    └──────────────────────────────────────────┘  │
                                      │                            │
                                      ▼                            ▼
                        services/mcp_tools.py  ─────────▶ mcp_call_logs
                        (12 tool specs, RBAC)              (journal)
                                      │
                                      ▼
                        services/skill_catalog.py ──▶ mcp_skills
                        services/skill_files.py   ──▶ mcp_skill_files
                                                   └─▶ data/skills/<code>/
```

`MCPAuthASGIMiddleware` (pure ASGI) binds an optional bearer token, tags the context with `source` / `actor` / `request_id` / `method`, and buffers the JSON-RPC body once so the method name can be journaled without touching streaming responses.

## 2. Data model

| Table | Purpose | Key columns |
| --- | --- | --- |
| `mcp_skills` | Registry + lifecycle state | `code` (unique), `type`, `endpoint`, `command`, `enabled`, `status`, `version`, `source`, `description`, `manifest` JSON, `tools` JSON, `health`, `installed_at` |
| `mcp_skill_files` | Editable skill files (authoritative) | `skill_id`, `path` (unique per skill), `content`, `language`, `size`, `updated_at` |
| `mcp_call_logs` | Invocation journal | `method`, `tool`, `source`, `transport`, `actor`, `arguments` JSON, `status`, `error`, `result_preview`, `duration_ms`, `request_id`, `created_at` |

Indexes: `idx_mcp_calls_created`, `idx_mcp_calls_tool`, `idx_skill_files_skill` (plus the four original ones — seven total). New columns on existing databases are added by `db._migrate()` at startup via `PRAGMA table_info` + `ALTER TABLE`.

## 3. Lifecycle state machine

| State | `enabled` | Files | Meaning |
| --- | --- | --- | --- |
| `installed` | 1 | present | Available; may be synced and invoked |
| `disabled` | 0 | present | Temporarily off; configuration retained |
| `uninstalled` | 0 | removed | Installation removed; registry row kept for reinstall |
| `error` | 0 | any | Reserved for failed installs/probes |

Transitions:

- `POST /mcp/skills/install` → `installed` (creates the row if absent, or re-installs an `uninstalled` one) and materializes the default file set.
- `POST /mcp/skills/{id}/disable` → `disabled`; `enable` → `installed` (ensures files exist).
- `POST /mcp/skills/{id}/uninstall` → `uninstalled`, deletes DB files and the disk directory, clears `tools` / `health`.
- `POST /mcp/skills/{id}/reinstall` → `installed`, regenerates the default files.
- `DELETE /mcp/skills/{id}` → permanent removal of registry row + files.

`POST /mcp/skills` (manual registration) also installs files; `PUT /mcp/skills/{id}` may patch metadata or `status`.

## 4. Installable catalog

`GET /mcp/skills/catalog` returns five built-in templates, each with `installed` / `status` flags:

| Code | Type | Version | Capabilities |
| --- | --- | --- | --- |
| `web-search` | http | 1.2.0 | search, fetch, citation |
| `filesystem` | stdio | 1.0.0 | read, list, stat |
| `sqlite-query` | stdio | 0.9.1 | query, schema |
| `weather` | http | 2.0.0 | forecast, current |
| `github-issues` | http | 1.1.0 | search, read |

Each install creates five editable files: `SKILL.md`, `manifest.json`, `config.json`, `tools.json`, `README.md`. Custom skills registered manually receive a generic file set derived from their metadata.

## 5. Editable skill files

| Operation | Endpoint | Permission |
| --- | --- | --- |
| List files + disk path | `GET /mcp/skills/{id}/files` | `mcp:read` |
| Read one file | `GET /mcp/skills/{id}/files/{path}` | `mcp:read` |
| Create / update | `PUT /mcp/skills/{id}/files/{path}` | `mcp:write` |
| Delete | `DELETE /mcp/skills/{id}/files/{path}` | `mcp:write` |
| Re-read disk mirror | `POST /mcp/skills/{id}/files/reload` | `mcp:write` |

Path rules (`services/skill_files.validate_path`): relative paths only, `[A-Za-z0-9._/-]`, no `..` segments, no double slashes, resolved target must stay inside `data/skills/<code>/`. Content is capped at 200,000 characters. Language is inferred from the extension (`md` → markdown, `json` → json, …).

The UI provides a two-pane file manager: a file tree on the left, an editor on the right, plus new-file, save, delete and reload-from-disk actions. The disk mirror is best-effort — SQLite remains authoritative.

## 6. Call journal

### 6.1 What is recorded

| Source | Origin | Example `method` |
| --- | --- | --- |
| `mcp` | `/mcp` JSON-RPC (authenticated or anonymous) | `initialize`, `tools/list`, `tools/call`, `resources/read`, `prompts/get` |
| `rest` | `POST /api/v1/mcp/invoke` | `invoke` |
| `agent` | ReAct tool loop in `llm.run_agent` | `agent.tool` |
| `internal` | In-process aggregation (rare; dashboard stats pass `journal=False`) | `tools/call` |

`tools/call` and `resources/read` are written by `mcp_tools.call_tool()` with **arguments, result preview, status, error and duration**; all other JSON-RPC methods are written by the ASGI middleware at transport level. A `finally` block guarantees failed calls (validation errors, permission denials, handler exceptions) are logged with `status=error`. Journal writes are best-effort and never break the tool call.

### 6.2 Query & visualization

| Endpoint | Purpose |
| --- | --- |
| `GET /mcp/calls` | Filters: `tool`, `source`, `status`, `actor`, `method`, `q`, `limit`, `offset` |
| `GET /mcp/calls/stats` | Totals, success rate, avg latency, today, `by_tool`, `by_source`, 7-day `timeline`, filter vocabularies |
| `GET /mcp/calls/export` | CSV export (`text/csv`, attachment) |
| `GET /mcp/calls/{id}` | Full entry with parsed `arguments` / `result` |
| `DELETE /mcp/calls` | Clear the journal (`mcp:write`, audited) |

The frontend journal tab shows four KPI cards, a per-tool horizontal bar chart, a 7-day timeline, source badges, a filterable table and a detail dialog with JSON arguments/result/error.

### 6.3 Operational notes

- No automatic retention: use `DELETE /mcp/calls` or schedule cleanup. `result_preview` is truncated to 2000 characters.
- On a fresh (empty) journal, `mcp_journal.ensure_demo()` seeds six illustrative entries so the UI is not blank; they are real rows and can be cleared.
- `GET /mcp/status` exposes `journal.total` and `skill_statuses` aggregate counts.

## 7. RBAC & audit

| Permission | Grants |
| --- | --- |
| `mcp:read` | Tool catalog, status, skill list/detail/catalog, file listing/reading, journal queries/export |
| `mcp:write` | Skill registration/install/lifecycle, file create/update/delete/reload, skill deletion, journal clearing, sync |
| `mcp:invoke` | REST tool invocation |

Tool-level authorization still uses `PERMISSION_MAP` inside `call_tool` (see ADR-0002). All lifecycle, file and journal-clear actions are written to `audit_logs` via `deps.audit()` with actions such as `mcp.skill.install`, `mcp.skill.files.write`, `mcp.journal.clear`.

## 8. Validation

`backend/tests/smoke.py` — 69 assertions, including journal recording/statistics/export/clear, catalog, install with file creation, file CRUD, path-traversal rejection, enable/disable/uninstall/reinstall and permanent delete. `POST /mcp` `initialize` / `tools/list` / `tools/call` remain 200 after the ASGI body-buffering change. `pnpm typecheck`, `pnpm build`, `pnpm check:i18n` (558 en/zh keys) and `ruff check app` all pass.

## 9. Production considerations

- Rotate or truncate `mcp_call_logs`; add a retention job for high-traffic deployments.
- Require `Authorization: Bearer` on `/mcp` for untrusted clients so journal entries carry real actors.
- Treat `data/skills/` as runtime state (gitignored); back up `mcp_skill_files` (the authoritative copy).
- Replace the demo catalog with a signed/verified registry before allowing arbitrary third-party skills.
- Keep `SECRET_KEY` strong and serve over HTTPS; WebAuthn/passkey and MCP bearer tokens both depend on transport security.
