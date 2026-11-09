"""Intent planning and schema-driven information collection for AI agents.

A user can ask "who am I and what can I do", "show my approvals and their
progress", or "help me create an expense claim".  This module turns those
requests into one of three plans:

* ``tool``    — run a self-scoped platform tool immediately (identity, approvals,
  submissions, instances) and render a grounded answer.
* ``collect`` — the request needs business data. Return a JSON field schema
  (derived from the bound form definition via ``form_rules.render_schema``) so
  the chat UI can render a dynamic form; nothing is written until the user
  submits it through ``POST /agents/{id}/actions``.
* ``chat``    — fall through to the normal ReAct tool loop / knowledge RAG.

The schemas are the very same ``FormField`` objects the form designer uses, so
validators, conditional rules, formulas and permissions stay single-sourced.
"""
from __future__ import annotations

import re

from .. import db, deps
from . import data_scope, flow_runtime, form_catalog, form_rules

# Field types a chat-side dynamic form can reasonably collect. Files/signatures
# and pure layout/computed fields are handled by the full form designer.
SKIP_TYPES = set(form_catalog.LAYOUT_TYPES) | {"serial", "signature", "image",
                                               "attachment", "ocr", "file", "divider"}

WORKFLOW_HINTS: list[tuple[str, str]] = [
    (r"报销|费用|expense|claim|reimburse", "expense_approval"),
    (r"请假|休假|leave|holiday|time off", "leave_approval"),
    (r"采购|购买|purchase|procure", "purchase_approval"),
]


def _zh(message: str) -> bool:
    return len(re.findall(r"[\u4e00-\u9fff]", message or "")) >= 2


def _workflow_form(row: dict) -> tuple[str | None, dict | None, list[dict]]:
    graph = (db.loads(row, "graph") or {}).get("graph") or {}
    start = next((n for n in (graph.get("nodes") or []) if n.get("type") == "start"), {})
    code = (start.get("config") or {}).get("form_code") or row.get("form_code")
    if not code:
        return None, None, []
    form = db.q1("SELECT * FROM forms WHERE code=?", (code,))
    if not form:
        return code, None, []
    return code, form, (db.loads(form, "schema") or {}).get("schema") or []


def _collect_fields(schema: list[dict]) -> list[dict]:
    out: list[dict] = []
    for f in schema:
        if f.get("type") in SKIP_TYPES or not f.get("key"):
            continue
        field = dict(f)
        if f.get("formula"):
            field["permission"] = "readonly"
            field["hint"] = "auto"  # computed by the rules engine on submit
        out.append(field)
    return out


def _startable() -> list[dict]:
    return [dict(r) for r in db.q(
        "SELECT id,code,name,description,status,form_code FROM workflows "
        "WHERE status='published' ORDER BY id")]


def _pick_workflow(message: str) -> dict | None:
    rows = _startable()
    if not rows:
        return None
    for pattern, code in WORKFLOW_HINTS:
        if re.search(pattern, message, re.I):
            hit = next((r for r in rows if r["code"] == code), None)
            if hit:
                return hit
    # Prefer a workflow with a bound form so a real dynamic form can be shown.
    return next((r for r in rows if r.get("form_code")), rows[0])


def _collect_plan(message: str, user: dict) -> dict | None:
    # Queries about existing data must never open a collection form.
    if re.search(r"(查询|查看|看看|有哪些|哪些|列表|进度|状态|我的|我发起的|我创建的|"
                 r"list|show|query|status|progress|which|my )", message, re.I):
        return None
    if not re.search(
        r"(帮我|为我|我想|我要|请|创建|发起|申请|提交|新建|开一个|create|start|launch|submit|file|apply)",
            message, re.I):
        return None
    if not re.search(r"(流程|审批|报销|请假|采购|单据|申请单|workflow|approval|claim|leave|request|process)",
                     message, re.I):
        return None
    wf = _pick_workflow(message)
    if not wf:
        return None
    _, form, schema = _workflow_form(wf)
    fields = _collect_fields(schema)
    zh = _zh(message)
    if form:
        title = f"填写「{form['name']}」并发起「{wf['name']}」" if zh else \
                f"Fill in {form['name']} to start {wf['name']}"
        desc = ("我已识别到你要发起该流程。请填写下面的表单，提交后我会立即创建审批实例并反馈进度。"
                if zh else
                "I identified the workflow you want to launch. Fill in the form below and I will "
                "create the approval instance and report its progress.")
    else:
        title = f"发起「{wf['name']}」" if zh else f"Start {wf['name']}"
        desc = ("该流程未绑定表单，填写备注后即可发起。" if zh else
                "This workflow has no bound form; add a remark and start it.")
        fields = [{"id": "note", "key": "note", "type": "textarea", "label": "备注 / Remark",
                   "width": 100, "required": False}]
    answer = (f"好的，{desc}" if zh else f"Sure. {desc}")
    return {
        "mode": "collect",
        "answer": answer,
        "action_request": {
            "id": "ar_" + db.uid()[:10],
            "kind": "start_workflow", "code": wf["code"],
            "workflow_id": wf["id"], "title": title, "description": desc,
            "schema": fields,
            "form_id": form["id"] if form else None,
            "form_code": form["code"] if form else None,
            "submit_label": "创建并发起" if zh else "Create & start",
            "endpoint": "actions",
        },
    }


