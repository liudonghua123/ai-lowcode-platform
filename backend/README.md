# Backend — AI Low-Code Platform

FastAPI service built with **uv + python-dotenv + fastmcp + AgentScope**. SQLite persistence, JWT/RBAC security, SSO/MFA, a DAG workflow engine, BM25 RAG, AI agents and an MCP streamable-HTTP server.

中文：[README.zh-CN.md](README.zh-CN.md) · [Root README](../README.md)

## Run

```bash
cp .env.example .env
uv sync                          # or: pip3 install fastapi uvicorn python-dotenv httpx fastmcp agentscope
uv run uvicorn app.main:app --reload --port 8000
```

- REST: `http://localhost:8000/api/v1` · OpenAPI: `/docs` · MCP: `http://localhost:8000/mcp`
- If `../frontend/dist` exists it is served at `/` (single-port mode).
- The database at `data/platform.db` is created and seeded on first boot. Delete it to re-seed.
- Smoke test: `python tests/smoke.py` (110 assertions, no external services required).

## Layout

```
app/
  main.py            FastAPI app, CORS, routers, SPA hosting, MCP ASGI mount, lifespan
  config.py          dotenv settings (single frozen Settings instance)
  db.py              SQLite helpers (q/q1/run/insert/update/delete + JSON columns)
  security.py        PBKDF2, JWT HS256, TOTP, WebAuthn challenges, MFA policy
  deps.py            get_current_user / require(permission) / audit()
  seed.py            permissions, roles, users, forms, workflows, KB, agents, skills
  mcp_server.py      fastmcp tool definitions + builtin JSON-RPC fallback
  routers/           auth · rbac · forms · workflows · knowledge · agents · mcp · audit · meta
  services/
    mcp_tools.py       the single tool registry (schema + permission + handler)
    workflow_engine.py DAG validation, condition routing, execution logs
    rag.py             zh/en tokenizer, chunking, BM25 retrieval, context assembly
    llm.py             mock / OpenAI-compatible / AgentScope chat + ReAct loop
    sso.py             CAS, OAuth2, OIDC, WeCom, DingTalk providers
    mcp_journal.py     call journal persistence, queries, stats, CSV export data
    skill_catalog.py   installable skill templates + default file generator
    skill_files.py     editable skill files, path validation, disk mirror
```

## REST endpoints (prefix `/api/v1`)

| Group | Endpoints |
| --- | --- |
| Auth | `POST /auth/login`, `/auth/mfa/verify`, `/auth/change-password`, `GET /auth/me`, `POST /auth/logout` |
| OTP | `POST /auth/otp/setup`, `/auth/otp/enable`, `/auth/otp/disable` |
| Passkey | `POST /auth/passkey/register/options` + `/verify`, `POST /auth/passkey/authenticate/options` + `/verify`, `GET|DELETE /auth/passkey/credentials[/{id}]` |
| MFA policy | `GET|PUT /auth/mfa-policy` |
| SSO | `GET /auth/providers`, `GET /auth/sso/providers`, `PUT /auth/sso/providers/{code}`, `GET /auth/sso/{code}/authorize`, `GET|POST /auth/sso/{code}/callback` |
| RBAC | `GET /rbac/permissions`, `/rbac/matrix`, `GET|POST|PUT|DELETE /rbac/users[/{id}]`, `GET|POST|PUT|DELETE /rbac/roles[/{id}]`, `POST /rbac/users/{id}/reset-password`, `POST /rbac/check` |
| Forms | `GET /forms/field-types`, `GET|POST /forms`, `GET /forms/code/{code}`, `GET|PUT|DELETE /forms/{id}`, `POST /forms/{id}/publish`, `GET|POST /forms/{id}/submissions` |
| Workflows | `GET /workflows/node-types`, `GET|POST /workflows`, `GET|PUT|DELETE /workflows/{id}`, `POST /workflows/{id}/validate`, `/run`, `GET /workflows/{id}/instances`, `GET /workflows/instances/{id}` |
| Knowledge | `GET|POST|PUT|DELETE /knowledge/collections[/{id}]`, `GET|POST|PUT|DELETE /knowledge/documents[/{id}]`, `POST /knowledge/documents/{id}/reindex`, `POST /knowledge/search`, `GET /knowledge/stats`, `GET /knowledge/formats`, `POST /knowledge/upload` |
| Agents | `GET /agents/meta/runtime`, `GET /agents/meta/bindings`, `GET|POST|PUT|DELETE /agents[/{id}]`, `POST /agents/{id}/chat`, `GET|DELETE /agents/conversations[/{id}]` |
| MCP transport | `GET /mcp/tools`, `/mcp/status`, `GET /mcp/calls[/stats,/export,{id}]`, `DELETE /mcp/calls`, `POST /mcp/invoke` |
| MCP servers | `GET|POST|PUT|DELETE /mcp/servers[/{id}]`, `GET /mcp/servers/summary`, `GET /mcp/servers/{id}/tools`, `POST /mcp/servers/{id}/{sync,enable,disable,invoke}` |
| Skills | `GET|POST|PUT|DELETE /skills[/{id}]`, `GET /skills/catalog`, `POST /skills/install`, `POST /skills/{id}/{enable,disable,uninstall,reinstall,sync}`, `GET|PUT|DELETE /skills/{id}/files[/...]`, `POST /skills/{id}/files/reload` |
| AI models | `GET /ai/providers/meta`, `GET|POST|PUT|DELETE /ai/providers[/{id}]`, `POST /ai/providers/{id}/{default,test}` |
| Audit / meta | `GET /audit/logs`, `/audit/actions`, `GET /meta/health`, `/meta/version`, `/meta/stats`, `/meta/bootstrap`, `GET|PUT /settings` |

