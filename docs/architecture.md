# System Architecture Design

| Field | Value |
| --- | --- |
| Document ID | `ARC-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Audience | Architects, backend/frontend engineers, SRE |
| 中文 | [architecture.zh-CN.md](architecture.zh-CN.md) |
| Related | [AI System Design](ai-design.md) · [Security Architecture](security.md) · [Data Model](data-model.md) · [API & MCP Reference](api-reference.md) · [Domestic Form & Approval](form-flow-domestic.md) · [ADR index](adr/README.md) |

## 1. Purpose and scope

This document describes the **as-built architecture** of the AI Low-Code Platform: a full-stack, front-end/back-end separated system that provides a **China-localized form engine** (66 field types, statutory validators, formula sandbox, detail tables, conditional rules), a visual DAG workflow orchestrator plus a **long-running human approval runtime** (countersign, parallel/join, delegation, task actions), a versioned REST API, an MCP server with **independently managed MCP server and Skill registries**, multi-category AI model configuration, multi-format knowledge upload, knowledge-grounded AI query/action agents with declarative resource bindings, RBAC, five SSO protocols and role/user-scoped MFA. The domestic extension is specified in [FFC-001](form-flow-domestic.md) and [ADR-0009](adr/0009-domestic-forms-and-approval-runtime.md).

**In scope:** system context, containers, backend/frontend components, runtime flows, data flow, deployment topology, cross-cutting concerns, quality attributes and evolution boundaries.

**Out of scope:** detailed AI algorithms (see [AI System Design](ai-design.md)), cryptographic/permission details (see [Security Architecture](security.md)), table-by-table schema (see [Data Model](data-model.md)), endpoint contracts (see [API & MCP Reference](api-reference.md)).

## 2. Goals, non-goals and constraints

| Goals | Non-goals |
| --- | --- |
| Fully runnable with zero external services (offline-first demo) | Distributed/multi-tenant production deployment |
| One source of truth for platform capabilities (single tool registry) | A hosted vector database or managed LLM service |
| Every mutation authorized (RBAC) and recorded (audit) | Real WebAuthn attestation hardware validation |
| Consistent UI with i18n (en/zh, default en) and system/light/dark theme | Native mobile applications |
| Single-port deployment for simple operations | Horizontal scaling / HA out of the box |

**Constraints:** Python 3.11+, Node 18+, `uv`, `pnpm`; SQLite standard library (WAL); `fastmcp` 4.x streamable HTTP; `python-multipart` for uploads; stdlib-only document parsing with optional `pdftotext` / `tesseract`; MIT license; no emoji in UI (SVG only).

## 3. Architectural principles

1. **One registry, three consumers.** Every capability exposed to an LLM is declared once in `backend/app/services/mcp_tools.py` (name, JSON Schema, permission, handler). The MCP server, the AI ReAct loop and `POST /api/v1/mcp/invoke` all call the same handlers. See [ADR-0002](adr/0002-single-tool-registry.md).
2. **Offline-first with graceful degradation.** The default `mock` LLM backend works without an API key; MCP falls back to a built-in JSON-RPC transport if `fastmcp` is unavailable. See [ADR-0003](adr/0003-offline-first-llm-runtime.md).
3. **Declarative authorization.** Every business route uses `Depends(require("resource:action"))`; tool calls re-check the same permission through the registry.
4. **Metadata-driven UI.** The frontend never hard-codes catalogs; `/meta/bootstrap` returns field types, node types, permissions, providers, agents runtime, i18n locales and themes in one call.
5. **Stateless request identity, local persistence.** JWT carries identity; SQLite holds state with WAL and a thread-local connection + write lock.

## 4. System context (C4 Level 1)

```mermaid
flowchart TB
    User[End user / Administrator]
    MCPClient[External MCP client<br/>Claude Desktop, IDE, agent]
    IdP[Identity providers<br/>CAS · OAuth2 · OIDC · WeCom · DingTalk]
    LLM[LLM provider<br/>mock / OpenAI-compatible / AgentScope]

    User -->|HTTPS| System[AI Low-Code Platform]
    MCPClient -->|MCP streamable HTTP /mcp| System
    System -->|OIDC / CAS / OAuth2 redirects| IdP
    System -->|chat completions, optional| LLM
