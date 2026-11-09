# Domestic Form & Approval Capability Specification (FFC-001)

> 中文摘要：本文档描述面向中国企业与政务场景的表单与审批增强。表单侧从 14 种字段扩展到 **44 种**（身份证、统一社会信用代码、手机号、银行卡、金额大写、省市区、手写签名、明细表、组织架构选择器等），加入服务端法定校验、受限 AST 公式引擎、明细表行内计算与合计、条件显隐/条件必填、节点字段权限、版本快照、流水号、打印视图与 CSV 导出。流程侧从 9 种节点扩展到 **14 种**，新增人工审批运行时：9 类审批人规则（含部门主管与逐级主管）、或签/会签/比例/依次审批、并行分支与汇聚、抄送、驳回/退回/转交/加签/撤回/催办、超时策略、委托代理与节点字段权限。示例 `expense_claim` + `expense_approval` 覆盖一条完整的国内报销审批链路。

## 1. Starting point and gap analysis

The first release shipped a visual form designer and a synchronous DAG runner. It was enough for a demo, but not for the scenarios Chinese teams actually run:

| Domestic requirement | Before | Now |
| --- | --- | --- |
| Statutory identifiers (身份证 / 统一社会信用代码 / 银行卡) | none | `idcard` (GB 11643 checksum + birthday/gender/age), `uscc` (GB 32100 check character), `bankcard` (Luhn), `mobile`, `tel` |
| Amount in words (人民币大写) | none | `amount` field + `CNY_UPPER()` + automatic `{key}_upper` derivation |
| Detail tables / 子表单 | one `table` field, no computation | column formulas, row subtotals, `TABLE_SUM()`, configurable summaries |
| Formula / 数据联动 | none | restricted-AST evaluator with 19 whitelisted functions |
| Conditional display / 条件必填 | none | `visible_when` / `required_when` condition groups (AND/OR, 12 operators) |
| Field-level permission by approval node | none | `editable` / `readonly` / `hidden` per node, enforced server-side |
| Document number / 流水号 | none | `serial` field, `BX-20261108-0001` style, monotonic per form |
| Form version rollback | `version` integer only | `form_versions` snapshots + restore |
| Print / 套打 | none | structured print view with RMB-in-words and summaries |
| Countersign / 会签 | auto-approved stub | `any` / `all` / `ratio` / `sequence`, one task per assignee |
| Approver rules | single role string | 9 rules incl. department leader and multi-level leader chain |
| Parallel approval | single-path DAG | `parallel` + `join` (all/any), CC, subflow, delay |
| Human actions | none | approve / reject / return / transfer / add-sign / withdraw / urge |
| Timeouts & delegation | none | per-node `timeout_hours` + 4 policies; `flow_delegations` |
| In-flight definition changes | graph read live | instance pins a graph snapshot + workflow version |

## 2. Form subsystem

### 2.1 Field catalog

`backend/app/services/form_catalog.py` is the single source of truth for the designer palette, the validator and the renderer. **44 field types in 5 groups**:

| Group | Types |
| --- | --- |
| `basic` | `text`, `textarea`, `number`, `select`, `multiselect`, `radio`, `checkbox`, `switch`, `date`, `datetime`, `time`, `slider`, `rate`, `color`, `email`, `url` |
| `china` | `idcard`, `mobile`, `tel`, `bankcard`, `uscc`, `amount`, `region`, `cascader`, `signature`, `qrcode` |
| `org` | `user`, `multi_user`, `department`, `role` |
| `business` | `table`, `formula`, `serial`, `relation`, `attachment`, `image`, `location`, `richtext`, `ocr` |
| `layout` | `divider`, `description`, `grid`, `tabs`, `collapse` |

`GET /forms/meta?lang=en|zh` returns the localized catalog plus validators, operators, functions and permission modes. `GET /forms/regions` returns a GB/T 2260 administrative-division sample that can be replaced with a full dataset through form settings.

### 2.2 Validation engine

`backend/app/services/form_rules.py` implements a server-side pipeline in `validate_data()`:

