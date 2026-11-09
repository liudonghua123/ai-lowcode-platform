# REST & MCP API Reference

| Field | Value |
| --- | --- |
| Document ID | `API-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Machine-readable source | `GET /openapi.json`, interactive UI at `GET /docs` |
| Related | [System Architecture](architecture.md) · [AI System Design](ai-design.md) · [Security Architecture](security.md) · [Data Model](data-model.md) · [Domestic Form & Approval](form-flow-domestic.md) · [ADR-0009](adr/0009-domestic-forms-and-approval-runtime.md) |

> 中文摘要：REST API 统一挂在 `/api/v1` 下，共 **134 个 OpenAPI 路径 / 174 个路由装饰器**，除登录与 SSO 外均需 `Authorization: Bearer`；MCP 通过 `/mcp` 提供 streamable HTTP，注册 24 个平台工具（+1 远程工具桥接）。MCP 服务（`/mcp/servers`）与技能（`/skills`）各自独立管理；`/ai/providers` 提供 LLM/ASR/TTS/Embedding/Rerank/Vision 六类模型配置；`/knowledge/upload` 支持 Office/PDF/Markdown 等多格式文档上传；`/agents/meta/bindings` 让创建智能体时可一键绑定 MCP 服务、技能与知识库。**国内场景增强**：`/forms` 提供 44 种字段的目录、服务端法定校验、公式求值、版本快照、打印视图与 CSV 导出；`/workflows` 提供 14 种节点、会签/并行/汇聚的人工审批运行时、任务中心、转交/加签/撤回/催办、超时与委托，详见 [国内表单与审批规范](form-flow-domestic.md)。本文档列出完整端点、MCP 方法、工具 Schema 与调用示例。详见 [系统架构设计](architecture.zh-CN.md) 与 [MCP 服务、技能与调用日记](mcp-skills.md)。

## 1. Conventions

| Item | Rule |
| --- | --- |
| Base path | `/api/v1` (`API_PREFIX`) |
| Auth | `Authorization: Bearer <access_token>` (HS256, `typ=access`) |
| Public routes | `/auth/login`, `/auth/providers`, `/auth/sso/*`, `/meta/health`, `/meta/version` |
| Content type | `application/json`; Pydantic v2 request/response models |
| Status codes | `200` OK · `201` created · `401` unauthenticated · `403` permission denied · `404` not found · `422` validation error |
| Error shape | `{"detail": "..."}`; the frontend wraps it in `ApiError` |
| Auditing | Every mutation emits an `audit_logs` row |
| Catalogs | `GET /meta/bootstrap` returns field types, node types, permissions, providers, agent runtime, MCP mode, i18n locales and themes in one call |

### Bootstrap contract (`GET /api/v1/meta/bootstrap`)

```json
{
  "app": {"name": "AI Low-Code Platform", "version": "0.1.0"},
  "i18n": {"locales": ["en", "zh"], "default": "en"},
  "themes": ["system", "light", "dark"],
  "defaults": {"locale": "en", "theme": "system"},
  "form": {"field_types": [...]},
  "workflow": {"node_types": [...]},
  "rbac": {"permissions": [...], "roles": [...]},
  "auth": {"providers": [...], "mfa_policy": {...}},
  "agents": {"runtime": {...}},
  "mcp": {"mode": "fastmcp", "tools": 12},
  "user": {...}
}
```

## 2. REST endpoints (134 paths)

### 2.1 Authentication & MFA — `/auth`

| Methods | Path | Permission | Purpose |
| --- | --- | --- | --- |
| POST | `/auth/login` | public | Password login or MFA challenge/enrollment token |
| POST | `/auth/logout` | authenticated | Client-side session teardown |
| GET | `/auth/me` | authenticated | Current user, roles, permissions |
| POST | `/auth/change-password` | authenticated | Change own password |
| POST | `/auth/mfa/verify` | `mfa`/`enroll` token | Verify OTP or passkey assertion |
| GET, PUT | `/auth/mfa-policy` | `auth:config` (write) | Global / role / user MFA enforcement |
| POST | `/auth/otp/setup`, `/otp/enable`, `/otp/disable` | authenticated | TOTP enrollment |
| POST | `/auth/passkey/register/options`, `/register/verify` | authenticated | WebAuthn registration |
| POST | `/auth/passkey/authenticate/options`, `/authenticate/verify` | public | Passkey sign-in |
| GET, DELETE | `/auth/passkey/credentials[/{credential_id}]` | authenticated | List / remove credentials |
| GET | `/auth/providers` | public | Sanitized SSO provider list (no raw config) |
| GET, PUT | `/auth/sso/providers[/{code}]` | `auth:config` (write) | Provider configuration |
| GET | `/auth/sso/{code}/authorize` | public | Build redirect URL + persist state/nonce |
| GET, POST | `/auth/sso/{code}/callback` | public | Exchange code/ticket, provision user, issue JWT |

### 2.2 Forms — `/forms`

The designer palette, validators, operators, formula functions, permission modes and the China-localized field catalog come from `services/form_catalog.py` (`GET /forms/meta?lang=en|zh`). All statutory validation, formula evaluation, visibility rules and node field permissions are enforced server-side by `services/form_rules.py`; the live preview calls `/evaluate`, which uses the same engine as `/submissions`.

| Methods | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/forms/meta` | `form:read` | 44 field types in 5 groups, validators, operators, 19 functions, permission modes |
| GET | `/forms/field-types` | `form:read` | Flat list of the 44 field types |
| GET | `/forms/regions` | `form:read` | GB/T 2260 administrative-division sample for `region` fields |
| GET, POST | `/forms` | `form:read` / `form:write` | List / create a definition (auto version snapshot) |
| GET | `/forms/code/{code}` | `form:read` | Fetch by stable code |
| GET, PUT, DELETE | `/forms/{form_id}` | `form:read` / `form:write` | Read / update (auto snapshot) / delete |
| POST | `/forms/{form_id}/publish` | `form:publish` | Publish so it accepts submissions |
| POST | `/forms/{form_id}/evaluate` | `form:read` | Live computed values, summaries, visible/hidden keys, permissions, errors |
| POST | `/forms/{form_id}/validate` | `form:read` | Same validation engine, no persistence |
| GET, POST | `/forms/{form_id}/versions` | `form:read` / `form:write` | List snapshots; restore one with `{"version": n}` |
| GET | `/forms/{form_id}/render` | `form:read` | Desktop/mobile render schema with node field permissions |
| GET | `/forms/{form_id}/print/{submission_id}` | `form:read` | Structured print view incl. RMB amount in words |
| GET | `/forms/{form_id}/submissions` | `form:read` | List submissions |
| GET | `/forms/{form_id}/submissions/export` | `form:read` | UTF-8 BOM CSV export for Excel |
| POST | `/forms/{form_id}/submissions` | `form:submit` | Validate, compute, generate `serial_no`, persist |
| PATCH | `/forms/{form_id}/submissions/{submission_id}` | `form:write` | Change status (`submitted`/`approved`/`rejected`/`archived`/`draft`) |

`GET /meta/bootstrap` additionally returns `form.validators`, `form.functions`, `form.permission_modes`, `workflow.approver_rules`, `workflow.sign_modes` and `workflow.actions`. See [FFC-001](form-flow-domestic.md).

### 2.3 Workflows — `/workflows`

Two runtimes coexist: `services/workflow_engine.py` keeps the original synchronous DAG dry-run (`/run`), while `services/flow_runtime.py` drives long-running human approval instances (`/start` → `/instances/.../act`). Instances pin a graph snapshot plus `workflow_version`, so editing a definition never changes an in-flight approval.

| Methods | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/workflows/meta` | `workflow:read` | 14-node palette, 9 approver rules, 4 sign modes, empty/timeout policies, actions |
| GET | `/workflows/node-types` | `workflow:read` | Node palette metadata for the canvas |
| GET, POST | `/workflows` | `workflow:read` / `workflow:write` | List / create a definition (auto version snapshot) |
| GET, PUT, DELETE | `/workflows/{workflow_id}` | `workflow:read` / `workflow:write` | Read / update (auto snapshot) / delete |
| POST | `/workflows/{workflow_id}/publish` | `workflow:write` | Publish the definition |
| GET, POST | `/workflows/{workflow_id}/versions` | `workflow:read` / `workflow:write` | List snapshots; restore one with `{"version": n}` |
| POST | `/workflows/{workflow_id}/validate` | `workflow:read` | Graph validation (start/end, cycles, join/sign modes) |
| POST | `/workflows/{workflow_id}/run` | `workflow:run` | Synchronous dry-run simulator (legacy) |
| POST | `/workflows/{workflow_id}/start` | `workflow:run` | Create a long-running approval instance (optional linked form submission) |
| GET | `/workflows/{workflow_id}/instances` | `workflow:read` | Instances of one workflow |
| GET | `/workflows/tasks` | `workflow:read` | Task center: pending / done tasks for the current user |
| GET | `/workflows/instances/{instance_id}` | `workflow:read` | Instance view with tasks and timeline |
| GET | `/workflows/instances/{instance_id}/tasks` | `workflow:read` | Tasks of an instance |
| GET | `/workflows/instances/{instance_id}/timeline` | `workflow:read` | Approval timeline |
| GET | `/workflows/instances/{instance_id}/form-schema` | `workflow:read` | Bound form schema merged with active node `field_permissions` |
| POST | `/workflows/instances/{instance_id}/tasks/{task_id}/act` | `workflow:run` | `approve` / `reject` / `return` / `transfer` / `addsign_before` / `addsign_after` |
| POST | `/workflows/instances/{instance_id}/withdraw` | `workflow:run` | Initiator cancels a running instance |
| POST | `/workflows/instances/{instance_id}/urge` | `workflow:run` | Remind all pending assignees |
| POST | `/workflows/instances/sweep-timeouts` | `workflow:run` | Apply per-node timeout policies to overdue tasks |
| GET, POST, DELETE | `/workflows/delegations[/{delegation_id}]` | `workflow:read` / `workflow:write` | Approval delegation rules (principal → agent, time window) |
| GET | `/workflows/catalog` | `workflow:read` | Published workflows + bound form + auth-gated share start path (portal catalogue) |
| GET | `/workflows/mine/instances` | `workflow:read` | My launched instances; `status` / `q` / `workflow_id` / `date_from` / `date_to` / `limit` filters |
| GET | `/workflows/mine/stats` | `workflow:read` | Portal counters (startable / total / running / pending approvals) for the caller's scope |
| GET | `/workflows/share-info/{code}` | **public (no token)** | Non-sensitive share metadata: `workflow_id`, `name`, `form_name`, `requires_auth`, `start_path`, `login_path`, `share_url` |
| GET | `/workflows/{workflow_id}/start-schema` | `workflow:read` | Dynamic `FormField[]` start schema rendered from the bound form |

Approver rules: `users`, `roles`, `departments`, `initiator`, `initiator_leader`, `leader_chain`, `form_field`, `previous`, `self_select`. Signing modes: `any` (或签), `all` (会签), `ratio`, `sequence` (依次审批). `comment_required` / `signature_required` and node-level `field_permissions` are enforced server-side. See [FFC-001](form-flow-domestic.md) and [ADR-0009](adr/0009-domestic-forms-and-approval-runtime.md).

**Workflow portal & auth-gated sharing (v0.1.0+).** The redesigned home page uses `/workflows/catalog` for the startable catalogue, `/workflows/mine/instances` and `/workflows/mine/stats` for "my requests" with filters, and `/workflows/tasks` for approvals. Launching is form-based: `GET /workflows/{id}/start-schema` returns the dynamic `FormField[]` schema (the very same type the form designer emits), and `POST /workflows/{id}/start` accepts `{form_data, create_submission}`. Every startable workflow exposes `GET /workflows/share-info/{code}` — the only public business endpoint, returning metadata plus `start_path` (`/#/start/{code}`) and `login_path` (`/#/login?next=/start/{code}`). Opening the share URL anonymously shows a preview and jumps to sign-in, then returns to the start form; `?data=<base64(json)>` prefills it for host-system integration. All business endpoints apply `data_scope.owner_clause()`: super admin `all`, auditor `audit` (read-only), everyone else `self`. See [WFP-001](workflow-portal-and-data-scopes.md) and [ADR-0010](adr/0010-data-scopes-portal-and-agent-actions.md).

### 2.4 Knowledge base — `/knowledge`

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/knowledge/collections` | `knowledge:read` / `knowledge:write` |
| PUT, DELETE | `/knowledge/collections/{collection_id}` | `knowledge:write` / `knowledge:delete` |
| GET, POST | `/knowledge/documents` | `knowledge:read` / `knowledge:write` |
| GET, PUT, DELETE | `/knowledge/documents/{document_id}` | `knowledge:read` / `knowledge:write` / `knowledge:delete` |
| POST | `/knowledge/documents/{document_id}/reindex` | `knowledge:write` |
| POST | `/knowledge/search` | `knowledge:read` |
| GET | `/knowledge/stats` | `knowledge:read` |
| GET | `/knowledge/formats` | `knowledge:read` (supported upload formats) |
| POST | `/knowledge/upload` | `knowledge:write` (multipart: `collection_id`, `files[]`, optional `title`) |

`POST /knowledge/upload` accepts up to 20 files (≤20 MB each) and parses Markdown, plain text, CSV/TSV, JSON/YAML, HTML/XML, PDF (via `pdftotext`), Word `.docx`, Excel `.xlsx/.xlsm`, PowerPoint `.pptx`, OpenDocument `.odt/.ods/.odp`, EPUB, RTF, images (OCR via `tesseract`) and more. Each file becomes a `kb_documents` row with `file_name`, `file_type`, `file_size`, `parse_status`, `parse_error`, and is chunked/indexed for BM25 immediately. See [Knowledge Upload](knowledge-upload.md).

### 2.5 AI agents — `/agents`

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/agents` | `agent:read` / `agent:write` |
| GET, PUT, DELETE | `/agents/{agent_id}` | `agent:read` / `agent:write` |
| POST | `/agents/{agent_id}/chat` | `agent:chat` |
| GET | `/agents/{agent_id}/conversations` | `agent:read` |
| GET, DELETE | `/agents/conversations/{conversation_id}` | `agent:read` |
| GET | `/agents/meta/runtime` | `agent:read` |
| GET | `/agents/meta/bindings` | `agent:read` (all bindable resources in one call) |
| POST | `/agents/{agent_id}/actions` | `agent:chat` (execute a schema-driven dynamic-form action) |

`POST /agents` / `PUT /agents/{agent_id}` accept `kb_ids`, `skill_ids`, `server_ids` (MCP servers) and `workflow_ids`; unknown ids are dropped. `GET /agents/meta/bindings` returns the servers, skills, collections, workflows and LLM configurations available to the agent editor. The ReAct tool set is filtered to the tools declared by the bound servers / skills. `POST /agents/{agent_id}/chat` body: `{"message": "...", "conversation_id": 12}` → `{answer, steps, sources, model, provider, tools_available, bound_servers, orchestration, action_request?}`.

`chat` now plans the message with `agent_intents.plan()` before any side effect: a **`collect`** intent ("create an X workflow") returns `action_request` with a dynamic `FormField[]` schema and creates nothing; a **`tool`** intent ("who am I", "my approvals and progress", "my workflows", "which workflows can I start") calls one self-scoped tool and summarizes it in natural language; everything else falls back to the ReAct / RAG loop. The chat UI renders `action_request.schema` as a `SchemaForm` card and submits `{kind, code, data, conversation_id}` to `POST /agents/{agent_id}/actions`, which executes the real work (starts an approval instance or submits a form) and appends the result to the same conversation.

### 2.6 MCP servers — `/mcp/servers`

MCP servers and Skills are **independent registries** with separate routes, tables and UI pages.

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/mcp/servers` | `mcp:read` / `mcp:write` |
| GET | `/mcp/servers/summary` | `mcp:read` |
| GET, PUT, DELETE | `/mcp/servers/{server_id}` | `mcp:read` / `mcp:write` |
| GET | `/mcp/servers/{server_id}/tools` | `mcp:read` |
| POST | `/mcp/servers/{server_id}/sync` | `mcp:write` |
| POST | `/mcp/servers/{server_id}/enable`, `/disable` | `mcp:write` |
| POST | `/mcp/servers/{server_id}/invoke` | `mcp:invoke` |

A server declares `transport` (`builtin` / `http` / `sse` / `stdio`), `endpoint`/`command`, `auth_config`, `tools`, `enabled`, `health`. `sync` probes a remote streamable-HTTP endpoint with `initialize` + `tools/list`. Enabled servers contribute their declared tools to the shared registry; remote tools are dispatched through `services/mcp_servers.invoke_external` (JSON-RPC `tools/call`) and journaled with `target=server:<code>`.

### 2.7 Skills — `/skills`

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/skills` | `mcp:read` / `mcp:write` |
| GET | `/skills/catalog` | `mcp:read` |
| POST | `/skills/install` | `mcp:write` |
| GET, PUT, DELETE | `/skills/{skill_id}` | `mcp:read` / `mcp:write` |
| POST | `/skills/{skill_id}/enable`, `/disable`, `/uninstall`, `/reinstall` | `mcp:write` |
| POST | `/skills/{skill_id}/sync` | `mcp:write` (through `server_id`) |
| GET | `/skills/{skill_id}/files` | `mcp:read` |
| POST | `/skills/{skill_id}/files/reload` | `mcp:write` |
| GET, PUT, DELETE | `/skills/{skill_id}/files/{path}` | `mcp:read` / `mcp:write` |

A Skill has its own lifecycle, manifest and editable files (`SKILL.md`, `manifest.json`, `config.json`, `tools.json`, `README.md`) mirrored to `data/skills/<code>/`. `server_id` optionally links a skill to an MCP server; deleting a server sets the link to `NULL` without deleting the skill.

### 2.8 MCP transport, tools & call journal — `/mcp`

| Methods | Path | Permission |
| --- | --- | --- |
| GET | `/mcp/tools` | `mcp:read` (20 platform tools + enabled-server tools) |
| GET | `/mcp/status` | `mcp:read` |
| GET | `/mcp/calls`, `/mcp/calls/stats`, `/mcp/calls/export`, `/mcp/calls/{call_id}` | `mcp:read` |
| DELETE | `/mcp/calls` | `mcp:write` |
| POST | `/mcp/invoke` | `mcp:invoke` |

`POST /mcp/invoke` body: `{"tool": "list_forms", "arguments": {"status": "published"}, "target": "server:platform-builtin"}`.
`POST /skills/install` body: `{"code": "weather"}` (or full `InstallIn` fields). `PUT /skills/{id}/files/config.json` body: `{"content": "..."}`.
`GET /mcp/calls` accepts `tool`, `source`, `status`, `actor`, `method`, `q`, `limit`, `offset`. `/mcp/calls/export` returns `text/csv` including the `target` column.

### 2.9 AI model providers — `/ai/providers`

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/ai/providers` | `mcp:read` / `settings:write` |
| GET | `/ai/providers/meta` | `mcp:read` (categories, vendors, defaults, effective runtime) |
| GET, PUT, DELETE | `/ai/providers/{provider_id}` | `mcp:read` / `settings:write` |
| POST | `/ai/providers/{provider_id}/default` | `settings:write` |
| POST | `/ai/providers/{provider_id}/test` | `mcp:read` (optional `{"live": true}` probe) |

Categories: `llm`, `asr`, `tts`, `embedding`, `rerank`, `vision`. `api_key` is write-only — responses contain `has_api_key` and `api_key_masked`. One default per category; the `llm` default overrides `LLM_*` environment variables at runtime. See [AI Model Services](ai-models.md).

See [MCP Servers, Skills & Call Journal](mcp-skills.md) for the two registries, lifecycle state machine, file conventions and journal sources.

### 2.10 RBAC — `/rbac`

| Methods | Path | Permission |
| --- | --- | --- |
| GET | `/rbac/permissions` | `rbac:read` (25 codes) |
| GET | `/rbac/matrix` | `rbac:read` |
| POST | `/rbac/check` | authenticated |
| GET, POST | `/rbac/roles` | `rbac:read` / `rbac:write` |
| PUT, DELETE | `/rbac/roles/{role_id}` | `rbac:write` |
| GET, POST | `/rbac/users` | `rbac:read` / `rbac:write` |
| PUT, DELETE | `/rbac/users/{user_id}` | `rbac:write` |
| POST | `/rbac/users/{user_id}/reset-password` | `rbac:write` |

### 2.11 Audit, metadata & settings

| Methods | Path | Permission |
| --- | --- | --- |
| GET | `/audit/logs`, `/audit/actions` | `audit:read` |
| GET | `/meta/health`, `/meta/version` | public |
| GET | `/meta/bootstrap`, `/meta/stats` | authenticated / `dashboard:view` |
| GET, PUT | `/settings` | `settings:read` / `settings:write` |
| GET, PUT | `/settings/ai` | `settings:read` / `settings:write` |

## 3. MCP endpoint `/mcp`

Streamable HTTP, primary transport `fastmcp` 4.1.6 (`http_app(path="/mcp")`), built-in JSON-RPC fallback when the SDK is unavailable. Optional `Authorization: Bearer <token>` for RBAC-checked tool calls.

| Method | Params | Result |
| --- | --- | --- |
| `initialize` | `protocolVersion`, `capabilities`, `clientInfo` | `protocolVersion`, `capabilities{tools,prompts,resources}`, `serverInfo`, `instructions` |
| `notifications/initialized` | — | `202` |
| `ping` | — | `{}` |
| `tools/list` | — | 24 tools with `inputSchema` |
| `tools/call` | `name`, `arguments` | `content`, `structuredContent`, `isError` |
| `resources/list`, `resources/read`, `resources/templates/list` | `uri` | `platform://stats`, `platform://forms/{code}`, `platform://workflows/{code}` |
| `prompts/list`, `prompts/get` | `name`, `arguments` | `analyze_workflow`, `answer_from_kb` |

### Example

```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"list_forms","arguments":{"status":"published"}}}'
```

## 4. Platform tools (24)

All input schemas are strict objects (`additionalProperties: false`).

| Tool | Required args | Optional args | Permission | Writes |
| --- | --- | --- | --- | --- |
| `list_forms` | — | `status` | `form:read` | no |
| `get_form` | `code` | — | `form:read` | no |
| `submit_form` | `code`, `data` | — | `form:submit` | **yes** |
| `query_records` | — | `form_code`, `limit` (≤100) | `form:read` | no |
| `list_workflows` | — | `status` | `workflow:read` | no |
| `get_workflow` | `code` | — | `workflow:read` | no |
| `run_workflow` | `code` | `context` | `workflow:run` | **yes** |
| `get_workflow_instance` | `instance_id` | — | `workflow:read` | no |
| `list_collections` | — | — | `knowledge:read` | no |
| `search_knowledge` | `query` | `top_k` (≤10) | `knowledge:read` | no |
| `list_users` | — | — | `rbac:read` | no |
| `get_stats` | — | — | `dashboard:view` | no |
| `who_am_i` | — | — | (self context) | no |
| `my_approvals` | — | `status`, `limit` | (self context) | no |
| `my_submissions` | — | `form_code`, `limit` | (self context) | no |
| `my_instances` | — | `status`, `limit` | (self context) | no |
| `list_startable_workflows` | — | — | `workflow:read` | no |
| `get_form_schema` | `code` | — | `form:read` | no |
| `start_workflow_instance` | `code`, `data` | — | `workflow:run` | **yes** |
| `submit_form_data` | `code`, `data` | — | `form:submit` | **yes** |
| `act_approval_task` | — | `action`, `instance_id`, `task_id`, `comment`, `assignee`, `return_to` | `workflow:run` | **yes** |
| `withdraw_instance` | — | `instance_id`, `reason` | `workflow:run` | **yes** |
| `urge_instance` | — | `instance_id`, `message` | `workflow:run` | **yes** |
| `my_notifications` | — | `unread`, `limit` | (self context) | no |
| `act_approval_task` | — | `action`, `instance_id`, `task_id`, `comment`, `assignee`, `return_to` | `workflow:run` | **yes** |
| `withdraw_instance` | — | `instance_id`, `reason` | `workflow:run` | **yes** |
| `urge_instance` | — | `instance_id`, `message` | `workflow:run` | **yes** |
| `my_notifications` | — | `unread`, `limit` | (self context) | no |
| `act_approval_task` | — | `action`, `instance_id`, `task_id`, `comment`, `assignee`, `return_to` | `workflow:run` | **yes** |
| `withdraw_instance` | — | `instance_id`, `reason` | `workflow:run` | **yes** |
| `urge_instance` | — | `instance_id`, `message` | `workflow:run` | **yes** |
| `my_notifications` | — | `unread`, `limit` | (self context) | no |
| `act_approval_task` | — | `action`, `instance_id`, `task_id`, `comment`, `assignee`, `return_to` | `workflow:run` | **yes** |
| `withdraw_instance` | — | `instance_id`, `reason` | `workflow:run` | **yes** |
| `urge_instance` | — | `instance_id`, `message` | `workflow:run` | **yes** |
| `my_notifications` | — | `unread`, `limit` | (self context) | no |

`list_tools("openai")` emits the same specs as OpenAI function-calling definitions for the ReAct loop. `mcp_tools.agent_tools(agent)` further filters this catalog to the tools declared by the agent's bound MCP servers (`server_ids`) and skills (`skill_ids`); enabled servers may add remote tool specs resolved through `mcp_servers.external_specs`. The fastmcp bridge tool `call_remote_tool` lets MCP clients reach those remote tools.

The twelve self-service tools (13–24) are data-scope aware; see above and [NPF-001 §5](notifications-and-profile.md).

## 5. Typical sequences

**Login → catalog → action**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/meta/bootstrap

curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"context":{"days":5}}' \
  http://localhost:8000/api/v1/workflows/1/run
```

**Agent chat**

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"List all forms and show platform statistics"}' \
  http://localhost:8000/api/v1/agents/1/chat
```

**Domestic approval: start → task center → act → timeline**

```bash
# Start the seeded expense_approval workflow with its bound expense_claim form
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"form_data":{"title":"客户拜访报销","department":"IT","mobile":"13800138000",\
       "remark":"客户拜访","items":[{"name":"高铁票","qty":2,"price":320}]}}' \
  http://localhost:8000/api/v1/workflows/2/start       # → {id, current_nodes, status}

# Personal task center
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows/tasks

# Approve one task (other actions: reject / return / transfer / addsign_before / addsign_after)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"approve","comment":"同意","signature":""}' \
  http://localhost:8000/api/v1/workflows/instances/1/tasks/1/act

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows/instances/1/timeline
```

## 6. Versioning and compatibility

- All business endpoints are versioned under `/api/v1`; breaking changes require a new prefix.
- MCP protocol version is negotiated during `initialize` (no hard-coded client requirement).
- `/openapi.json` is the authoritative machine-readable contract; regenerate this table when routers change.
- `backend/tests/smoke.py` (205 assertions) exercises the critical subset of these endpoints end-to-end, including the full domestic expense approval chain.
