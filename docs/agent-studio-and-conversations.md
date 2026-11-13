# AGS-001 — Agent Studio & Conversation Groups

> 中文摘要：本文档描述 v6 智能体工作台重构。原来的三栏布局把智能体配置放在右侧 22rem 的标签页面板里，配置与对话割裂，且会话只是隐式持久化、无法按智能体分组管理。新设计改为**两栏**：左侧是按智能体分组、可折叠的会话历史；右侧是完整的聊天区。所有配置从右侧面板**转移到输入框上方的图标工具条**（MCP 服务 / 技能 / 知识库 / 流程 / 设置 / 能力覆盖 / 工具目录 / 运行时），点击后以弹窗编辑。会话支持新建、恢复、删除单个、清空某智能体下全部会话，删除智能体时级联清理。后端新增 `POST /agents/{id}/conversations` 与 `DELETE /agents/{id}/conversations`，首条消息自动为空会话命名，并按 `user_id` 做归属隔离。

## 1. Context

Before v6 (`pages/Agents.tsx`) the page used `grid-cols-[14rem_minmax(0,1fr)_22rem]`:

| Pane | Problem |
| --- | --- |
| Left (14rem) | Only a flat agent list plus one global "New chat" button; history was invisible |
| Center | Chat with a bare composer; configuration was far away on the right |
| Right (22rem) | Five tabs (`config` / `bindings` / `runtime` / `capabilities` / `tools`) — the most frequently used resource bindings required leaving the conversation, and the panel consumed a quarter of the width |

The backend already persisted `conversations` (`agent_id`, `title`, `messages` JSON, `user_id`, `created_at`) and exposed `GET /agents/conversations/{id}`, `DELETE /agents/conversations/{id}` and `GET /agents/{agent_id}/conversations`, but there was **no way to start an empty session** or **clear a whole agent group**, and the UI never listed or resumed history. A new session only appeared after the first message, so "keeping history under its agent" was impossible.

## 2. Layout decision

Two columns: `grid-cols-1 lg:grid-cols-[17rem_minmax(0,1fr)]`.

- **Left — Agents & sessions.** Each agent is a collapsible group header showing its session count. Header actions: `+` (new session) and `🗑` (clear all sessions, disabled when empty). Expanded groups list sessions newest-first with title, message count and timestamp; the active one is highlighted; a hover `×` deletes a single session. A sticky **New conversation** button at the bottom targets the selected agent. Lists are height-capped and scrollable (`max-h-[20rem]` mobile / `max-h-[42rem]` desktop).
- **Right — Chat.** Wider message area, header shows the agent, mode badge and the current session title, with `+` (new session) and `🗑` (delete current session) actions.
- The old right-hand tab panel is **removed**, not duplicated. Its four informational views are reachable from dialogs opened by the composer toolbar, so no capability was lost.

## 3. Composer icon toolbar

Directly above the textarea, a wrapping row of icon buttons:

| Group | Buttons | Action |
| --- | --- | --- |
| Bindings | `Server` MCP servers · `Package` Skills · `Database` Knowledge collections · `GitBranch` Workflows | Opens a **binding dialog** with a searchable checkbox list for that group, a `selected/total` counter and summary badges for all four groups; **Save** issues `PUT /agents/{id}` |
| Information | `Settings2` Agent settings · `ShieldCheck` Capability coverage · `Wrench` Tool catalog · `Cpu` Runtime info | Opens a read-only (or editable, for settings) dialog with the content previously in the right tabs |

Binding buttons show a numeric badge of currently attached resources and their label from `xl:` upward, so on phones the toolbar is a compact icon-only row. The right end of the row shows `N bound · attach hint`. Dialogs are `size="md"` (`lg` for settings/capabilities), scroll internally (`max-h-[60vh]`) and close on backdrop / Escape / Cancel. The settings dialog also hosts the **Delete agent** action behind a confirmation.

All confirmations (delete one session, clear a group, delete agent) go through a single `ConfirmDialog` driven by a discriminated `ConfirmState`, avoiding three near-identical dialogs.