_DIRECT_TOOLS: list[tuple[str, str]] = [
    (r"我是谁|我的身份|我的权限|我能做什么|我有哪些权限|我的角色|who am i|my identity|my permission|my role|what can i do",
     "who_am_i"),
    (r"我的审批|审批进度|我.*审批|待办|待我审批|my approval|approval progress|pending task|my task",
     "my_approvals"),
    (r"我发起|我创建|我的流程|我提交的流程|my workflow|my instance|my process",
     "my_instances"),
    (r"我的数据|我提交的单据|我的单据|我的提交|my submission|my record|my data",
     "my_submissions"),
    (r"可发起|能发起|有哪些流程|可以发起什么|startable|available workflow|which workflow",
     "list_startable_workflows"),
]


def _act_plan(message: str) -> dict | None:
    """Route approve / reject / withdraw / urge / notification requests."""
    m = message
    num = re.search(r"#(\d+)", m) or re.search(r"(?:实例|instance)\s*(\d+)", m, re.I)
    iid = int(num.group(1)) if num else None
    has_obj = bool(re.search(r"审批|待办|任务|申请|流程|approval|task|instance|workflow", m, re.I)) or iid is not None
    if re.search(r"同意|批准|通过|approve", m, re.I) and has_obj:
        args = {"action": "approve",
                "comment": "同意（AI 智能体代办）/ Approved via AI agent"}
        if iid:
            args["instance_id"] = iid
        return {"mode": "tool", "tool": "act_approval_task", "args": args}
    if re.search(r"驳回|拒绝|reject", m, re.I) and has_obj:
        args = {"action": "reject",
                "comment": m if len(m) < 60 else "驳回（AI 智能体代办）/ Rejected via AI agent"}
        if iid:
            args["instance_id"] = iid
        return {"mode": "tool", "tool": "act_approval_task", "args": args}
    if re.search(r"撤回|撤销|withdraw", m, re.I):
        args = {}
        if iid:
            args["instance_id"] = iid
        return {"mode": "tool", "tool": "withdraw_instance", "args": args}
    if re.search(r"催办|urge", m, re.I):
        args = {"message": m}
        if iid:
            args["instance_id"] = iid
        return {"mode": "tool", "tool": "urge_instance", "args": args}
    if re.search(r"我的.{0,2}通知|未读消息|通知中心|my notifications?", m, re.I):
        return {"mode": "tool", "tool": "my_notifications",
                "args": {"unread": bool(re.search(r"未读|unread", m, re.I))}}
    return None


def plan(message: str, user: dict, context: dict | None = None) -> dict:
    """Classify a chat message into collect / tool / chat."""
    ctx = context or {}
    if ctx.get("skip_intents"):
        return {"mode": "chat"}
    collect = _collect_plan(message, user)
    if collect:
        return collect
    act = _act_plan(message)
    if act:
        return act
    m = (message or "").lower()
    for pattern, tool in _DIRECT_TOOLS:
        if re.search(pattern, m, re.I):
            return {"mode": "tool", "tool": tool, "args": {}}
    return {"mode": "chat"}


