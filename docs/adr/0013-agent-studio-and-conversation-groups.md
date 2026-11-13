# ADR-0013: Two-column agent studio, composer icon toolbar and per-agent conversation groups

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-13 |
| Deciders | Platform / frontend + AI agent engineering |
| Related | [AGS-001](../agent-studio-and-conversations.md), [API-001 §2.14](../api-reference.md), [ADR-0012](0012-extensible-registry-agent-coverage-and-skill-hubs.md), `pages/Agents.tsx`, `routers/agents.py` |

## Context

`pages/Agents.tsx` had grown into a three-column screen: a flat agent list, chat, and a 22rem right-hand tab panel holding `config`, `bindings`, `runtime`, `capabilities` and `tools`. Users had to leave the conversation to attach an MCP server, a skill or a knowledge base — the single most common configuration action — and the panel consumed a quarter of the width on laptops while being awkward on phones.

Conversations were already persisted in `conversations` (`agent_id`, `title`, `messages`, `user_id`, `created_at`) with GET/DELETE for a single row and a per-agent list endpoint, but the UI never rendered history, could not start a session before the first message, and had no way to clear a whole agent's history. Requirement: **"重构 agents 页面右侧区域对于 agent 的配置…转移到在聊天区域 input 上方放置一些 icon 配置 mcp skills knowledge 等，支持历史会话保留至相应 agent 的分组下，支持删除会话，清空 agent 下所有会话，添加新的会话"**.

Constraints: keep every existing capability (capability matrix, tool catalog, runtime info, agent settings, dynamic-form actions, deep links), keep mobile at 0px horizontal overflow, keep the offline demo working, and avoid breaking the existing REST contract.

## Decision

1. **Collapse to two columns.** `grid-cols-1 lg:grid-cols-[17rem_minmax(0,1fr)]`. The left column becomes a combined *Agents + sessions* tree: each agent is a collapsible group with its session count, a `+` new-session action and a clear-all action; sessions inside show title / message count / timestamp and a delete button. The right column is the chat, now full-width with a taller message area.
2. **Move all configuration to a composer icon toolbar.** Directly above the textarea, four binding icon buttons (MCP servers, Skills, Knowledge collections, Workflows) with selected-count badges open focused binding dialogs; four information icon buttons (Agent settings, Capability coverage, Tool catalog, Runtime info) open the views that used to live in the right tabs. The 22rem tab panel is deleted. Labels appear only from `xl:` so phones get a compact icon row.
3. **Make sessions first-class, grouped by agent.** Add `POST /agents/{agent_id}/conversations` (explicit empty session, 201) and `DELETE /agents/{agent_id}/conversations` (clear the group, agent intact). `POST /chat` titles an empty session from its first message and refuses to append to another user's row. Frontend operations: new (reusing an existing blank session), resume, delete one, clear all, delete agent (cascades), all behind one `ConfirmDialog` state machine.
4. **Enforce ownership consistently.** `_owns_conversation()` (owner / shared `NULL` / admin) and `_conv_visible_sql()` are shared by get/delete/list/clear; admins see and clear all rows of an agent, others only their own + shared. All mutations are audited. Add `idx_conversations_agent_user`.
5. **Keep the REST surface additive.** Both new methods attach to the already-existing `/api/v1/agents/{agent_id}/conversations` path, so the OpenAPI path count is unchanged; only decorator count grows. No existing endpoint changes shape.

## Consequences

### Positive

- The chat is the widest element on the page; attaching a resource is one click next to where you type.
- History is visible, grouped and fully manageable, with no orphan sessions: deleting an agent cascades, clearing a group preserves the agent.
- Capability coverage, tool catalog, runtime and settings remain reachable without a permanent side panel.
- Mobile layout is a simple stack; 14-route 375px sweep reports 0px overflow.
- Ownership is now checked on every conversation mutation (previously `chat()` would append to any existing `conversation_id`).

### Negative / residual risks

- `conversations.messages` is still a JSON blob; a long session is rewritten on every turn and the whole history is returned by the grouped list. A production system should split messages into their own table and paginate.
- Tool steps / citations are rendering-time only and are not replayed when a session is resumed.
- Empty rows can accumulate if a user repeatedly starts sessions without messaging; the frontend reuses one blank session per agent, but a periodic cleanup job is not implemented.
- Admins clear **all** users' sessions for an agent, which is intentional for the admin console but should be surfaced in the confirmation copy in a multi-tenant deployment.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Keep the right panel but add a "quick bindings" popover | Still duplicates configuration and keeps the narrow chat; requirement explicitly asked to move configuration to the composer |
| Put everything in one big settings drawer | Hides the frequently used bindings behind an extra click and loses the per-resource icon affordance |
| Client-side-only sessions (`localStorage`) | Would not satisfy "history kept under the agent" across devices/roles and would bypass `user_id` data scoping |
| Add a separate `/conversations` top-level router | Breaks the nested REST convention and duplicates permission/ownership logic |

## Verification

- `backend/tests/smoke.py`: **284 passed / 0 failed** (12 new v6 assertions: empty-session creation, grouping, chat reuse, first-message titling, single delete + 404, clear-all, agent survival, empty group, two non-owner denials).
- `ruff check app tests`, `python3 -m compileall -q app tests`, `pnpm typecheck`, `pnpm build` clean; i18n parity **950 / 950** (21 new `agents.*` keys per locale).
- Playwright: 14 routes at 375px → 0px horizontal overflow; 5 new screenshots (`agent-studio.png`, `agent-binding-dialog.png`, `agent-capabilities-dialog.png`, `agent-settings-dialog.png`, `mobile-agent-studio.png`).
- Live API probe: empty session 201 → chat reuses id and titles it → delete one → clear group → agent still 200 → non-owner delete 403.
- Registry at this ADR: **149 OpenAPI paths / 194 route decorators / 30 tables / 22 indexes / 55 tools / 28 permissions / 950 i18n keys / 284 smoke assertions / 33 screenshots**.
