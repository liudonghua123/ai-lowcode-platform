# REST & MCP API Reference

| Field | Value |
| --- | --- |
| Document ID | `API-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Machine-readable source | `GET /openapi.json`, interactive UI at `GET /docs` |
| Related | [System Architecture](architecture.md) · [AI System Design](ai-design.md) · [Security Architecture](security.md) · [Data Model](data-model.md) |

> 中文摘要：REST API 统一挂在 `/api/v1` 下，共 **96 个 OpenAPI 路径 / 131 个路由装饰器**，除登录与 SSO 外均需 `Authorization: Bearer`；MCP 通过 `/mcp` 提供 streamable HTTP，注册 12 个平台工具（+1 远程工具桥接）。MCP 服务（`/mcp/servers`）与技能（`/skills`）各自独立管理；`/ai/providers` 提供 LLM/ASR/TTS/Embedding/Rerank 多类别模型配置；`/knowledge/upload` 支持 Office/PDF/Markdown 等多格式文档上传；`/agents/meta/bindings` 让创建智能体时可一键绑定 MCP 服务、技能与知识库。本文档列出完整端点、MCP 方法、工具 Schema 与调用示例。详见 [系统架构设计](architecture.zh-CN.md) 与 [MCP 服务、技能与调用日记](mcp-skills.md)。

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

## 2. REST endpoints (96 paths)

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

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/forms` | `form:read` / `form:write` |
| GET | `/forms/field-types` | `form:read` (15 field types) |
| GET | `/forms/code/{code}` | `form:read` |
| GET, PUT, DELETE | `/forms/{form_id}` | `form:read` / `form:write` / `form:delete` |
| POST | `/forms/{form_id}/publish` | `form:publish` |
| GET, POST | `/forms/{form_id}/submissions` | `form:read` / `form:submit` |

### 2.3 Workflows — `/workflows`

| Methods | Path | Permission |
| --- | --- | --- |
| GET, POST | `/workflows` | `workflow:read` / `workflow:write` |
| GET | `/workflows/node-types` | `workflow:read` (9 node types) |
| GET, PUT, DELETE | `/workflows/{workflow_id}` | `workflow:read` / `workflow:write` / `workflow:delete` |
| POST | `/workflows/{workflow_id}/validate` | `workflow:read` |
| POST | `/workflows/{workflow_id}/run` | `workflow:run` |
| GET | `/workflows/{workflow_id}/instances` | `workflow:read` |
| GET | `/workflows/instances/{instance_id}` | `workflow:read` |

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

`POST /agents` / `PUT /agents/{agent_id}` accept `kb_ids`, `skill_ids`, `server_ids` (MCP servers) and `workflow_ids`; unknown ids are dropped. `GET /agents/meta/bindings` returns the servers, skills, collections, workflows and LLM configurations available to the agent editor. The ReAct tool set is filtered to the tools declared by the bound servers / skills. `POST /agents/{agent_id}/chat` body: `{"message": "...", "conversation_id": 12}` → `{answer, steps, sources, model, provider, tools_available, bound_servers, orchestration}`.

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
| GET | `/mcp/tools` | `mcp:read` (12 platform tools + enabled-server tools) |
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

## 3. MCP endpoint `/mcp`

Streamable HTTP, primary transport `fastmcp` 4.1.6 (`http_app(path="/mcp")`), built-in JSON-RPC fallback when the SDK is unavailable. Optional `Authorization: Bearer <token>` for RBAC-checked tool calls.

| Method | Params | Result |
| --- | --- | --- |
| `initialize` | `protocolVersion`, `capabilities`, `clientInfo` | `protocolVersion`, `capabilities{tools,prompts,resources}`, `serverInfo`, `instructions` |
| `notifications/initialized` | — | `202` |
| `ping` | — | `{}` |
| `tools/list` | — | 12 tools with `inputSchema` |
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

## 4. Platform tools (12)

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

`list_tools("openai")` emits the same specs as OpenAI function-calling definitions for the ReAct loop. `mcp_tools.agent_tools(agent)` further filters this catalog to the tools declared by the agent's bound MCP servers (`server_ids`) and skills (`skill_ids`); enabled servers may add remote tool specs resolved through `mcp_servers.external_specs`. The fastmcp bridge tool `call_remote_tool` lets MCP clients reach those remote tools.

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

## 6. Versioning and compatibility

- All business endpoints are versioned under `/api/v1`; breaking changes require a new prefix.
- MCP protocol version is negotiated during `initialize` (no hard-coded client requirement).
- `/openapi.json` is the authoritative machine-readable contract; regenerate this table when routers change.
- `scripts/smoke.py` (110 assertions) exercises the critical subset of these endpoints end-to-end.
