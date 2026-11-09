# ADR-0009: Domestic form engine and human approval runtime

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Platform architecture
- **Related:** ADR-0002 (single tool registry), ADR-0004 (SQLite), ADR-0008 (MCP/Skills split)

## Context

The initial form designer exposed 14 field types and a single `required` flag; the workflow engine executed a DAG synchronously and auto-approved every approval node. Chinese enterprise and government scenarios require statutory identifier validation, RMB amount-in-words, detail tables with row formulas, conditional display, node-level field permissions, designated/leader/countersign approvers, parallel branches, reject/return/transfer/add-sign, timeouts and delegation. Users explicitly asked to "梳理当前支持的功能特性，增强表单、流程这块的功能以覆盖国内复杂场景需求".

## Decision

**1. Keep JSON-schema definitions; add a rules layer.** Form `schema` and workflow `graph` stay JSON columns. New services `form_catalog.py`, `form_rules.py` and `flow_runtime.py` interpret them; no per-field relational tables are introduced. This preserves lazy `ALTER TABLE` migration and keeps the designer payload stable.

**2. Server-side validation, not client-only.** All statutory checks, formulas, visibility, permissions and detail summaries run in `form_rules.validate_data()`. The designer's live preview calls `POST /forms/{id}/evaluate`, which uses the same function — no duplicated logic.

**3. A restricted AST instead of `eval`.** Formulas are parsed with `ast.parse(mode="eval")` and walked against a whitelist of node types and 19 pure functions. The legacy workflow `expression` field still uses constrained `eval` for backward compatibility, but new condition groups go through `form_rules.check_rule()`.

**4. Long-running instances with per-assignee tasks.** `flow_tasks` holds one row per person per node activation (with `round` for re-review). `POST /workflows/{id}/start` creates an instance pinned to a graph snapshot; actions on `/instances/{id}/tasks/{tid}/act` advance the DAG. The original synchronous `/run` remains as a dry-run simulator so existing tests and quick demos keep working.

**5. Reuse the existing RBAC surface.** New endpoints use `form:read` / `form:write` / `form:publish` / `form:submit` and `workflow:read` / `workflow:write` / `workflow:run`; no new permission codes were added. Every mutation writes an audit entry.

**6. Minimal organization graph.** `org_units` (code, name, parent_code, level, leader) is added instead of a full HR system, enough to resolve `initiator_leader` and `leader_chain`. `users.dept` remains the join key.

**7. Idempotent provisioning.** `seed.ensure_domestic_examples()` adds org units plus the `expense_claim` / `expense_approval` examples on every boot, so upgraded databases demonstrate the new features without touching existing user data.

## Consequences

**Positive**

- 44 field types / 5 groups, statutory validation, RMB-in-words, formula sandbox, detail summaries, conditional rules, field permissions, versions, serial numbers, print and CSV export.
- 14 node types, 9 approver rules, 4 signing modes, parallel + join, 8 human actions, timeouts and delegation.
- 41 new smoke assertions cover the full countersign → parallel → join → CC chain; total 189 passed / 0 failed at the time; 205 after [ADR-0011](0011-groups-tags-notifications-and-agent-actions.md).
- Frontend gets a real task center and node-configuration editor without a new route.

**Costs / risks**

- `flow_runtime._enter()` is recursive with a depth guard (60); very deep graphs should still be validated as DAGs.
- Instance state is spread across `workflow_instances` columns and `flow_tasks`; a future high-volume deployment would want a transactional task queue.
- `signature`, `image` and `attachment` store metadata in the payload, not blobs in object storage.
- `subflow` and `delay` are simulated steps; `region` ships a reduced administrative-division dataset.
- Documentation figures moved from 97 paths / 133 decorators / 21 tables / 10 indexes / 651 keys / 116 assertions to **126 / 161 / 26 / 17 / 789 / 189**, later grown by ADR-0010/0011 to **134 / 174 / 29 / 20 / 824 / 205**.

## Alternatives considered

| Option | Rejected because |
| --- | --- |
| External workflow engine (Temporal / Camunda) | breaks the zero-dependency, single-file SQLite deployment model |
| Storing computed values in dedicated columns | complicates migration; JSON `computed` column is sufficient and versionable |
| Client-side formula evaluation only | untrusted expressions and no server-side enforcement of readonly/unique rules |
| Rewriting `/run` as the human runtime | would break existing consumers and smoke tests; a separate `/start` is cleaner |

## Validation

- `python3 -m ruff check app tests` — clean
- `python3 tests/smoke.py` — 189 passed / 0 failed (205 after ADR-0011)
- `pnpm typecheck`, `pnpm check:i18n` (740/740), `pnpm build` — pass
- Browser verification of `/forms` (Rules tab, 5 palette groups) and `/workflows` (14 node types, task center) with zero console errors
- Quick Tunnel health: `form_field_types: 44`, `workflow_node_types: 14`, `org_units: 6`
