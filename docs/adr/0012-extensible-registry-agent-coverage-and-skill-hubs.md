# ADR-0012: Declarative component/node registry, permission-driven full agent coverage, independent Skills and Skill Hubs

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-10 |
| Deciders | Platform architecture |
| Related | `ADR-0002` (single tool registry), `ADR-0007` (skill lifecycle), `ADR-0008` (MCP/Skills split), `ADR-0009` (domestic form/approval runtime), `REG-001`, `AI-001`, `API-001`, `DAT-001` |

## Context

Four structural problems had accumulated:

1. **Duplicated type catalogues.** Form field types lived in `form_catalog.py`, workflow node types were hard-coded in `workflow_engine.NODE_TYPES`, `/forms/meta` and `/workflows/meta` built their own payloads, and the React designer property panels had hard-coded JSX branches per type. Adding one type meant editing 5+ files, and the lists could drift. The catalogue had stalled at 44 field types / 14 node types.
2. **Agents could not do what the user could.** `TOOL_SPECS` exposed 24 tools (business + self-service), while the platform had grown MCP servers, Skills, settings, AI providers, RBAC, audit logs, knowledge documents, groups/delegations and registry metadata. An admin chatting with an agent could not list roles, search a skill marketplace or register a component.
3. **MCP / Skills separation was incomplete.** ADR-0008 split the entities, but `routers/skills.py` still required `mcp:read` / `mcp:write`, and the Skills UI still loaded MCP servers, so the two registries were not independently governable.
4. **Skills were opaque.** Files were editable only as raw text, and there was no way to discover third-party skills other than a hard-coded built-in catalog.

Constraints: the platform must keep working fully offline, must remain a single SQLite file with idempotent migrations, and must not require a redeploy for user-supplied extensions.

## Decision

1. **Introduce `services/registry.py` as the single source of truth.** It declares `FORM_COMMON_SCHEMA` / `FORM_CAP_SCHEMA` and 24 `NODE_SPECS` with `config_schema`, owns `NODE_EXECUTORS`, and normalizes runtime-registered custom specs persisted in `settings.registry.custom_types`. `workflow_engine`, `flow_runtime`, `/forms/meta`, `/workflows/meta`, `/meta/registry`, `/meta/bootstrap`, `/meta/health` and both React designers all consume it. The catalogues grow to **66 form components / 6 groups** and **24 workflow nodes / 6 categories**. New types are registerable through `POST /meta/registry/{components|nodes}` with `form:write` / `workflow:write`.
2. **Make agent capability coverage complete and permission-driven.** Extend `TOOL_SPECS` from 24 to **55** by adding `agent_admin_tools.py` (31 system tools). Every spec declares a permission; `list_tools`, `call_tool`, MCP `tools/list`, `/mcp/tools` and `/agents/meta/runtime` filter by the caller. `capability_matrix()` groups tools into 10 permission domains; the agent studio renders it as a **Capabilities** panel. `agent_intents._system_plan()` maps natural-language administration requests to those tools.
3. **Complete the MCP / Skills split.** Add `skill:read` / `skill:write` (28 permissions total), switch all Skills and Skill Hub routes to them, remove the Skills UI's dependency on `/mcp/servers`, and add `seed.ensure_permission_upgrade()` for idempotent in-place upgrades of existing databases.
4. **Add visual skill editing and Skill Hubs.** `GET /skills/{id}/preview`, `PUT /skills/{id}/manifest`, `PUT /skills/{id}/files/batch` plus a Code/Preview file manager and structured manifest dialog. A new `skill_hubs` table and `/skill-hubs` router provide 3 registries (2 offline built-in, 1 remote), cross-hub search over 13 skills, one-click install, Hub CRUD/sync and cached-index degradation. `mcp_skills.hub_id` records provenance.

## Consequences

### Positive

- One declaration per type; designers become schema-driven, so new types need no frontend branch.
- Runtime registration allows tenant-specific component/node types without a deployment.
- Agents and the UI share one RBAC boundary; an operator literally cannot see or invoke admin tools (55/55 admin vs 35/55 operator).
- Skills are governed independently and are discoverable/installable from offline or remote hubs.
- Registry figures are machine-verifiable from `/openapi.json`, `db.py::SCHEMA` and `TOOL_SPECS`.

### Negative / residual risks

- `settings`-backed custom specs are global, not tenant-scoped; a multi-tenant deployment would need a namespace column.
- `script` nodes use a restricted `eval` and assume trusted workflow authors.
- HTTP / webhook / skill node executors are simulated in the synchronous engine.
- Remote hub indexes are trusted JSON without package signature verification.
- 55 tools increase the MCP `tools/list` payload; permission filtering keeps it bounded per role.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Keep per-module constants and add adapter functions | Leaves five lists to drift; no single `config_schema` for designers |
| Plugin packages / entry points loaded from disk | Requires a deployment and process restart; violates the "runtime extension" goal |
| A separate agent-only admin API instead of tools | Agents would still be unable to act as the user; breaks ADR-0002's one-registry principle |
| Expose all 55 tools to every role | Violates RBAC; would leak settings, keys and audit data to operators |
| Hard-code a larger built-in skill catalog | No Hub management, no remote registries, no graceful degradation |
| Require `mcp:write` for Skills (status quo) | Keeps the two registries coupled and prevents independent role grants |

## Verification

- `GET /meta/registry` → 66 components, 24 nodes, `config_schema` on every spec, 6 node categories, `human_nodes = [approval, cc, human_input]`.
- `POST /meta/registry/components` → component appears in `/forms/meta`, passes form validation; `POST /meta/registry/nodes` → node appears in `/workflows/meta`; invalid code → 400; `DELETE` removes it.
- One `POST /workflows/{id}/run` executes 8 new node types with `status: completed` and full logs.
- `GET /agents/meta/runtime`: 55 tools for admin, `capabilities.total_tools = 55`, `available_tools = 55`; operator 35/55; `/mcp/tools` filtered identically.
- `GET /skill-hubs` → 3 hubs; `/skill-hubs/search?q=pdf` → `pdf-extract`; unreachable remote hub → `errors` populated, builtin results intact.
- Hub install → `mcp_skills` row with `hub_id`, preview renders Markdown, manifest edit persists to `manifest.json`, batch file save persists.
- `backend/tests/smoke.py`: **272 passed / 0 failed** (68 new v5 assertions). `ruff check app tests` clean; `pnpm typecheck`, `pnpm build`, i18n parity 929/929, and a 375px Playwright sweep over 14 routes with 0px horizontal overflow.
- Registry at this ADR: **149 OpenAPI paths / 192 route decorators / 30 tables / 21 indexes / 55 tools / 28 permissions / 929 i18n keys per locale / 272 smoke assertions**.
