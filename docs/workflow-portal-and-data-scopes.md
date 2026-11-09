# Workflow Portal, Data Scopes and Schema-Driven Agent Actions

| Field | Value |
| --- | --- |
| ID | `WFP-001` |
| Status | Accepted |
| Version | 1.0 |
| Applies to | v0.1.0+ (data scopes / portal / agent actions) |
| Related | `API-001` · `SEC-001` · `DAT-001` · `AI-001` · `MCP-001` · `FFC-001` · `ADR-0006` · `ADR-0009` · `ADR-0010` |

> **中文摘要**：本轮把「谁能看到什么数据」从隐含约定升级为单一真源 `services/data_scope.py`：超级管理员 `all`、审计管理员 `audit`（只读查看审计类全部数据）、普通用户 `self`（仅本人数据）、匿名 `anonymous`（无权）。业务数据（表单提交、流程实例、审批任务、会话、审计日志、MCP 调用日记）统一按归属列过滤，定义类资产仍由 RBAC 权限码控制。工作流主页重构为门户：可发起流程目录、我发起的流程（状态/流程/日期/关键词过滤）、待办审批；启动由裸 JSON 改为基于关联表单 schema 的动态表单；每个可发起流程都有需认证跳转的可分享 URL（`/#/start/{code}`），未登录访问跳转登录并回跳，支持 `?data=` 预填，便于集成其它系统。智能体新增身份/权限/审批/流程自助查询与「帮我创建一个 xxx 流程」意图：AI 先分析意图并只返回 `action_request`（不产生副作用），前端用同一套 schema 渲染动态表单，提交后调用 `/agents/{id}/actions` 才真正创建审批实例。内置工具由 12 扩至 20。详见 [系统架构设计](architecture.zh-CN.md)、[接口规范](api-reference.md) 与 [ADR-0010](adr/0010-data-scopes-portal-and-agent-actions.md)。

## 1. Why this change

The previous release exposed every business row to any caller holding a
resource-level `*:read` permission. That is acceptable for a single-tenant demo
but wrong for an enterprise platform: an operator could list another person's
expense claims, and a read-only viewer could read every audit log. At the same
time the workflow home page was a designer-only view, starting an approval
required pasting raw JSON, and the AI agent could only answer questions or fire
immediate tool calls — it could not *collect* structured input before acting.

Four requirements drove this iteration:

1. **Row-level data scopes.** Only the super administrator sees all data; a new
   audit administrator sees all *audit-class* data read-only; everybody else sees
   only their own rows.
2. **A real workflow portal.** Browse startable workflows, launch one, review my
   own launched workflows with filters, and handle my pending approvals.
3. **Form-based launch + shareable URL.** Starting a workflow opens a form
   generated from the bound form schema (never a JSON textarea); workflow↔form
   binding is a dropdown; each startable workflow exposes an auth-gated URL that
   other systems can embed.
4. **Self-aware agent with schema-driven collection.** The agent can answer
   "who am I / what are my permissions / show my approvals and progress"; for
   "create an X workflow" it first asks for the required information through a
   dynamically generated form, then executes.

## 2. Data scope model

`backend/app/services/data_scope.py` is the **single source of truth**. It has no
knowledge of HTTP; routers and tools both call it.

| Scope | Who | Business data | Definition assets |
| --- | --- | --- | --- |
| `all` | `admin` role or `*` permission | read/write everything | RBAC permissions |
| `audit` | `auditor` role / `data:audit` | **read-only**, all rows of audit-class resources | only the read permissions in `AUDITOR_PERMISSIONS` |
| `self` | everyone else | only rows whose owner column equals the current username | RBAC permissions |
| `anonymous` | no session | none | none |

`OWNED_RESOURCES` declares the owner column and whether a resource belongs to
the audit class:

| Resource | Owner column | Audit-class |
| --- | --- | --- |
| `form_submissions` | `submitted_by` | yes |
| `workflow_instances` | `started_by` | yes |
| `flow_tasks` | `assignee` (also visible to the instance initiator) | yes |
| `audit_logs` | `actor` | yes |
| `mcp_call_logs` | `actor` | yes |
| `conversations` | `user_id` | no |

Definition assets (`forms`, `workflows`, `agents`, `knowledge`, `mcp_servers`,
`mcp_skills`, `ai_providers`, `users`, `roles`) are **not** owner-scoped: they are
shared platform configuration and remain governed by RBAC permission codes.
This is deliberate — otherwise a user could not see the form they must fill in.