```

The platform is a **single deployable unit**: one FastAPI process serves the REST API, the MCP endpoint, OpenAPI docs and (in single-port mode) the built SPA.

## 5. Container view (C4 Level 2)

```mermaid
flowchart LR
    subgraph Browser
        SPA[Vite SPA<br/>React 18 · TS · HashRouter]
    end
    subgraph Process["uvicorn :8000 (FastAPI)"]
        API["REST layer<br/>/api/v1 · 13 routers"]
        MCPS["MCP server<br/>/mcp · fastmcp + builtin fallback"]
        SVC["Service layer<br/>workflow_engine · flow_runtime · rag · llm<br/>form_catalog · form_rules · mcp_tools · mcp_servers<br/>model_providers · documents"]
        SEC["Security layer<br/>JWT · PBKDF2 · TOTP<br/>WebAuthn · RBAC"]
        HOST["SPA static host<br/>frontend/dist fallback"]
    end
    DB[(SQLite<br/>WAL · 30 tables)]
    FS[("dist/ static assets")]

    SPA -->|JSON + Bearer| API
    SPA -->|static| HOST
    API --> SEC
    API --> SVC
    MCPS -->|bind_user via ASGI middleware| SEC
    MCPS --> SVC
    SVC --> DB
    SEC --> DB
    HOST --> FS
```

| Container | Responsibility | Technology |
| --- | --- | --- |
| SPA | All UI, visual designers, i18n, theming | Vite 6, React 18, TypeScript, Tailwind 3, shadcn/ui-style components, lucide-react |
| REST layer | 149 OpenAPI paths, Pydantic models, error semantics | FastAPI 0.128+, `APIRouter`, `Depends` |
| MCP server | MCP `initialize` / `tools/list` / `tools/call` / resources / prompts | `fastmcp` 4.1.6 `http_app(path="/mcp")`, builtin JSON-RPC fallback |
| Service layer | Pure business logic, no HTTP concerns | Python modules in `app/services/` |
| Security layer | Identity, tokens, password/MFA, permission checks | stdlib `hashlib`/`hmac`, HS256 JWT, `contextvars` |
| Persistence | All state | `sqlite3` (WAL, JSON columns, thread-local connection, write lock) |

## 6. Component view (C4 Level 3, backend)

```
app/
├── main.py            lifespan (init_db → seed → fastmcp lifespan), CORS,
│                      MCPAuthASGIMiddleware, router include, SPA catch-all
├── config.py          frozen Settings dataclass, dotenv (backend/.env + root .env)
├── db.py              schema, connection lifecycle, insert/update/delete/q/q1/scalar
├── security.py        password hash, JWT (access/mfa/enroll), TOTP, WebAuthn, MFA policy
├── deps.py            get_current_user, has_permission, require(), audit()
├── seed.py            deterministic first-boot demo data
├── mcp_server.py      fastmcp tools + dependency-free JSON-RPC fallback
├── routers/           auth · rbac · forms · workflows · knowledge · agents · mcp
│                      mcp_servers · skills · ai_providers · audit · meta
└── services/
    ├── mcp_tools.py        ★ capability registry (55 tools, schemas, permissions, agent scoping)
    ├── mcp_servers.py      MCP server registry, probe/sync, external tool bridge
    ├── model_providers.py  6 AI categories, key masking, effective_llm()
    ├── documents.py        stdlib-only multi-format parsing (OOXML/PDF/OCR/text)
    ├── workflow_engine.py  DAG validation (24 node types), condition groups, dry-run execution
    ├── flow_runtime.py     ★ long-running approval: assignee rules, signing modes, tasks, timeouts
    ├── form_catalog.py     ★ 66 field types in 6 groups, validators, operators, functions
    ├── form_rules.py       ★ statutory validation, AST formula sandbox, visibility, permissions
    ├── rag.py              mixed zh/en tokenizer, chunking, BM25, context assembly
    ├── llm.py              3 backends, ReAct orchestration, grounded answers
    ├── data_scope.py       ★ row-level scopes (all/audit/self), owner clauses, row_visible()
    ├── notify.py           ★ notification hub: inbox + webhook/email channels, never-raise emit()
    ├── notify.py           ★ notification hub: inbox + webhook/email channels, never-raise emit()
    ├── agent_intents.py    ★ collect/tool/chat planning, schema-driven action requests
    └── sso.py              5 provider adapters, demo mode, identity provisioning
