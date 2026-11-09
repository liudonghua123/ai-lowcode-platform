# ADR-0010: Centralised data scopes, auth-gated workflow portal and schema-driven agent actions

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-02-18 |
| Deciders | Platform architecture |
| Related | `WFP-001` · `SEC-001` · `API-001` · `DAT-001` · `AI-001` · `ADR-0002` · `ADR-0006` · `ADR-0009` |

## Context

Before this change, row visibility was implicit. Any principal with a
resource-level read permission could list every `form_submissions`,
`workflow_instances`, `flow_tasks`, `conversations`, `audit_logs` and
`mcp_call_logs` row. RBAC was doing two jobs — guarding *operations* and
guarding *data* — and only the first was modelled. Three concrete problems
followed:

- An operator could read another employee's expense claim and its approval
  history.
- There was no way to give a compliance/audit role a broad read-only view
  without also granting write permissions.
- MCP tools, REST routers and dashboard stats each implemented their own (or no)
  filtering, so a fix in one place did not fix the others.

Independently, the workflow UX was designer-centric. Starting an approval meant
pasting a JSON object; binding a form to a workflow was a free-text code; there
was no self-service catalogue, no "my requests" view, and no stable URL another
system could link to. The AI agent, finally, could only answer or act
immediately — it had no way to say "I need these fields first" and collect them
through a structured form.

`ADR-0009` had already introduced a long-running approval runtime and a rich
form rule engine, which made a schema-driven launch form and a schema-driven
agent collection card cheap to build. The remaining decision was where the
authorization boundary should live.

## Decision

**1. One authorization module for data visibility.** Introduce
`services/data_scope.py` as the single source of truth, with four scopes
(`all`, `audit`, `self`, `anonymous`) and a declarative `OWNED_RESOURCES` map of
owner columns and audit-class membership. Every business query — REST router,
dashboard stat and MCP tool — must obtain its filter from
`owner_clause()` / `row_visible()`. Definition assets stay under RBAC permission
codes, not owner scoping, because users must be able to see the shared forms and
workflows they operate on.

**2. Add an audit administrator as data, not as a superuser.** Add the
`data:audit` permission, an `auditor` builtin role with only read-class
permissions, and an idempotent `ensure_security_upgrade()`. Enforce read-only in
three layers: `deps.require()` rejects non-read actions, `mcp_tools.call_tool()`
rejects `WRITE_TOOLS`, and each router still checks its permission. A 404 (not
403) is returned for invisible single rows to avoid enumeration.

**3. Replace the workflow home with a portal and make launch form-based.** Add
`/workflows/catalog`, `/workflows/mine/instances`, `/workflows/mine/stats`,
`/workflows/{id}/start-schema` and the public `/workflows/share-info/{code}`.
Extract a shared `SchemaForm` component so the designer's start dialog, the
portal launch dialog and the public share page all render the same backend
`FormField[]` schema and the same rule engine (`/forms/{id}/evaluate`). Remove
the raw JSON textarea and replace free-text `form_code` inputs with dropdowns.

**4. Make the share URL a two-phase, auth-gated page.** `/#/start/{code}` is a
public route. Phase 1 (anonymous) calls the public metadata endpoint and offers
a sign-in CTA to `/#/login?next=/start/{code}`; phase 2 (authenticated) loads
the schema and submits. A whitelisted `safeNext()` blocks open redirects, and
`sessionStorage` preserves `next` across real SSO reloads. `?data=` allows
trusted host systems to prefill fields. No business data is exposed before
authentication.

**5. Let the agent plan before it acts.** Add `services/agent_intents.py` with
`collect` / `tool` / `chat` modes. `collect` returns an `action_request`
containing a dynamic schema and creates nothing; the UI renders a `SchemaForm`
card and only `POST /agents/{id}/actions` performs the side effect. Add eight
self-scoped tools (`who_am_i`, `my_approvals`, `my_submissions`, `my_instances`,
`list_startable_workflows`, `get_form_schema`, `start_workflow_instance`,
`submit_form_data`), taking `TOOL_SPECS` from 12 to 20. Query wording is
intercepted before collection so "my workflows" is not read as "create one".

## Consequences

### Positive

- Data visibility is now auditable from one file instead of being spread across
  routers; the same rules apply to REST, MCP and agents.
- A compliance role gets broad read-only visibility without any write surface.
- One `FormField` schema drives four surfaces (designer, portal, share page,
  agent card), so validators, conditional rules and field permissions cannot
  drift apart.
- The share URL gives integrating systems a stable, authenticated entry point,
  and the `next` round trip works for password, passkey, MFA and SSO sign-in.
- The agent never creates an approval instance until a human confirms the
  collected data, and the collected values still pass server-side validation.

### Negative / residual risks

- Every new business query must remember to call `owner_clause()`; there is no
  ORM-level enforcement. A missed call silently leaks rows. Mitigation: smoke
  assertions exercise admin / operator / auditor against the same fixture.
- Owner scoping is a single column per resource. Multi-party sharing beyond the
  `flow_tasks` initiator exception would need an ACL table.
- `?data=` is unsigned base64. It is a convenience for trusted hosts only; all
  values are revalidated server-side on submit.
- The public share page shows metadata without auto-redirecting, which is
  friendlier for embedding but means an anonymous visitor must click once to
  sign in.
- Historical ADRs keep their verification figures as decision-time snapshots;
  current figures are **126 OpenAPI paths / 161 route decorators / 26 tables /
  17 indexes / 20 MCP tools / 789 i18n keys / 189 smoke assertions**.

## Verification

`ruff check app tests`, `tests/smoke.py` (189 passed / 0 failed),
`pnpm typecheck`, `pnpm check:i18n` (789/789), `pnpm build`, and the Markdown
link check all pass. New smoke assertions cover all three scopes, auditor
read-only denial, self-scope filtering on submissions / instances / tasks, all
portal endpoints, auth-gating of the start schema and share metadata, 20 tool
specs, identity / approvals intents, the `action_request` schema, and a
dynamic-form action that creates a real instance (withdrawn in teardown).