def summarize_direct(tool: str, result: dict, message: str) -> str:
    """Render a grounded natural-language answer for a direct tool call."""
    zh = _zh(message)
    if result.get("error"):
        return (f"查询失败：{result['error']}" if zh else f"Query failed: {result['error']}")
    if tool == "who_am_i":
        u = result
        scope = u.get("data_scope") or {}
        if zh:
            return (f"你是 **{u.get('display_name') or u.get('username')}**（{u.get('username')}），"
                    f"部门：{u.get('dept') or '—'}，角色：{', '.join(u.get('roles') or []) or '—'}。\n\n"
                    f"数据范围：**{scope.get('role')}**（{scope.get('rule')}）。"
                    f"{'你是超级管理员，可读写全部数据。' if scope.get('is_super_admin') else ''}"
                    f"{'你是审计管理员，可只读查看审计类全部数据。' if scope.get('is_auditor') else ''}\n\n"
                    f"权限码 {len(u.get('permissions') or [])} 项；"
                    f"我的提交 {u.get('counts', {}).get('my_submissions', 0)} 条、"
                    f"我发起的流程 {u.get('counts', {}).get('my_instances', 0)} 个、"
                    f"待我审批 {u.get('counts', {}).get('pending_approvals', 0)} 项。")
        return (f"You are **{u.get('display_name') or u.get('username')}** "
                f"({u.get('username')}), dept {u.get('dept') or '—'}, "
                f"roles: {', '.join(u.get('roles') or []) or '—'}.\n\n"
                f"Data scope: **{scope.get('role')}** — {scope.get('rule')}.\n\n"
                f"{len(u.get('permissions') or [])} permission codes; "
                f"{u.get('counts', {}).get('my_submissions', 0)} submissions, "
                f"{u.get('counts', {}).get('my_instances', 0)} instances, "
                f"{u.get('counts', {}).get('pending_approvals', 0)} pending approvals.")
    if tool == "my_approvals":
        items = result.get("approvals") or []
        head = (f"你共有 {result.get('total', 0)} 项审批任务，其中待办 {result.get('pending', 0)} 项："
                if zh else f"You have {result.get('total', 0)} approval tasks, "
                           f"{result.get('pending', 0)} pending:")
        lines = []
        for t in items[:5]:
            lines.append(f"• #{t.get('id')} {t.get('node_name')} · {t.get('workflow_name') or t.get('workflow_code')} "
                         f"· 实例 #{t.get('instance_id')} {t.get('instance_status')} · {t.get('status')}"
                         + (f" · 发起人 {t.get('initiator')}" if t.get("initiator") else ""))
        return head + ("\n" + "\n".join(lines) if lines else ("\n（暂无）" if zh else "\n(none)"))
    if tool in {"my_instances", "my_submissions", "list_startable_workflows"}:
        key = "instances" if tool == "my_instances" else \
              "submissions" if tool == "my_submissions" else "workflows"
        items = result.get(key) or []
        label = {"instances": ("我发起的流程", "your launched workflows"),
                 "submissions": ("我提交的单据", "your submissions"),
                 "workflows": ("可发起的流程", "startable workflows")}[key]
        head = (f"{label[0]}共 {len(items)} 条：" if zh else f"{len(items)} {label[1]}:")
        lines = []
        for x in items[:8]:
            if key == "instances":
                lines.append(f"• #{x.get('id')} {x.get('workflow_name') or x.get('workflow_code')} · {x.get('status')} · {x.get('started_at')}")
            elif key == "submissions":
                lines.append(f"• #{x.get('id')} {x.get('form_name') or x.get('form_code')} · {x.get('status')} · {x.get('serial_no') or ''}")
            else:
                lines.append(f"• {x.get('name')} ({x.get('code')}) · {x.get('field_count', 0)} fields")
        return head + ("\n" + "\n".join(lines) if lines else ("\n（暂无）" if zh else "\n(none)"))
    if tool == "act_approval_task":
        status = result.get("instance_status")
        if zh:
            return (f"已完成 **{result.get('action')}**：实例 #{result.get('instance_id')} "
                    f"当前状态 **{status or '—'}**。"
                    + (f"待审批人：{', '.join(result.get('pending') or [])}。"
                       if result.get("pending") else ""))
        return (f"Done **{result.get('action')}** on instance #{result.get('instance_id')}; "
                f"status is now **{status or '—'}**."
                + (f" Pending approvers: {', '.join(result.get('pending') or [])}."
                   if result.get("pending") else ""))
    if tool == "withdraw_instance":
        return (f"实例 #{result.get('instance_id')} 已撤回（{result.get('instance_status')}）。" if zh
                else f"Instance #{result.get('instance_id')} withdrawn "
                     f"({result.get('instance_status')}).")
    if tool == "urge_instance":
        names = ", ".join(result.get("assignees") or [])
        return (f"已向 {result.get('urged', 0)} 位审批人发送催办：{names}。" if zh
                else f"Urged {result.get('urged', 0)} approvers: {names}.")
    if tool == "my_notifications":
        items = result.get("notifications") or []
        head = (f"你有 {result.get('unread', 0)} 条未读通知，最近 {len(items)} 条："
                if zh else f"You have {result.get('unread', 0)} unread notifications; "
                           f"latest {len(items)}:")
        lines = [f"• #{n.get('id')} [{n.get('event')}] {n.get('title')} "
                 f"{'(未读)' if not n.get('read_at') else ''}" for n in items[:8]]
        return head + ("\n" + "\n".join(lines) if lines else ("\n（暂无）" if zh else "\n(none)"))
    return (f"已查询：{tool} 返回 {len(result)} 个字段。" if zh else
            f"Query complete: {tool} returned {len(result)} fields.")