Key helpers:

- `scope_for(user, resource)` → one of the four scopes.
- `owner_clause(user, resource, alias)` → `(sql_fragment, args)` appended to every
  business query. `all` / `audit` return an empty fragment; `self` returns
  `owner=?`. `flow_tasks` additionally allows the instance initiator.
- `row_visible(user, resource, row)` → used for single-row reads (404 instead of
  403, so enumeration is not possible).
- `describe(user)` → injected into `/auth/me` for the UI.
- `read_only(user)` → `True` for the audit scope.

Enforcement points:

| Layer | File | What it does |
| --- | --- | --- |
| Identity | `deps._load_user()` | injects `data_scope`, `data_scopes`, `is_auditor` |
| RBAC guard | `deps.require()` | audit scope is denied for any action other than `read / view / audit / chat` |
| Forms | `routers/forms.py` | submissions list / CSV export / print view filtered |
| Workflows | `routers/workflows.py` | instance list / detail / tasks / timeline / form-schema filtered; task center ignores `all_users=true` for self users |
| Audit | `routers/audit.py` | `GET /audit/logs` filtered |
| Stats | `routers/meta.py` | `get_stats` tool called with the current user |
| Tools | `services/mcp_tools.py` | `_query_records` / `_get_workflow_instance` / `_get_stats` filtered; `WRITE_TOOLS` blocked for auditors |

The seed adds one permission (`data:audit`), one builtin role (`auditor`, with
`AUDITOR_PERMISSIONS`), and one demo user (`diana / demo1234`, Audit dept).
`ensure_security_upgrade()` is idempotent so existing databases upgrade in
place. Totals: **26 permissions / 5 roles / 6 users**.

## 3. Workflow portal

`GET /workflows/catalog` returns published workflows plus the bound form and a
share start path. `GET /workflows/mine/instances` supports `status`, `q`,
`workflow_id`, `date_from`, `date_to` and `limit`, always filtered through
`owner_clause`. `GET /workflows/mine/stats` supplies the four portal counters.
`GET /workflows/tasks` is the approval task center (self users are pinned to
their own username).

The front-end `WorkflowPortal.tsx` renders three tabs:

- **Launch** — startable workflow cards with one-click launch, copyable share
  link, and (for designers) a jump into the designer.
- **My workflows** — status / workflow / date-range / keyword filters and an
  instance detail dialog (status, tasks, timeline, form data).
- **Approvals** — pending tasks with inline approve / reject.

`Workflows.tsx` now toggles between **Portal** and **Designer** views; the
default is the portal, with `?view=designer` / `?workflow=` deep links preserved.

### Schema-driven start form

`GET /workflows/{id}/start-schema` merges the workflow's bound form schema with
`form_rules.render_schema()` (validators, conditional visibility, field
permissions, mobile single-column layout). The shared `SchemaForm.tsx` component
renders it in three places: the designer's **Start approval** dialog, the portal
launch dialog, and the public share page. It calls `/forms/{id}/evaluate` on each
change so hidden / readonly / computed / validation errors come from the very
same rule engine the form designer uses. Raw JSON submission is gone.

Workflow create/edit and `start` / `form` nodes now pick `form_code` from a
dropdown of existing forms; the backend rejects unknown form codes.

## 4. Auth-gated share URL

`GET /workflows/share-info/{code}` is the only **public** business endpoint (no
token). It returns only non-sensitive metadata: `workflow_id`, `code`, `name`,
`description`, form name, `requires_auth: true`, `start_path`, `login_path`,
`share_url`, `note`. No submissions or instance data are exposed.

```
https://<host>/#/start/expense_approval
        │
        ├─ anonymous → public info card → Sign in
        │                 └─ /#/login?next=/start/expense_approval
        │                       └─ after login → back to /#/start/<code>
        └─ authenticated → GET /workflows/{id}/start-schema
                              → SchemaForm → POST /workflows/{id}/start
                              → success card (instance #, status, pending tasks)
```

Implementation notes:

- `App.tsx` registers `/start/:code` as a public route (outside the
  `AppShell` / `user` guard) and a `LoginRoute` guard that returns to
  `safeNext(next)` instead of `/`.
