# Data Model

| Field | Value |
| --- | --- |
| Document ID | `DAT-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Source of truth | `backend/app/db.py::SCHEMA` |
| Related | [System Architecture](architecture.md) · [Security Architecture](security.md) · [API & MCP Reference](api-reference.md) · [ADR-0004](adr/0004-sqlite-and-local-bm25.md) |

> 中文摘要：平台使用单文件 SQLite（WAL 模式），共 **21 张表、10 个索引**，复杂结构统一以 JSON 文本列存储并由 `insert/update/loads` 透明序列化；连接采用线程局部对象 + 可重入写锁，`init_db()` 内置幂等的 `ALTER TABLE` 惰性迁移。首次启动自动灌入确定性演示数据。详见 [系统架构设计](architecture.zh-CN.md)。

## 1. Storage strategy

| Property | Implementation |
| --- | --- |
| Engine | `sqlite3` (Python standard library), single file `backend/data/platform.db` |
| Journal | `PRAGMA journal_mode=WAL` |
| Constraints | `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`, connect timeout 30 s |
| Row factory | `sqlite3.Row` (dict-like access) |
| Connections | `threading.local()` — one connection per thread |
| Concurrency | `threading.RLock()` guards all writes |
| JSON columns | TEXT columns serialized by `_enc`/`_dec`; read via `db.loads(row, *cols)` |
| Timestamps | UTC ISO-8601 seconds via `db.now()` |
| IDs | `INTEGER PRIMARY KEY AUTOINCREMENT`; `db.uid()` for opaque tokens |

`config.Settings.resolved_db_path` creates the parent directory on first use, so a fresh clone with only `backend/data/.gitkeep` starts cleanly.

## 2. Entity relationship overview

```mermaid
erDiagram
    users ||--o{ roles : "role_ids (JSON)"
    roles ||--o{ permissions : "permission_ids (JSON)"
    users ||--o{ conversations : "user_id"
    forms ||--o{ form_submissions : "form_id"
    workflows ||--o{ workflow_instances : "workflow_id"
    kb_collections ||--o{ kb_documents : "collection_id"
    agents ||--o{ conversations : "agent_id"
    agents ||--o{ kb_collections : "kb_ids (JSON)"
    agents ||--o{ mcp_skills : "skill_ids (JSON)"
    agents ||--o{ mcp_servers : "server_ids (JSON)"
    agents ||--o{ workflows : "workflow_ids (JSON)"
    mcp_servers ||--o{ mcp_skills : "server_id (nullable)"
    auth_providers ||--o{ sso_states : "provider"
    users ||--o{ mfa_challenges : "user_id"
```

> JSON-array columns represent logical relationships; SQLite foreign keys are declared where a scalar FK column exists (`form_id`, `workflow_id`, `collection_id`).

## 3. Tables (21)

### 3.1 Identity & access (6)

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `id`, `username` (unique), `email`, `display_name`, `avatar`, `password_hash`, `status`, `dept`, `role_ids` **JSON**, `otp_secret`, `otp_enabled`, `passkey_enabled`, `passkeys` **JSON**, `external_id`, `provider`, `last_login_at`, `created_at`, `updated_at` | Password stored as `pbkdf2_sha256$180000$…`; MFA credentials kept here |
| `roles` | `id`, `code` (unique), `name`, `description`, `permission_ids` **JSON**, `builtin`, `mfa_required`, `created_at` | Built-ins: admin / developer / operator / viewer |
| `permissions` | `id`, `code` (unique), `name`, `resource`, `action`, `description` | 25 rows |
| `auth_providers` | `id`, `code` (unique), `type`, `name`, `enabled`, `config` **JSON**, `sort_order`, timestamps | CAS / OAuth2 / OIDC / WeCom / DingTalk |
| `sso_states` | `state` (PK), `provider`, `redirect_uri`, `nonce`, `created_at` | CSRF/nonce state for SSO handshakes |
| `mfa_challenges` | `id`, `user_id`, `kind`, `challenge`, `payload` **JSON**, `expires_at`, `consumed`, `created_at` | One-time WebAuthn/MFA challenges |

### 3.2 Forms (2)

| Table | Key columns | Notes |
| --- | --- | --- |
| `forms` | `id`, `code` (unique), `name`, `description`, `status` (`draft`/`published`/`archived`), `schema` **JSON**, `layout` **JSON**, `version`, `created_by`, timestamps | Designer field definitions live in `schema` |
| `form_submissions` | `id`, `form_id`, `data` **JSON**, `status`, `submitted_by`, `created_at` | Indexed by `form_id` |

### 3.3 Workflows (2)

| Table | Key columns | Notes |
| --- | --- | --- |
| `workflows` | `id`, `code` (unique), `name`, `description`, `status`, `graph` **JSON** (`{nodes, edges}`), `version`, `created_by`, timestamps | DAG definition |
| `workflow_instances` | `id`, `workflow_id`, `status`, `context` **JSON**, `logs` **JSON**, `started_by`, `started_at`, `finished_at` | Indexed by `workflow_id` |

### 3.4 Knowledge base (2)

| Table | Key columns | Notes |
| --- | --- | --- |
| `kb_collections` | `id`, `code` (unique), `name`, `description`, `embedding_model` (default `bm25-local`), `chunk_size` (default 480), `created_by`, `created_at` | Retrieval scope for agents |
| `kb_documents` | `id`, `collection_id`, `title`, `content`, `source`, `status` (`indexed`/`empty`), `chunks` **JSON**, `file_name`, `file_type`, `file_size`, `parse_status` (`manual`/`parsed`/`ocr`/`empty`/`error`), `parse_error`, `created_at` | Uploaded Office/PDF/Markdown files are parsed by `services/documents.py`; `rag.index_document()` fills `chunks`; indexed by `collection_id` + `file_type` |

### 3.5 AI (2)

| Table | Key columns | Notes |
| --- | --- | --- |
| `agents` | `id`, `code` (unique), `name`, `description`, `mode` (`query`/`act`/`hybrid`), `model`, `system_prompt`, `temperature`, `kb_ids` **JSON**, `skill_ids` **JSON**, `server_ids` **JSON**, `workflow_ids` **JSON**, `status`, `created_by`, timestamps | Four independent binding arrays; `server_ids` restricts the ReAct tool set to declared MCP server tools |
| `conversations` | `id`, `agent_id`, `title`, `messages` **JSON**, `user_id`, `created_at` | Last 6 turns replayed into the ReAct prompt |

### 3.6 MCP servers, Skills, AI models & system (7)

| Table | Key columns | Notes |
| --- | --- | --- |
| `mcp_servers` | `id`, `code` (unique), `name`, `description`, `transport` (`builtin`/`http`/`sse`/`stdio`), `endpoint`, `command`, `auth_config` **JSON**, `tools` **JSON**, `enabled`, `health`, `last_sync_at`, `status`, `source`, `created_by`, timestamps | Independent MCP connection registry; enabled servers contribute tools |
| `mcp_skills` | `id`, `code` (unique), `name`, `type`, `endpoint`, `command`, `enabled`, `status` (`installed`/`disabled`/`uninstalled`/`error`), `version`, `source`, `description`, `manifest` **JSON**, `auth_config` **JSON**, `tools` **JSON**, `health`, `last_sync_at`, `installed_at`, `server_id` (nullable link), timestamps | Independent Skill registry + lifecycle state |
| `mcp_call_logs` | `id`, `request_id`, `method`, `tool`, `source` (`mcp`/`rest`/`agent`/`internal`), `transport`, `actor`, `arguments` **JSON**, `status`, `error`, `result_preview`, `target`, `duration_ms`, `created_at` | Every tool invocation and JSON-RPC method; `target` records `server:<code>` |
| `mcp_skill_files` | `id`, `skill_id`, `path` (unique per skill), `content`, `language`, `size`, `updated_at` | Editable skill files; mirrored to `data/skills/<code>/` |
| `ai_providers` | `id`, `code` (unique), `name`, `category` (`llm`/`asr`/`tts`/`embedding`/`rerank`/`vision`), `vendor`, `base_url`, `api_key`, `model`, `enabled`, `is_default`, `config` **JSON**, `description`, timestamps | Runtime model-service configs; `api_key` never returned in full; `config.env_managed` marks rows still bootstrapped from `.env` |
| `audit_logs` | `id`, `actor`, `action`, `resource`, `detail` **JSON**, `ip`, `level`, `created_at` | Indexed by `created_at DESC` |
| `settings` | `key` (PK), `value` **JSON**, `updated_at` | Runtime overrides (MFA policy, i18n/theme defaults) |

## 4. Indexes (10)

| Index | Column | Purpose |
| --- | --- | --- |
| `idx_submissions_form` | `form_submissions(form_id)` | Submission listing per form |
| `idx_instances_wf` | `workflow_instances(workflow_id)` | Instance listing per workflow |
| `idx_kbdocs_collection` | `kb_documents(collection_id)` | Collection-scoped retrieval |
| `idx_audit_created` | `audit_logs(created_at DESC)` | Recent-activity queries |
| `idx_mcp_calls_created` | `mcp_call_logs(created_at DESC)` | Journal pagination / recent calls |
| `idx_mcp_calls_tool` | `mcp_call_logs(tool)` | Per-tool aggregation and filters |
| `idx_skill_files_skill` | `mcp_skill_files(skill_id)` | Skill file listing |
| `idx_ai_providers_category` | `ai_providers(category, is_default)` | Default provider lookup per category |
| `idx_mcp_servers_enabled` | `mcp_servers(enabled)` | Enabled-server tool discovery |
| `idx_kbdocs_file_type` | `kb_documents(file_type)` | Upload format aggregation |

## 5. Data access API

| Helper | Semantics |
| --- | --- |
| `init_db()` | Execute `SCHEMA` inside a transaction |
| `is_empty()` | Used by `seed_if_empty()` to decide first boot |
| `insert(table, data)` | JSON-encodes values, returns `lastrowid` |
| `update(table, id, data)` | JSON-encodes, `WHERE id=?` |
| `delete(table, id)` | `WHERE id=?` |
| `q(sql, params)` | Return all rows |
| `q1(sql, params)` | Return first row or `None` |
| `scalar(sql, params)` | Return single value |
| `loads(row, *cols)` | Decode JSON columns back into Python objects |
| `run(sql, params)` | Execute under the write lock |

## 6. Seed data (`seed.py`)

`seed_if_empty()` runs once on first boot and creates: 25 permissions, 4 roles, 4 users (`admin`, `alice`, `bob`, `carol`), 5 SSO providers (CAS enabled in demo mode), sample forms and submissions, workflows and instances, knowledge collections/documents, agents, conversations, settings and audit logs. Admin is created with `mfa_required=0` and MFA defaults off, so the demo is immediately usable.

`ensure_registries()` is idempotent and runs on **every** startup (also from `seed_if_empty()`), provisioning three independent registries without touching user data: 3 MCP servers (`platform-builtin`, `thirdparty-http`, `thirdparty-stdio`), 5 catalog Skills (linked to those servers via `server_id`) and 5 default AI model providers (`llm`/`asr`/`tts`/`embedding`/`rerank`). This is also the in-place upgrade path for databases created before the MCP/Skills split.

## 7. Migration notes

- Schema is created idempotently with `CREATE TABLE IF NOT EXISTS`; full table creation is handled by `init_db()`.
- `init_db()` executes `SCHEMA` (tables), then calls `_migrate()`, then executes `INDEX_SCHEMA`. Indexes are created **after** the migration because some reference columns added by `ALTER TABLE` on existing databases.
- `_migrate()` is driven by the `MIGRATIONS` dict; it reads `PRAGMA table_info(<table>)` and issues `ALTER TABLE ... ADD COLUMN` for any missing column. Current migrations: `mcp_skills` (lifecycle fields + `server_id`), `kb_documents` (upload metadata), `agents` (`server_ids`), `mcp_call_logs` (`target`).
- v0.2.0 added the skill lifecycle / journal tables. v0.3.0 adds `mcp_servers` + `ai_providers`, splits MCP servers from Skills, and adds multi-format upload metadata. `ensure_registries()` backfills the new registries on existing databases.
- `skill_files.bootstrap()` runs at startup to materialize default files for installed skills that have none; `mcp_journal.ensure_demo()` seeds illustrative journal rows when the table is empty.
- For production, replace SQLite with Postgres and map JSON columns to `JSONB`; the data access helpers are the single integration seam.
- `backend/data/*.db*` is git-ignored; only `.gitkeep` is committed.