def execute(kind: str, code: str, data: dict, user: dict,
            agent: dict | None = None) -> dict:
    """Execute an action after the dynamic form has been submitted."""
    username = user["username"]
    zh = _zh(str(data.get("__message") or ""))
    if kind == "start_workflow":
        if not deps.has_permission(user, "workflow:run"):
            raise PermissionError("workflow:run permission required")
        if data_scope.read_only(user):
            raise PermissionError("The audit administrator role is read-only")
        row = db.q1("SELECT * FROM workflows WHERE code=?", (code,))
        if not row:
            raise ValueError(f"Workflow not found: {code}")
        if row["status"] != "published":
            raise ValueError("Only published workflows can be started")
        payload = {k: v for k, v in (data or {}).items() if not k.startswith("__")}
        view = flow_runtime.start_instance(row, payload, username)
        if view.get("form_code"):
            form = db.q1("SELECT * FROM forms WHERE code=?", (view["form_code"],))
            if form:
                schema = (db.loads(form, "schema") or {}).get("schema") or []
                checked = form_rules.validate_data(schema, view["form_data"],
                                                   form_id=form["id"], check_unique=False)
                db.insert("form_submissions", {
                    "form_id": form["id"], "data": view["form_data"],
                    "computed": checked["computed"], "status": "submitted",
                    "submitted_by": username, "form_version": form["version"],
                    "flow_instance_id": view["id"], "updated_at": db.now(),
                    "created_at": db.now()})
        deps.audit(username, "agent.action.start_workflow", f"workflow:{code}",
                   {"instance": view["id"], "agent": (agent or {}).get("code")})
        answer = (f"已创建「{row['name']}」审批实例 #{view['id']}，当前状态 {view['status']}，"
                  f"待办 {len(view.get('pending') or [])} 项。"
                  if zh else
                  f"Created {row['name']} approval instance #{view['id']} "
                  f"(status {view['status']}, {len(view.get('pending') or [])} pending tasks).")
        return {"ok": True, "kind": kind, "code": code, "instance_id": view["id"],
                "status": view["status"], "pending": view.get("pending") or [],
                "answer": answer}
    if kind == "submit_form":
        if not deps.has_permission(user, "form:submit"):
            raise PermissionError("form:submit permission required")
        if data_scope.read_only(user):
            raise PermissionError("The audit administrator role is read-only")
        form = db.q1("SELECT * FROM forms WHERE code=?", (code,))
        if not form:
            raise ValueError(f"Form not found: {code}")
        if form["status"] != "published":
            raise ValueError("Only published forms accept submissions")
        payload = {k: v for k, v in (data or {}).items() if not k.startswith("__")}
        schema = (db.loads(form, "schema") or {}).get("schema") or []
        checked = form_rules.validate_data(schema, payload, form_id=form["id"])
        if checked["errors"]:
            raise ValueError("; ".join(e["message"] for e in checked["errors"]))
        sid = db.insert("form_submissions", {
            "form_id": form["id"], "data": checked["data"], "computed": checked["computed"],
            "status": "submitted", "submitted_by": username,
            "form_version": form["version"], "updated_at": db.now(), "created_at": db.now()})
        deps.audit(username, "agent.action.submit_form", f"form:{code}", {"submission_id": sid})
        answer = (f"已提交「{form['name']}」，记录 #{sid}。" if zh else
                  f"Submitted {form['name']}, record #{sid}.")
        return {"ok": True, "kind": kind, "code": code, "submission_id": sid, "answer": answer}
    raise ValueError(f"Unsupported action kind: {kind}")


def identity(user: dict | None) -> dict:
    """Payload for the ``who_am_i`` platform tool."""
    u = user or {}
    username = u.get("username") or "anonymous"
    counts = {
        "my_submissions": int(db.scalar(
            "SELECT COUNT(*) FROM form_submissions WHERE submitted_by=?", (username,)) or 0),
        "my_instances": int(db.scalar(
            "SELECT COUNT(*) FROM workflow_instances WHERE started_by=?", (username,)) or 0),
        "pending_approvals": int(db.scalar(
            "SELECT COUNT(*) FROM flow_tasks WHERE status='pending' AND assignee=?",
            (username,)) or 0),
    }
    return {
        "username": username, "display_name": u.get("display_name"),
        "email": u.get("email"), "dept": u.get("dept"),
        "roles": u.get("role_codes") or [], "permissions": u.get("permissions") or [],
        "is_admin": bool(u.get("is_admin")), "is_auditor": bool(u.get("is_auditor")),
        "data_scope": data_scope.describe(u), "counts": counts,
    }