```

### 6.1 Request pipeline

```
HTTP → CORS → route match → Depends(get_current_user) → Depends(require(permission))
     → Pydantic validation → router → service → db (WAL) → audit() → JSON response
```

MCP requests take a parallel path: `MCPAuthASGIMiddleware` (pure ASGI) decodes the optional `Authorization: Bearer` header, calls `mcp_tools.bind_user(user)` via a `ContextVar`, then the fastmcp/builtin handler invokes `mcp_tools.call_tool()` which performs the same permission check.

### 6.2 Frontend composition

```
main.tsx → HashRouter · ThemeProvider · I18nProvider · ToastProvider · AppContext
         → App.tsx (auth guard, Splash) → AppShell (sidebar/header/user menu)
         → 14 page modules
```

`lib/api.ts` wraps `fetch` with JWT injection, `ApiError`, and a global `401 → logout` event. `AppContext` loads `/auth/me` + `/meta/bootstrap` once after login and exposes `can(permission)`.

The shared `components/SchemaForm.tsx` renders the backend `FormField[]` schema in four places — the designer's start dialog, the portal launch dialog, the public share page and the agent's dynamic collection card — and calls `/forms/{id}/evaluate` for visibility / permissions / computed values. `pages/WorkflowPortal.tsx` is the redesigned workflow home (catalog / my-workflows / approvals); `pages/StartWorkflow.tsx` is the public `/#/start/{code}` landing; `components/layout/NotificationBell.tsx` polls the unread counter and renders the in-app inbox; `pages/Profile.tsx` is the personal center (profile, password, counters, groups, delegations, notification preferences); `components/layout/NotificationBell.tsx` polls the unread counter and renders the in-app inbox; `pages/Profile.tsx` is the personal center (profile, password, counters, groups, delegations, notification preferences); `App.tsx` registers it as a public route with a `safeNext()` login round trip, and `Workflows.tsx` toggles Portal / Designer views.

## 7. Key runtime flows

### 7.1 Authentication with MFA and SSO

```mermaid
sequenceDiagram
    participant U as User
    participant F as SPA
    participant A as /api/v1/auth
    participant S as security.py
    participant D as SQLite

    U->>F: credentials or SSO button
    F->>A: POST /auth/login or /auth/sso/{code}/authorize
    A->>S: verify_password / exchange()
    S->>D: load user, roles, permissions
    alt MFA policy applies (global / role / user)
        A-->>F: mfa_required + enroll/verify token
        U->>F: OTP code or passkey assertion
        F->>A: POST /auth/mfa/verify
    end
    A-->>F: access_token (HS256, typ=access, TTL 7200s)
    F->>A: GET /meta/bootstrap (catalogs)
```

### 7.2 AI agent executing a real platform action

```mermaid
sequenceDiagram
    participant U as User
    participant R as agents router
    participant L as llm.run_agent
    participant G as rag
    participant T as mcp_tools
    participant D as SQLite

    U->>R: POST /agents/{id}/chat
    R->>T: bind_user(user)
    R->>L: run_agent(agent, message, history)
    L->>G: search(message, kb_ids, top_k)
    G-->>L: hits → [Knowledge Context]
    loop ReAct round (max 5)
        L->>L: chat(messages, tools) → tool_calls
        L->>T: call_tool(name, args, user)
        T->>T: permission check (PERMISSION_MAP)
        T->>D: read/write (submit form, run workflow…)
        T-->>L: result → role=tool message
    end
    L-->>R: answer + steps + sources + provider
    R->>D: persist conversation
    R-->>U: response with visible tool-call steps
```

