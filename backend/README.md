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
- Smoke test: `python tests/smoke.py` (69 assertions, no external services required).

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
| Knowledge | `GET|POST|PUT|DELETE /knowledge/collections[/{id}]`, `GET|POST|PUT|DELETE /knowledge/documents[/{id}]`, `POST /knowledge/documents/{id}/reindex`, `POST /knowledge/search`, `GET /knowledge/stats` |
| Agents | `GET /agents/meta/runtime`, `GET|POST|PUT|DELETE /agents[/{id}]`, `POST /agents/{id}/chat`, `GET|DELETE /agents/conversations[/{id}]` |
| MCP | `GET /mcp/tools`, `/mcp/status`, `GET|POST|PUT|DELETE /mcp/skills[/{id}]`, `/mcp/skills/catalog`, `/mcp/skills/install`, `/mcp/skills/{id}/{enable,disable,uninstall,reinstall,sync}`, `/mcp/skills/{id}/files[/...]`, `/mcp/calls[/stats,/export,{id}]`, `POST /mcp/invoke` |
| Audit / meta | `GET /audit/logs`, `/audit/actions`, `GET /meta/health`, `/meta/version`, `/meta/stats`, `/meta/bootstrap`, `GET|PUT /settings` |

Every mutating endpoint writes an audit log; every route is protected by `Depends(deps.require(permission))`.

## MCP

`POST /mcp` implements streamable HTTP JSON-RPC using the real `fastmcp` SDK (falls back to a self-contained implementation if the SDK is absent). Methods: `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `resources/templates/list`, `prompts/list`, `prompts/get`, and notifications.

Tools are declared once in `services/mcp_tools.py` and reused by the MCP server, the agent ReAct loop and `POST /api/v1/mcp/invoke`:

`list_forms`, `get_form`, `submit_form`, `query_records`, `list_workflows`, `get_workflow`, `run_workflow`, `get_workflow_instance`, `list_collections`, `search_knowledge`, `list_users`, `get_stats`.

Third-party MCP servers are registered in the `mcp_skills` table (`builtin` / `http` / `sse` / `stdio`); `POST /mcp/skills/{id}/sync` probes the endpoint with `initialize` + `tools/list` and refreshes its tool catalog. Bearer tokens on `/mcp` are bound to the tool context by a pure-ASGI middleware so tool calls are RBAC-checked.

**Skill lifecycle.** `GET /mcp/skills/catalog` lists five ready-to-install templates; `POST /mcp/skills/install` materializes a skill plus five editable files (`SKILL.md`, `manifest.json`, `config.json`, `tools.json`, `README.md`) in `mcp_skill_files` and mirrors them to `data/skills/<code>/`. `enable` / `disable` / `uninstall` / `reinstall` manage the `status` state machine; uninstall removes files but keeps the registry entry. File CRUD lives under `/mcp/skills/{id}/files/{path}`, with path-traversal validation and `POST .../files/reload` to re-read the disk mirror.

**Call journal.** `mcp_call_logs` records every tool invocation (MCP `tools/call`, REST `invoke`, agent tool steps) and every non-tool JSON-RPC method. The ASGI middleware tags the context with `source`/`actor`/`request_id` and buffers the request body once; `mcp_tools.call_tool()` writes arguments, result preview, status, error and duration in a `finally` block so failures are logged too. `GET /mcp/calls` (filters), `/calls/stats` (aggregates), `/calls/export` (CSV), `/calls/{id}` and `DELETE /calls` are guarded by `mcp:read` / `mcp:write`. See [MCP Skills & Call Journal](../docs/mcp-skills.md).

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