1. **Display rules** — `visible_when` condition groups remove hidden keys from the stored payload.
2. **Node permissions** — `editable` / `readonly` / `hidden`; a `readonly` field cannot be changed while an approval node is active.
3. **Detail tables** — each row's `formula` columns are computed, then `summary` aggregations (`sum`, `avg`, `count`, `max`, `min`) are written as `{key}_{summaryKey}`.
4. **Computed fields** — `formula` / `serial` values, `{amount}_upper` RMB-in-words, `{idcard}_info` parsed identity metadata.
5. **Per-field checks** — required (plus `required_when`), built-in statutory validators, `min`/`max`/`precision`/`min_length`/`max_length`/`regex`/`unique`/`date_range`/`options`, numeric and date type checks, readonly enforcement.

`unique` queries `form_submissions` for an existing value; errors are returned as `{key, rule, message}` rather than a single 400 string.

### 2.3 Formula sandbox

`safe_eval()` parses the expression with `ast.parse(mode="eval")` and walks only a whitelist of nodes (`Constant`, `Name`, `BinOp`, `UnaryOp`, `BoolOp`, `Compare`, `IfExp`, `Call`, `List`, `Tuple`, `Dict`, `Subscript`). Calls are restricted to 19 pure functions: `SUM`, `AVG`, `MIN`, `MAX`, `ROUND`, `ABS`, `IF`, `CONCAT`, `LEN`, `CNY_UPPER`, `TABLE_SUM`, `COUNT`, `DATEDIFF`, `TODAY`, `NOW`, `NUMBER`, `INT`, `FLOAT`, `STR`. There is **no `eval`**, no attribute access and no builtins, so user-authored formulas cannot reach the filesystem or the interpreter.

Example from the shipped expense form: `total_amount` uses `TABLE_SUM("items", "subtotal")`; a detail column uses `qty * price`.

### 2.4 Versioning, numbers, print and export

| Capability | Endpoint | Notes |
| --- | --- | --- |
| Snapshots | `GET/POST /forms/{id}/versions` | auto-written on create, update, publish; `POST` with `version` restores |
| Live evaluate | `POST /forms/{id}/evaluate` | returns computed data, summaries, visible/hidden, permissions, errors |
| Pre-flight validate | `POST /forms/{id}/validate` | same engine, no persistence |
| Render | `GET /forms/{id}/render?platform=mobile` | single-column mobile layout, node field permissions |
| Submit | `POST /forms/{id}/submissions` | computes, validates, generates `serial_no`, stores `computed` |
| Print | `GET /forms/{id}/print/{sid}` | structured print view with RMB-in-words and detail summaries |
| Export | `GET /forms/{id}/submissions/export` | UTF-8 BOM CSV for Excel |
| Status | `PATCH /forms/{id}/submissions/{sid}` | `submitted` / `approved` / `rejected` / `archived` / `draft` |

## 3. Approval subsystem

### 3.1 Node palette

`backend/app/services/workflow_engine.py` now accepts **14 node types**: the original `start`, `end`, `form`, `condition`, `approval`, `ai`, `knowledge`, `http`, `notification`, plus `cc`, `parallel`, `join`, `delay`, `subflow`. `validate_graph()` additionally checks `join_mode` and `sign_mode` values, duplicate ids, missing edge endpoints, cycles and the single-start constraint.

### 3.2 Approver resolution

`backend/app/services/flow_runtime.py::resolve_assignees()` supports 9 rules:

| Rule | Meaning |
| --- | --- |
| `users` | explicitly designated members |
| `roles` / `departments` | resolve active users by role ids or `users.dept` (legacy `approver_role` still works) |
| `initiator` | the person who started the instance |
| `initiator_leader` | leader of the initiator's `org_units` department |
| `leader_chain` | walk up `parent_code` for N levels (逐级主管) |
| `form_field` | read a member picker value from the submitted form |
| `previous` | previous node's approver |
| `self_select` | approvers chosen by the initiator at start time |

Resolution de-duplicates, can exclude the initiator, applies active `flow_delegations`, and falls back according to `empty_policy` (`skip` / `admin` / `auto_approve` / `fail`).

### 3.3 Signing modes and parallel routing

- `any` (或签): one approval passes the node, remaining tasks become `skipped`.
- `all` (会签): every assignee must approve; any rejection terminates or returns per `reject_policy`.
- `ratio`: approval fraction ≥ configured ratio.
- `sequence` (依次审批): only the first assignee is activated; the next is chained on each approval.

`parallel` nodes enter every outgoing branch; `join` nodes count arrivals and continue on `all` (default) or `any`. `condition` nodes accept a condition group (`logic` + `conditions`) as well as the legacy single field/operator/value form.

### 3.4 Human task lifecycle