Every mutating endpoint writes an audit log; every route is protected by `Depends(deps.require(permission))`.

## MCP

`POST /mcp` implements streamable HTTP JSON-RPC using the real `fastmcp` SDK (falls back to a self-contained implementation if the SDK is absent). Methods: `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `resources/templates/list`, `prompts/list`, `prompts/get`, and notifications.

Tools are declared once in `services/mcp_tools.py` and reused by the MCP server, the agent ReAct loop and `POST /api/v1/mcp/invoke`:

`list_forms`, `get_form`, `submit_form`, `query_records`, `list_workflows`, `get_workflow`, `run_workflow`, `get_workflow_instance`, `list_collections`, `search_knowledge`, `list_users`, `get_stats`.

**Independent registries.** MCP servers and Skills are separate entities with separate tables, routers and lifecycles (see [ADR-0008](../docs/adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md)):

| Registry | Table | Router | Responsibility |
| --- | --- | --- | --- |
| MCP servers | `mcp_servers` | `/mcp/servers` | Connection config (`transport`, `endpoint` / `command`, `auth_config`), `probe()` + `sync()` tool discovery, health/status, `invoke_on_server()` |
| Skills | `mcp_skills` | `/skills` | Lifecycle, catalog, manifest, editable files, nullable `server_id` link |

`services/mcp_servers.py::declared_tools()` merges enabled-server tools into `mcp_tools.list_tools(include_external=True)`; the `call_remote_tool` MCP bridge forwards a call to the owning server with `mcp:invoke` and a `target=server:<code>` journal entry. `mcp_tools.agent_tools(agent, fmt)` narrows the ReAct tool set to an agent's `server_ids` / `skill_ids` bindings. Deleting either entity never deletes the other.

**MCP servers.** `GET /mcp/servers/summary` exposes registry stats; `POST /mcp/servers` registers a `http` / `sse` / `stdio` connection; `POST /mcp/servers/{id}/sync` probes the endpoint with `initialize` + `tools/list` and refreshes the declared tool list; `GET /mcp/servers/{id}/tools`, `/{id}/enable`, `/{id}/disable` and `/{id}/invoke` complete the surface. Bearer tokens on `/mcp` are bound to the tool context by a pure-ASGI middleware so tool calls are RBAC-checked.

**Skill lifecycle.** `GET /skills/catalog` lists five ready-to-install templates; `POST /skills/install` materializes a skill plus five editable files (`SKILL.md`, `manifest.json`, `config.json`, `tools.json`, `README.md`) in `mcp_skill_files` and mirrors them to `data/skills/<code>/`. `enable` / `disable` / `uninstall` / `reinstall` manage the `status` state machine; uninstall removes files but keeps the registry entry. `POST /skills/{id}/sync` refreshes tools from the linked server (`server_id`). File CRUD lives under `/skills/{id}/files/{path}`, with path-traversal validation and `POST .../files/reload` to re-read the disk mirror.

**AI model services.** `GET /ai/providers/meta` returns six categories (`llm`, `asr`, `tts`, `embedding`, `rerank`, `vision`) and vendors; `GET|POST|PUT|DELETE /ai/providers[/{id}]` manages configurations (`api_key` is write-only — reads return only `has_api_key` / `api_key_masked`); `POST /ai/providers/{id}/default` enforces one default per category and `/{id}/test` probes connectivity. `model_providers.effective_llm()` lets the `llm` default override `LLM_*` environment variables at runtime.

**Knowledge upload.** `GET /knowledge/formats` lists supported extensions; `POST /knowledge/upload` accepts multipart batches parsed by `services/documents.py` (OOXML / OpenDocument / EPUB via stdlib ZIP+XML, PDF via `pdftotext`, images via `tesseract`, plus text/data formats) and immediately chunks/indexes extracted text for BM25. See [Knowledge Upload](../docs/knowledge-upload.md).

**Agent bindings.** `GET /agents/meta/bindings` returns all bindable resources; create/update accepts `kb_ids`, `skill_ids`, `server_ids` and `workflow_ids`, with stale ids removed on save by `routers/agents.py::_clean_ids()`.

**Call journal.** `mcp_call_logs` records every tool invocation (MCP `tools/call`, REST `invoke`, agent tool steps) and every non-tool JSON-RPC method, with a `target` column for external servers. The ASGI middleware tags the context with `source`/`actor`/`request_id` and buffers the request body once; `mcp_tools.call_tool()` writes arguments, result preview, status, error and duration in a `finally` block so failures are logged too. `GET /mcp/calls` (filters), `/calls/stats` (aggregates), `/calls/export` (CSV), `/calls/{id}` and `DELETE /calls` are guarded by `mcp:read` / `mcp:write`. See [MCP Servers, Skills & Call Journal](../docs/mcp-skills.md).

## Auth & security model

- Passwords: PBKDF2-HMAC-SHA256 (180k rounds, per-user salt). Tokens: HS256 JWT (`typ` = `access` / `mfa` / `enroll`).
- OTP: RFC 6238 TOTP, 6 digits, 30 s, ±1 window; `otpauth://` provisioning URI for QR enrollment.
- Passkey: WebAuthn challenge → `navigator.credentials.create/get` → credential binding. Demo-grade attestation; install the `webauthn` extra for full verification (HTTPS required).
- MFA policy: global / per role / per user; if a policy applies but no factor is enrolled, login returns an `enroll_token` and the UI guides the user through enrollment.
- SSO: real protocol flows (CAS ticket validation, OAuth2 code exchange + userinfo, OIDC discovery + ID token nonce check, WeCom/DingTalk token + user APIs) with an automatic, clearly flagged demo fallback when credentials are missing.

## LLM / AgentScope

`LLM_PROVIDER=mock` (default) provides deterministic intent recognition and grounded answers so the whole platform works offline. `openai-compatible` calls any chat-completions endpoint; `agentscope` builds an `agentscope.model` chat model when installed and credentials are present, otherwise transparently degrades. `services/llm.py` implements the ReAct loop: retrieve RAG context → let the model request tools → execute the shared tool registry → feed results back → answer with sources.

## Configuration

See `.env.example`. All settings are read once via `config.Settings` from `.env`; SSO/MFA/platform settings can additionally be changed at runtime through the API (stored in the `settings` table).

**Production:** set a strong `SECRET_KEY`, use HTTPS, replace SQLite, configure real SSO/LLM credentials, install `webauthn` for passkey attestation, and require MCP authentication. Approval/HTTP/notification workflow nodes are simulated in the demo engine.

## License

[MIT](../LICENSE)