### 7.3 Workflow execution (synchronous dry-run)

`validate_graph()` enforces exactly one `start`, at least one `end`, known node types, valid edge endpoints and no cycles (DFS three-state). `run()` walks the DAG, evaluates `condition` nodes against context (`gt/gte/lt/lte/eq/ne/contains` plus condition groups), dispatches `form/approval/ai/knowledge/http/notification/cc/parallel/join/delay/subflow` nodes, and returns `{status, context, logs}` persisted to `workflow_instances`.

### 7.4 Long-running domestic approval instance

`POST /workflows/{id}/start` creates an instance that **pins a graph snapshot** plus `workflow_version`, so later definition edits cannot change an in-flight approval. `services/flow_runtime.py` resolves assignees from 9 rules (`users`, `roles`, `departments`, `initiator`, `initiator_leader`, `leader_chain`, `form_field`, `previous`, `self_select`), applies active `flow_delegations`, then creates one `flow_tasks` row per assignee per node activation. Signing modes `any` / `all` / `ratio` / `sequence` decide when a node completes; `parallel` + `join` gate concurrent branches. Each `act` (approve / reject / return / transfer / add-sign) writes an audit log and a timeline entry; `withdraw`, `urge` and `sweep_timeouts()` cover initiator cancellation, reminders and overdue policies. `GET /workflows/instances/{id}/form-schema` merges the bound form schema with the active node's `field_permissions`, and `form_rules.validate_data()` enforces `editable` / `readonly` / `hidden` server-side. See [FFC-001](form-flow-domestic.md).

### 7.5 Auth-gated share link and schema-driven collection

A host system embeds `https://<host>/#/start/{code}`. Phase 1 (anonymous) calls
the **public** `GET /workflows/share-info/{code}`, shows non-sensitive metadata
and a sign-in CTA to `/#/login?next=/start/{code}`; `safeNext()` rejects open
redirects and `sessionStorage` preserves `next` across real SSO reloads. Phase 2
(authenticated) loads `GET /workflows/{id}/start-schema` → `SchemaForm` →
`POST /workflows/{id}/start`, with optional `?data=<base64(json)>` prefill. No
submission or instance data is exposed before authentication.

The agent mirrors this pattern: `agent_intents.plan()` returns a `collect`
intent with an `action_request` schema and **no side effect**; the chat UI
renders a `SchemaForm` card and only `POST /agents/{id}/actions` performs the
work. Every business read in both flows goes through
`data_scope.owner_clause()`. See [WFP-001](workflow-portal-and-data-scopes.md).

## 8. Data flow

| Flow | Path | Storage |
| --- | --- | --- |
| Form definition | Designer → `PUT /forms/{id}` → JSON `schema` column | `forms`, `form_submissions` |
| Form rules / versions | `POST /forms/{id}/evaluate` → `form_rules` → snapshot on publish | `form_versions`, `form_submissions.computed` |
| Workflow graph | Canvas → `PUT /workflows/{id}` → JSON `graph` column | `workflows`, `workflow_instances` |
| Approval instance | `POST /workflows/{id}/start` → `flow_runtime` → `/instances/.../act` | `workflow_versions`, `flow_tasks`, `flow_delegations`, `org_units` |
| Knowledge (text) | Document create → `rag.index_document()` → JSON `chunks` | `kb_collections`, `kb_documents` |
| Knowledge (upload) | Multipart → `documents.parse()` → `rag.index_document()` → file metadata + chunks | `kb_documents` |
| Agent chat | Chat → `agent_intents.plan()` → `run_agent()` / scoped tool / dynamic form → conversation turns | `conversations`, `audit_logs` |
| Portal & share | `/workflows/catalog` · `/mine/instances` → `/{id}/start-schema` → `/{id}/start` | `workflow_instances`, `form_submissions`, `flow_tasks` |
| MCP server registry | Server config → probe/sync → declared tools | `mcp_servers` |
| Skill registry | Install → lifecycle → editable files → optional `server_id` link | `mcp_skills`, `mcp_skill_files` |
| AI model providers | `.env` bootstrap → category defaults → `effective_llm()` → runtime override; Settings card + `/models` manager | `ai_providers` |
| Configuration | `.env` → `Settings` → runtime overrides | `settings` |

