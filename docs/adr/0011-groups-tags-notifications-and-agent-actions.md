# ADR-0011: Groups/Tags Approvers, Notification Hub, Personal Center and Agent Actions

- Status: Accepted
- Date: 2026-11-09
- Relates to: [ADR-0009](0009-domestic-forms-and-approval-runtime.md) (approval runtime),
  [ADR-0010](0010-data-scopes-portal-and-agent-actions.md) (data scopes, portal, agent intents)

## Context

After the portal and data-scope work the remaining gaps were people-centric:

- Approver rules covered the org chart (users, roles, departments, leaders,
  form fields, previous, self-select) but not free-form pools such as 财务审核组
  or label-based routing (VIP 客户经理).
- No notification path existed: tasks appeared silently and external systems
  (IM bots, email digests) had no hook.
- The agent could *query* approvals but not *act* on them — approve, reject,
  withdraw, urge were portal-only.
- Users had no single place to see their workload, groups, delegations or
  notification preferences.

## Decision

1. **Two new approver rules** in `flow_runtime.resolve_assignees`:
   `groups` (union of enabled `user_groups.members`) and `tags` (active users
   whose `users.tags` intersect the configured set). Both reuse the existing
   pipeline (dedupe → `exclude_initiator` → delegation remap → empty policy).
   `user_groups` gets full CRUD under `/rbac/groups`; `users.tags` is a JSON
   column with an idempotent demo seed.

2. **Notification hub** as a pure service (`services/notify.py`):
   - `notifications` inbox table + `notify_prefs` per-user event→channel map;
   - channels `inapp` (always), `webhook`, `email` configured in the
     `settings` table under `notify_channels`, masked for non-admins;
   - `emit()` is best-effort: any webhook/SMTP failure is captured in the
     return value and never propagates into the approval runtime;
   - events: `task_created`, `task_result`, `urged`, `cc`, `timeout`,
     `instance_completed`, `withdrawn`, emitted from the runtime's state
     transitions, not from the routers, so every entry path (REST, agent,
     timeout sweep) is covered.

3. **Personal center**: `GET /auth/me/overview` aggregates counters (pending /
   done tasks, running instances, submissions, unread, groups, delegations,
   data scope); `PUT /auth/me` self-edits display name and email only. The
   `/#/profile` page renders the overview, password change and the
   preferences matrix; delegation editing and MFA stay in their dedicated
   pages.

4. **Agent actions**: four tools (`act_approval_task`, `withdraw_instance`,
   `urge_instance`, `my_notifications`) grow `TOOL_SPECS` 20 → 24, mirroring
   `seed.BUILTIN_TOOLS` and the built-in MCP server declaration. Intent
   routing maps 同意/批准/驳回/拒绝/撤回/撤销/催办/notification phrases to
   scoped tool calls; `act_approval_task` defaults to the caller's first
   pending task. All three mutating tools join `WRITE_TOOLS` for the
   auditor read-only guard.

## Consequences

- Registry grew to **134 OpenAPI paths / 174 route decorators / 29 tables /
  20 indexes / 24 tools / 824 i18n keys / 205 smoke assertions**.
- Delegation interacts with group expansion: a delegated member resolves to
  the delegate (documented and covered by smoke assertions using
  non-delegated members).
- Webhook/email delivery is at-most-once and synchronous; a durable outbound
  queue can be layered on `notifications` without schema changes.
- Notification privacy: non-admins never receive channel credentials;
  notification rows are strictly per-recipient.

## Verification

`ruff check app tests`, `tests/smoke.py` (**205 passed / 0 failed**),
`pnpm typecheck`, `pnpm check:i18n` (824/824), `pnpm build`, Markdown link
check, plus live public-tunnel verification of the portal, bell and profile
page (0 console errors).