## 4. Conversation lifecycle

| Operation | Frontend | Backend |
| --- | --- | --- |
| New session | `newSession(agentId?)` — reuses an existing empty session instead of piling up blank rows; otherwise creates one, refreshes the group and selects it | `POST /agents/{agent_id}/conversations` (`{"title": ""}`, 201) |
| First message | `send()` posts with `conversation_id`, then refreshes the group | `POST /agents/{agent_id}/chat` appends to the row and sets `title = message[:60]` when the title is still empty |
| Resume | `openSession()` fetches the full history and maps it into chat bubbles | `GET /agents/conversations/{id}` |
| Delete one | Confirm → refresh group → clear the composer if it was active | `DELETE /agents/conversations/{id}` → `{"ok": true, "deleted": 1}` |
| Clear group | Confirm → empty the group in state → reset the composer if it belongs to that agent | `DELETE /agents/{agent_id}/conversations` → `{"ok": true, "deleted": n}`; **the agent itself is untouched** |
| Delete agent | Confirm → remove agent + its group from state → reload | `DELETE /agents/{agent_id}` cascades `DELETE FROM conversations WHERE agent_id=?` |

Switching agents resets the composer to the welcome state (history stays visible in the left groups); deep links `/#/agents?agent=<code>` still work.

**Ownership.** `_owns_conversation()` allows the owner, shared rows (`user_id IS NULL`) and admins. `_conv_visible_sql()` makes admins see/clear all rows of an agent while ordinary users only see/clear their own + shared rows. `chat()` refuses to append to a conversation owned by somebody else and creates a fresh one instead. All three mutations write audit entries (`agent.conversation.create` / `.delete` / `.clear`).

**Storage.** `conversations` gains `idx_conversations_agent_user` for grouped listing. Messages remain a JSON array; the frontend re-fetches the whole session on resume, so tool steps and citations (which are not persisted) are intentionally not replayed as structured cards.

## 5. Mobile-first

The two-column grid collapses to one column below `lg:`; the toolbar wraps; labels are hidden under `xl:`; dialogs are `max-w-*` with internal scrolling. A 375px Playwright sweep over 14 routes produced **0px horizontal overflow** on every route, and the 390px studio capture shows the grouped list, chat and toolbar stacked without clipping.

## 6. API summary

| Methods | Path | Permission |
| --- | --- | --- |
| GET | `/agents/{agent_id}/conversations` | `agent:chat` |
| POST | `/agents/{agent_id}/conversations` | `agent:chat` |
| DELETE | `/agents/{agent_id}/conversations` | `agent:chat` |
| GET / DELETE | `/agents/conversations/{conversation_id}` | `agent:chat` |
| POST | `/agents/{agent_id}/chat`, `/actions` | `agent:chat` |

The two new methods attach to an **existing** OpenAPI path (`/api/v1/agents/{agent_id}/conversations`), so the path count stays at **149** while route decorators grow from 192 to **194**. See [API-001 §2.14](api-reference.md) and [ADR-0013](adr/0013-agent-studio-and-conversation-groups.md).

## 7. Verification

- `backend/tests/smoke.py`: **284 passed / 0 failed** — 12 new v6 assertions cover empty-session creation, grouping, reuse on chat, first-message titling, second-session deletion, 404 after delete, clear-all, agent survival, empty group afterwards, and two non-owner denials.
- `ruff check app tests`, `python3 -m compileall`, `pnpm typecheck`, `pnpm build` all pass; i18n parity **950 en / 950 zh, 0 missing** (21 new `agents.*` keys per locale).
- Playwright: 5 new captures — `agent-studio.png`, `agent-binding-dialog.png`, `agent-capabilities-dialog.png`, `agent-settings-dialog.png`, `mobile-agent-studio.png`; 14-route 375px overflow sweep clean.
- Registry after v6: **149 OpenAPI paths / 194 route decorators / 30 tables / 22 indexes / 55 tools / 28 permissions / 950 i18n keys / 284 smoke assertions / 33 screenshots**.