All complex structures are stored as JSON text columns, transparently serialized by `db._enc/_dec` and `db.loads()`.

## 9. Deployment view

| Mode | Command | Ports | Use |
| --- | --- | --- | --- |
| Development | `./scripts/dev.sh` | `:8000` API + `:5173` Vite (proxy `/api`, `/mcp`) | HMR, fast iteration |
| Single-port | `./scripts/start.sh` | `:8000` only | Demo / simple deployment; FastAPI serves `frontend/dist` |
| API-only | `uvicorn app.main:app --port 8000` | `:8000` | Headless API + MCP consumers |

The SPA catch-all is registered unconditionally and resolves `dist/index.html` per request, so the backend can start before the frontend is built. Paths `/api`, `/mcp`, `/docs`, `/openapi.json` are protected from the fallback. `HashRouter` avoids server-side route configuration.

## 10. Cross-cutting concerns

| Concern | Implementation |
| --- | --- |
| i18n | 929 leaf keys per locale, default `en`, `localStorage`, `<html lang>` sync, English fallback |
| Theme | `system` (default) / `light` / `dark`, `prefers-color-scheme` listener, HSL CSS variables, `meta[theme-color]` |
| Audit | Every mutation → `audit_logs(actor, action, resource, detail, ip, level, created_at)` |
| Configuration | `python-dotenv` → frozen `Settings`; `settings` table for runtime overrides |
| Errors | `HTTPException` with 401 / 403 / 404 / 422; `ApiError` on the client; 401 triggers global logout |
| Observability | `/api/v1/meta/health`, `/meta/stats`, `/agents/meta/runtime`, `/agents/meta/bindings`, `/mcp/status`, `/mcp/calls/stats`, `/knowledge/stats` |
| Testing | `backend/tests/smoke.py` — 272 end-to-end assertions; `pnpm typecheck`, `pnpm build`, `pnpm check:i18n`, `ruff check` |

## 11. Technology decisions (summary)

| Decision | Rationale | ADR |
| --- | --- | --- |
| Monorepo, front/back separation, uv + pnpm | Independent toolchains, one clone to run | [0001](adr/0001-monorepo-and-stack.md) |
| Single tool registry for MCP + Agent + REST | Prevents capability drift, one permission gate | [0002](adr/0002-single-tool-registry.md) |
| Offline-first LLM with 3 backends | Zero-config demo, upgradeable to real models | [0003](adr/0003-offline-first-llm-runtime.md) |
| SQLite + in-process BM25 | No external service, mixed zh/en retrieval | [0004](adr/0004-sqlite-and-local-bm25.md) |
| fastmcp primary + builtin fallback, ASGI auth binding | Real MCP compliance plus resilience | [0005](adr/0005-mcp-transport-and-auth.md) |
| RBAC + policy-driven MFA + demo SSO | Complete auth surface without external IdP | [0006](adr/0006-rbac-mfa-and-sso.md) |
| Skill lifecycle, editable files and call journal | Auditable third-party capability management | [0007](adr/0007-mcp-skill-lifecycle-and-journal.md) |
| Split MCP servers / Skills, AI model providers, knowledge upload, agent bindings | Independent registries and configurable model / knowledge resources | [0008](adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md) |
| Domestic form engine + long-running human approval runtime | Cover China enterprise/government form & approval scenarios without a relational per-field schema | [0009](adr/0009-domestic-forms-and-approval-runtime.md) |
| Centralised data scopes, portal, auth-gated share URL, schema-driven agent actions | One authorization source of truth; schema reuse across four surfaces; no agent side effect before human confirmation | [0010](adr/0010-data-scopes-portal-and-agent-actions.md) |