`flow_tasks` holds one row per assignee per node activation, with `round` for re-review after a return. Actions exposed by `POST /workflows/instances/{id}/tasks/{tid}/act`:

| Action | Effect |
| --- | --- |
| `approve` | records decision/comment/signature; may complete the node |
| `reject` | terminates (`terminate`) or returns to initiator (`return`) |
| `return` | reopens initiator / previous / named node, skips other pending tasks |
| `transfer` | closes the current task, creates one for the target user |
| `addsign_before` / `addsign_after` | inserts an extra approver into the same node |
| `withdraw` (instance) | initiator cancels a running instance |
| `urge` (instance) | logs a reminder to all pending assignees |

`comment_required` and `signature_required` are enforced server-side. `sweep_timeouts()` applies `remind` / `auto_approve` / `auto_reject` / `transfer_admin` to overdue tasks. Every action writes an audit log and an instance timeline entry.

### 3.5 Version pinning and field permissions

`start_instance()` snapshots the graph into `workflow_instances.graph` together with `workflow_version`, so later edits to the definition never change a running approval. `GET /workflows/instances/{id}/form-schema` merges the bound form schema with the active node's `field_permissions`, letting the UI render exactly the fields that node may edit.

## 4. Data model

Five new tables (26 total, 17 indexes):

| Table | Purpose |
| --- | --- |
| `form_versions` | form definition snapshots (schema, layout, print template, settings, note) |
| `workflow_versions` | workflow graph snapshots pinned by running instances |
| `flow_tasks` | per-assignee approval tasks with round, decision, comment, signature, due/acted timestamps |
| `flow_delegations` | principal → agent delegation with optional time window |
| `org_units` | minimal department hierarchy (`parent_code`, `level`, `leader`) for leader-chain rules |

Extended columns: `forms.print_template`, `forms.settings`; `form_submissions.form_version`, `serial_no`, `flow_instance_id`, `computed`, `updated_at`; `workflows.form_code`; `workflow_instances.graph`, `form_data`, `form_code`, `current_nodes`, `variables`, `workflow_version`. All are added by the idempotent `MIGRATIONS` map before `INDEX_SCHEMA` runs.

## 5. Reference example

`seed.ensure_domestic_examples()` provisions, on every startup:

- **`expense_claim`** (费用报销单): serial number, applicant/department/mobile/idcard, claim type, conditional `travel_region` / `bank_account` / `supplier_uscc`, a detail table with row formulas and a total, an `amount` field computed via `TABLE_SUM` with automatic RMB-in-words, `remark` with `required_when total_amount > 5000`, invoice image, handwritten signature, description block, mobile layout and print template.
- **`expense_approval`** (费用报销审批): start bound to the form → department-leader approval with `comment_required`, timeout, and readonly field permissions → OR condition group on amount/type → parallel branch with a two-person finance countersign (`all`) and a GM approval → `join(all)` → CC to HR → end.
- **`org_units`**: 6 units with parent links and leaders so leader-chain resolution is demonstrable.

The smoke suite starts this workflow, approves the leader task, verifies that three parallel tasks open, approves all of them, and asserts the instance reaches `approved` through the join and CC nodes.

## 6. Verification

| Check | Result |
| --- | --- |
| `python3 -m ruff check app tests` | All checks passed |
| `python3 tests/smoke.py` | **189 passed / 0 failed** (41 new domestic assertions) |
| `pnpm typecheck` / `pnpm check:i18n` / `pnpm build` | pass / 789 en ↔ 789 zh, 0 missing / pass |
| Runtime metadata | 126 OpenAPI paths, 161 route decorators, 26 tables, 17 indexes, 20 MCP tools |

## 7. Constraints and boundaries

- The synchronous `POST /workflows/{id}/run` remains a **dry-run simulator**; real human approval uses `/start` + `/instances/.../act`.
- `region` ships a compact GB/T 2260 subset; full data is expected through form settings or an organization service.
- `signature` / `attachment` / `image` store metadata (or a data URL) in the form payload; a production file-storage service is not bundled.
- `subflow` and `delay` are recorded and validated, but the runtime treats them as simulated steps.
- Delegation applies at task-creation time; existing pending tasks are not retroactively reassigned.

See also: [REST & MCP API Reference](api-reference.md), [Data Model](data-model.md), [ADR-0009](adr/0009-domestic-forms-and-approval-runtime.md), [AI Model Services](ai-models.md), [Knowledge Upload](knowledge-upload.md).