- `safeNext()` only accepts a single leading `/`, blocking `//evil.com` open
  redirects. `Login.tsx` and `SsoCallback.tsx` both honour `next`; real SSO
  round-trips persist it in `sessionStorage` because they reload the page.
- `?data=<base64(json)>` prefills the start form, so a host system can pass the
  requester / amount / subject without re-keying. Both standard and URL-safe
  base64 with UTF-8 payloads are accepted; malformed input is ignored. The
  sign-in CTA rebuilds `next` from the full current hash query, so the prefill
  survives the anonymous → login → return round trip (verified in a browser).
- The portal's **Copy link** composes
  `window.location.origin + pathname + start_path`, which stays correct behind a
  Quick Tunnel / reverse proxy.
- A viewer without `workflow:run` sees the form but gets an explicit
  "no permission" notice instead of a 403 on submit.

## 5. Agent intents and schema-driven collection

`services/agent_intents.py` plans each message into one of three modes:

| Mode | Trigger | Behaviour |
| --- | --- | --- |
| `collect` | "帮我创建一个 xxx 流程" | returns `action_request` with a dynamic `FormField[]` schema; **no side effects** |
| `tool` | "我是谁 / 我的权限 / 查询我的审批及进度 / 我发起的流程 / 有哪些可发起的流程" | calls one self-scoped tool and summarizes the result in natural language |
| `chat` | everything else | falls back to the original ReAct / RAG loop |

Query-style wording is intercepted before `collect`, so "我发起的流程" is never
misread as "create a workflow". The `collect` schema is derived from
`form_rules.render_schema()` on the workflow's bound form — the same
`FormField` objects used by the designer, portal and public page.

`POST /agents/{id}/chat` returns `action_request` on a `collect` intent. The chat
UI renders a `SchemaForm` card; submitting it calls
`POST /agents/{id}/actions` with `{kind, code, data, conversation_id}`, which
executes `agent_intents.execute()` (starts a real approval instance or submits a
form) and appends the result to the same conversation.

### Tool registry: 12 → 20

Eight self-service / schema tools were added to `mcp_tools.TOOL_SPECS`:

| Tool | Purpose |
| --- | --- |
| `who_am_i` | identity, roles, permissions, data scope |
| `my_approvals` | my pending / completed approval tasks |
| `my_submissions` | my form submissions |
| `my_instances` | workflow instances I started |
| `list_startable_workflows` | published workflows I can launch |
| `get_form_schema` | dynamic `FormField[]` schema for a form |
| `start_workflow_instance` | start an approval instance (self-scoped) |
| `submit_form_data` | submit a form (self-scoped) |

`WRITE_TOOLS = {submit_form, run_workflow, start_workflow_instance,
submit_form_data}` is blocked for auditors. `llm.py` also gained self-service
intent recognition and result summarization so the mock/offline runtime behaves
consistently with the intent planner.

## 6. Verification

```bash
cd backend
python3 -m ruff check app tests            # All checks passed
PYTHONPATH=. python3 tests/smoke.py        # 189 passed, 0 failed

cd ../frontend
pnpm typecheck                            # pass
pnpm check:i18n                           # en 789 / zh 789, 0 missing
pnpm build                                # pass
```

The smoke suite adds assertions for admin/bob/diana scopes, auditor read-only
denial, self-scope submission and instance filtering, task-center pinning,
catalog / mine / stats / share-info / start-schema, auth-gating of the schema,
20 tool specs, identity and approvals intents, `action_request` schema and the
dynamic-form action creating a real instance (withdrawn afterwards).

Runtime figures: **126 OpenAPI paths / 161 route decorators / 26 tables /
17 indexes / 20 MCP tools / 789 i18n keys / 189 assertions**.

## 7. Known limitations

- The audit administrator's read-only guarantee is defence-in-depth at
  `require()`, `mcp_tools.call_tool()` and the route layer; a future write
  endpoint must remember to consult `data_scope.read_only()`.
- Owner scoping is single-dimension (one owner column per resource). Shared
  business data with multiple participants beyond `flow_tasks` would need an ACL
  table.
- `?data=` prefill is unsigned base64; it is a convenience for trusted host
  systems, not an authorization mechanism. All values are still validated by the
  server-side form rule engine on submit.
- The share page shows public metadata but deliberately does **not** auto-redirect
  to sign-in, so an embedding portal can render a meaningful preview; the CTA
  performs the authentication jump.