## 12. Quality attributes and trade-offs

| Attribute | Current posture | Evolution path |
| --- | --- | --- |
| Availability | Single process, SQLite WAL | Multi-worker + Postgres, shared session store |
| Security | HS256 JWT, PBKDF2, per-route RBAC, audit | RS256/rotating keys, rate limiting, secret manager |
| AI accuracy | Deterministic mock + BM25 grounding | Real LLM, vector/embedding store, reranking |
| Scalability | In-process indexes, synchronous execution | Task queue for workflow runs, external vector DB |
| Testability | 272 smoke assertions, no network required | Contract tests, load tests, MCP conformance suite |
| Operability | Health/stats/runtime endpoints | Structured logging, metrics, tracing |

## 13. Known limitations

- SQLite and in-process BM25 are single-node; no cross-process index sharing.
- `mock` LLM uses regex intent detection — it is deterministic, not generative.
- WebAuthn uses challenge/credential binding without full attestation verification; `PASSKEY_ORIGIN` must match the deployment (HTTPS or localhost).
- SSO demo mode provisions local users without real IdP validation; production requires real credentials and TLS.
- The **synchronous** `/run` dry-run still executes inside the request; real human approvals use persisted long-running instances, but `subflow`, `delay`, `signature`/`attachment` storage and the GB/T 2260 region sample remain simulated or partial (see [FFC-001 §7](form-flow-domestic.md)). A task queue is still the production path for very long flows.

## 14. Traceability

| Requirement | Design element | Code |
| --- | --- | --- |
| Visual form design | Metadata-driven designer | `routers/forms.py`, `pages/Forms.tsx` |
| Domestic forms (FFC-001) | 66-field catalog, statutory validation, AST formulas, versions, print/CSV | `services/form_catalog.py`, `services/form_rules.py`, `routers/forms.py`, `pages/Forms.tsx` |
| Visual workflow orchestration | DAG validator + engine | `services/workflow_engine.py`, `pages/Workflows.tsx` |
| Human approval runtime (ADR-0009) | Long-running instances, countersign, parallel/join, task actions, delegation | `services/flow_runtime.py`, `routers/workflows.py`, `pages/Workflows.tsx` |
| REST API | Versioned routers | `routers/*.py` (192 route decorators → 149 OpenAPI paths) |
| MCP transport + tool registry | Dual-transport MCP + single registry | `mcp_server.py`, `routers/mcp.py`, `services/mcp_tools.py` |
| MCP servers (independent) | CRUD, probe/sync, declared tools, remote invoke | `routers/mcp_servers.py`, `services/mcp_servers.py`, `mcp_servers` |
| Skills (independent) | Lifecycle, catalog, editable files, `server_id` link | `routers/skills.py`, `services/skill_*.py`, `mcp_skills` |
| AI query/act agents | ReAct + bound tool scope + RAG | `services/llm.py`, `services/rag.py` |
| Agent resource bindings | `GET /agents/meta/bindings`, create/update with id cleanup | `routers/agents.py`, `pages/Agents.tsx` |
| AI model providers | 6 categories, write-only keys, runtime LLM override | `routers/ai_providers.py`, `services/model_providers.py`, `ai_providers` |
| Knowledge base | BM25 + chunking + multi-format upload | `services/rag.py`, `services/documents.py`, `routers/knowledge.py` |
| RBAC / SSO / MFA | Declarative guards + adapters | `deps.py`, `security.py`, `services/sso.py` |
| i18n / theme | Providers + bootstrap | `i18n/`, `theme/`, `routers/meta.py` |
