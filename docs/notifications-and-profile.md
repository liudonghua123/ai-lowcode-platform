# Notifications, Personal Center and Multi-Source Approvers

| Field | Value |
| --- | --- |
| ID | `NPF-001` |
| Status | Accepted |
| Version | 1.0 |
| Applies to | v0.1.0+ (groups/tags approvers, notifications, personal center, full agent actions) |
| Related | `WFP-001` · `SEC-001` · `DAT-001` · `API-001` · `ADR-0009` · `ADR-0010` · `ADR-0011` |

> **中文摘要**：本轮补齐审批生命周期的「人的闭环」。审批人规则在个人/角色/部门/主管链等 9 种之上新增 **按成员组（`groups`）** 与 **按用户标签（`tags`）** 两种（共 11 种），`user_groups` 支持自由组建跨部门审批组。新增**通知中心**：`notifications` 站内收件箱 + 可配置的 Webhook / 邮件渠道，待办、结果、催办、抄送、超时、完结、撤回七类事件在流程运行时自动触发，用户可按「事件 × 渠道」配置偏好，非管理员看不到渠道凭据。新增**个人中心**（`/#/profile`）：资料与密码自助维护、待办/已办/进行中/提交/未读统计、所属组、委托规则一览与通知偏好表。智能体工具从 20 扩至 **24**：新增 `act_approval_task`（同意/驳回/退回/转交/加签，可自动选取第一条待办）、`withdraw_instance`、`urge_instance`、`my_notifications`，使智能体覆盖当前角色能做的查询、申请、审批、撤回、催办全部操作。内置工具清单同步进 `seed.BUILTIN_TOOLS` 与内置 MCP server。详见 [接口规范](api-reference.md)、[数据模型](data-model.md) 与 [ADR-0011](adr/0011-groups-tags-notifications-and-agent-actions.md)。

## 1. Why this change

The previous release closed the designer-side loop but left three people-side
gaps:

1. **Approver targeting was org-chart-only.** Real Chinese approval flows route
   through free-form pools — 财务审核组, VIP 客户经理标签 — that do not map
   cleanly to departments or roles.
2. **Nobody was told anything.** Tasks were created silently; an approver had
   to poll the portal, and there was no way to integrate IM/webhook bots.
3. **The agent could read but not act.** It could list approvals, yet a
   "同意我的待办" message fell back to generic chat.

## 2. Member groups and user tags

- `users.tags` (JSON array) holds free-form labels seeded idempotently
  (`manager`, `vip`, `finance`, `hr`, `audit` on demo users).
- New table `user_groups` (`code` unique, `members` JSON, `tags`, `enabled`)
  managed by CRUD endpoints under `/api/v1/rbac/groups` (`rbac:read` /
  `rbac:write`).
- `flow_runtime.resolve_assignees` gains two rules:
  - `groups` — union of enabled groups' `members`;
  - `tags` — every active user holding any configured tag.
- Both compose with `exclude_initiator`, sign modes, empty policies and
  delegation remapping like every other rule; `/workflows/meta` exposes them
  and the designer renders dedicated inputs.

## 3. Notification center

| Layer | Design |
| --- | --- |
| Inbox | `notifications` table, one row per recipient per event; unread counter drives the header bell |
| Channels | `inapp` (always on), `webhook` (HTTP POST, `X-AILP-Secret` header), `email` (SMTP `starttls`); credentials stored under settings key `notify_channels`, masked for non-admins |
| Events | `task_created`, `task_result`, `urged`, `cc`, `timeout`, `instance_completed`, `withdrawn` |
| Preferences | `notify_prefs.events` maps event → channels (`GET/PUT /notifications/prefs`); extra channels fire only when a recipient opted in |
| Reliability | `services/notify.emit()` never raises — a broken webhook/SMTP cannot fail an approval; failures are returned in the emit summary |

Wiring points in `flow_runtime`: task creation (`task_created` / `cc`), final
approval (`instance_completed`), rejection (`task_result`), urge, withdraw and
the timeout sweep.

## 4. Personal center

`GET /auth/me/overview` returns profile, pending/done task counters, running
instance counters, submission count, unread notifications, my groups,
delegation rules (outgoing + incoming) and the effective data scope.
`PUT /auth/me` updates display name / email only. The `/#/profile` page adds a
password change form, a notification-preferences matrix and all counters.
Management of delegation rules and MFA stays in their existing pages; the
overview links the data.

## 5. Agent full-capability tools

| Tool | Required | Optional | Permission | Writes |
| --- | --- | --- | --- | --- |
| `act_approval_task` | — | `action`, `instance_id`, `task_id`, `comment`, `assignee`, `return_to` | `workflow:run` | **yes** |
| `withdraw_instance` | — | `instance_id`, `reason` | `workflow:run` | **yes** |
| `urge_instance` | — | `instance_id`, `message` | `workflow:run` | **yes** |
| `my_notifications` | — | `unread`, `limit` | (self context) | no |

`act_approval_task` falls back to the caller's first pending task, so
"同意我的待办" works without IDs. Intent routing in `agent_intents.plan()`
recognises 同意/批准/通过, 驳回/拒绝, 撤回/撤销, 催办 and notification
phrases (with optional `#id`), and routes them as scoped tool calls. All three
mutating tools are in `WRITE_TOOLS` and blocked for the read-only auditor.

## 6. Verification

- `tests/smoke.py` adds 16 assertions: group CRUD, groups/tags rules in meta,
  seeded tags, a groups-rule instance resolving `{carol, diana}`, unread
  counter increments, prefs roundtrip, channel masking, personal overview,
  approve / notifications / withdraw intents — total **205 passed / 0 failed**.
- Registry growth: **134 OpenAPI paths / 174 route decorators / 29 tables /
  20 indexes / 24 tools / 824 i18n keys per locale**.
