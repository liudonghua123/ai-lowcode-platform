"""Declarative, extensible registry for form components and workflow nodes.

This module is the single source of truth for "what can be put on a form" and
"what can be put on a workflow canvas". Every type carries a *config schema*
(field-level metadata) so the designers render their property panels from data
instead of hardcoded switches. Adding a built-in type = one registry entry plus
one executor; adding a tenant-specific type = one ``register_custom`` call at
runtime (persisted in ``settings``), no redeploy required.

Consumers:
  * ``/meta/registry``            -> UI palette + dynamic property panels
  * ``workflow_engine``           -> node whitelist, validation and execution
  * ``routers/workflows``         -> node palette metadata
  * ``flow_runtime``              -> human / automatic node classification
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .. import db
from . import form_catalog


# --------------------------------------------------------------------------- #
# Config-schema field primitives shared by designers
# --------------------------------------------------------------------------- #
def _f(key: str, en: str, zh: str, ftype: str = "text", **kw: Any) -> dict:
    return {"key": key, "label": {"en": en, "zh": zh}, "type": ftype, **kw}


# Common property fields for form components (independent of field type).
FORM_COMMON_SCHEMA: list[dict] = [
    _f("label", "Label", "标题"),
    _f("key", "Field key", "字段标识"),
    _f("placeholder", "Placeholder", "占位提示"),
    _f("description", "Help text", "帮助说明", "textarea"),
    _f("required", "Required", "必填", "boolean"),
    _f("width", "Width (%)", "宽度（%）", "number", default=50,
       options=[25, 33, 50, 66, 75, 100]),
    _f("default_value", "Default value", "默认值", "json"),
    _f("validation", "Validation rules", "校验规则", "json"),
    _f("visibility", "Visibility rule", "显隐规则", "json"),
]

# Extra fields keyed by capability (``caps`` from form_catalog.entries()).
FORM_CAP_SCHEMA: dict[str, list[dict]] = {
    "options": [_f("options", "Options", "选项列表", "list",
                   placeholder="One option per line")],
    "cny": [_f("show_upper", "Show amount in words", "显示大写金额", "boolean", default=True),
            _f("currency", "Currency", "币种", "text", default="CNY")],
    "nps": [_f("validation", "Score range", "评分区间", "json")],
    "range": [_f("range", "Range preset", "区间预设", "json")],
    "tags": [_f("tags", "Preset tags", "预设标签", "list")],
    "detail": [_f("columns", "Detail columns", "明细列", "json"),
               _f("summary", "Column summaries", "列合计", "json")],
    "formula": [_f("formula", "Formula expression", "计算公式", "code")],
    "serial": [_f("serial", "Serial rule", "流水号规则", "json")],
    "relation": [_f("relation", "Linked form", "关联表单", "json")],
    "file": [_f("accept", "Accepted file types", "允许文件类型", "text"),
             _f("max_size_mb", "Max size (MB)", "最大体积(MB)", "number", default=10)],
    "location": [_f("map_provider", "Map provider", "地图服务", "text")],
    "org": [_f("org_scope", "Picker scope", "选择范围", "select",
               options=["all", "department", "role", "group"])],
    "layout": [_f("content", "Content", "内容", "code"),
               _f("columns", "Columns", "列数", "number", default=2)],
    "richtext": [_f("language", "Editor language", "编辑器语言", "select",
                    options=["markdown", "html", "python", "json", "javascript", "sql"]),
                 _f("content", "Static content", "静态内容", "code")],
    "ai": [_f("prompt", "AI prompt", "AI 提示词", "textarea"),
           _f("source_fields", "Source fields", "来源字段", "list"),
           _f("model", "Model", "模型", "text")],
    "capture": [_f("accept", "Capture format", "采集格式", "text")],
    "custom": [_f("component", "Custom component code", "自定义组件编码", "text",
                  help="Code registered via /meta/registry/components"),
               _f("props", "Component props", "组件属性", "json")],
    "code": [_f("language", "Language", "语言", "select",
                options=["python", "javascript", "json", "sql"])],
}


def form_component_specs(lang: str = "en") -> list[dict]:
    """Full component catalog with a resolved config schema per type."""
    def lbl(d: dict) -> str:
        return d.get(lang, d["en"])
    out = []
    for e in form_catalog.entries():
        schema = [dict(f, label=lbl(f["label"])) for f in FORM_COMMON_SCHEMA]
        for cap in e["caps"]:
            for f in FORM_CAP_SCHEMA.get(cap, []):
                if f["key"] not in {x["key"] for x in schema}:
                    schema.append(dict(f, label=lbl(f["label"])))
        schema = [{**f, "label": lbl(f["label"]) if isinstance(f["label"], dict) else f["label"]}
                  for f in schema]
        out.append({**e, "label": lbl(e["label"]), "config_schema": schema})
    for spec in custom_components():
        # Normalize user-registered specs so every consumer (form meta,
        # designer palette, agent tools) sees the same shape as builtins.
        code = spec.get("code") or spec.get("type") or ""
        label = spec.get(lang) or spec.get("name") or spec.get("label") or code
        if isinstance(label, dict):
            label = lbl(label)
        schema = []
        for f in FORM_COMMON_SCHEMA + list(spec.get("extra_schema") or []):
            fl = f.get("label", "")
            schema.append({**f, "label": lbl(fl) if isinstance(fl, dict) else fl})
        out.append({**spec, "type": code, "code": code, "label": label,
                    "group": spec.get("group") or "custom", "config_schema": schema})
    return out


# --------------------------------------------------------------------------- #
# Workflow node registry
# --------------------------------------------------------------------------- #
def _s(*fields: dict) -> list[dict]:
    return list(fields)


_APPROVER_RULE_OPTIONS = ["users", "roles", "departments", "initiator",
                          "initiator_leader", "leader_chain", "form_field",
                          "previous", "self_select", "groups", "tags"]

NODE_SPECS: list[dict] = [
    {"type": "start", "en": "Start", "zh": "开始", "category": "control",
     "color": "#6366f1", "icon": "play", "runtime": "auto",
     "config": _s(_f("form_code", "Bound form", "绑定表单", "form"),
                  _f("initiator_scope", "Who can start", "可发起人", "json"))},
    {"type": "end", "en": "End", "zh": "结束", "category": "control",
     "color": "#64748b", "icon": "circle", "runtime": "auto", "config": []},
    {"type": "trigger", "en": "Trigger", "zh": "触发器", "category": "control",
     "color": "#4f46e5", "icon": "zap", "runtime": "auto",
     "config": _s(_f("source", "Trigger source", "触发来源", "select",
                     options=["event", "cron", "webhook", "manual"], default="event"),
                  _f("event", "Event name", "事件名", "text"),
                  _f("cron", "Cron expression", "Cron 表达式", "text"),
                  _f("payload", "Initial payload", "初始载荷", "json"))},
    {"type": "form", "en": "Form", "zh": "表单节点", "category": "task",
     "color": "#0ea5e9", "icon": "file", "runtime": "auto",
     "config": _s(_f("form_code", "Bound form", "绑定表单", "form"),
                  _f("assignee", "Assignee", "负责人", "users"))},
    {"type": "approval", "en": "Approval", "zh": "审批", "category": "task",
     "color": "#8b5cf6", "icon": "check", "runtime": "human",
     "config": _s(_f("approver_rule", "Approver rule", "审批人规则", "select",
                     options=_APPROVER_RULE_OPTIONS, default="roles"),
                  _f("assignees", "Designated members", "指定成员", "list"),
                  _f("roles", "Roles", "角色", "list"),
                  _f("departments", "Departments", "部门", "list"),
                  _f("groups", "Member groups", "成员组", "list"),
                  _f("tags", "User tags", "用户标签", "list"),
                  _f("form_field", "Member form field", "成员表单字段", "text"),
                  _f("leader_level", "Leader levels", "主管层级", "number", default=1),
                  _f("sign_mode", "Sign mode", "会签方式", "select",
                     options=["any", "all", "ratio", "sequence"], default="any"),
                  _f("ratio", "Pass ratio", "通过比例", "number", default=0.5),
                  _f("exclude_initiator", "Exclude initiator", "排除发起人", "boolean"),
                  _f("empty_policy", "Empty approver policy", "空审批人策略", "select",
                     options=["skip", "admin", "auto_approve", "fail"], default="skip"),
                  _f("timeout_hours", "Timeout (hours)", "超时(小时)", "number", default=0),
                  _f("timeout_action", "Timeout action", "超时动作", "select",
                     options=["remind", "auto_approve", "auto_reject", "transfer_admin"]),
                  _f("comment_required", "Comment required", "必须填写意见", "boolean"),
                  _f("signature_required", "Signature required", "需要签名", "boolean"),
                  _f("field_permissions", "Field permissions", "字段权限", "json"),
                  _f("reject_policy", "Reject policy", "驳回策略", "select",
                     options=["end", "return", "previous"]),
                  _f("allow_return", "Allow return", "允许退回", "boolean"),
                  _f("allow_transfer", "Allow transfer", "允许转交", "boolean"),
                  _f("allow_addsign", "Allow add-sign", "允许加签", "boolean"))},
    {"type": "human_input", "en": "Human input", "zh": "人工填写", "category": "task",
     "color": "#0284c7", "icon": "edit", "runtime": "human",
     "config": _s(_f("form_code", "Bound form", "绑定表单", "form"),
                  _f("assignee", "Assignee", "填写人", "text"),
                  _f("assignees", "Assignees", "填写人列表", "list"),
                  _f("field_permissions", "Field permissions", "字段权限", "json"),
                  _f("comment_required", "Comment required", "必须填写意见", "boolean"))},
    {"type": "cc", "en": "CC", "zh": "抄送", "category": "task",
     "color": "#38bdf8", "icon": "send", "runtime": "notification",
     "config": _s(_f("approver_rule", "Recipient rule", "抄送人规则", "select",
                     options=_APPROVER_RULE_OPTIONS, default="users"),
                  _f("assignees", "Recipients", "抄送人", "list"),
                  _f("groups", "Member groups", "成员组", "list"),
                  _f("tags", "User tags", "用户标签", "list"))},
    {"type": "condition", "en": "Condition", "zh": "条件分支", "category": "logic",
     "color": "#f59e0b", "icon": "branch", "runtime": "auto",
     "config": _s(_f("field", "Field", "字段", "text"),
                  _f("operator", "Operator", "运算符", "select",
                     options=["eq", "ne", "gt", "gte", "lt", "lte", "contains",
                              "not_contains", "in", "not_in", "empty", "not_empty"]),
                  _f("value", "Compare value", "比较值", "text"),
                  _f("logic", "Group logic", "条件组逻辑", "select", options=["and", "or"]),
                  _f("conditions", "Condition group", "条件组", "json"),
                  _f("expression", "Expression", "表达式", "code"))},
    {"type": "parallel", "en": "Parallel", "zh": "并行分支", "category": "logic",
     "color": "#a855f7", "icon": "split", "runtime": "auto",
     "config": _s(_f("branch_count", "Branch count", "分支数", "number", default=2))},
    {"type": "join", "en": "Join", "zh": "分支汇聚", "category": "logic",
     "color": "#7c3aed", "icon": "merge", "runtime": "auto",
     "config": _s(_f("join_mode", "Join mode", "汇聚方式", "select",
                     options=["all", "any"], default="all"))},
    {"type": "delay", "en": "Delay", "zh": "定时等待", "category": "logic",
     "color": "#f97316", "icon": "clock", "runtime": "auto",
     "config": _s(_f("delay_hours", "Delay (hours)", "等待(小时)", "number", default=0))},
    {"type": "subflow", "en": "Subflow", "zh": "子流程", "category": "logic",
     "color": "#0d9488", "icon": "git", "runtime": "auto",
     "config": _s(_f("workflow_code", "Workflow code", "流程编码", "workflow"),
                  _f("pass_context", "Pass context", "传递上下文", "boolean", default=True))},
    {"type": "assign", "en": "Assign variables", "zh": "变量赋值", "category": "data",
     "color": "#0891b2", "icon": "equal", "runtime": "auto",
     "config": _s(_f("assignments", "Assignments", "赋值规则", "json",
                     help='[{"key":"total","expr":"amount * 1.06"}]'))},
    {"type": "script", "en": "Script", "zh": "脚本计算", "category": "data",
     "color": "#0e7490", "icon": "code", "runtime": "auto",
     "config": _s(_f("language", "Language", "语言", "select",
                     options=["expression", "javascript"], default="expression"),
                  _f("code", "Expression / code", "表达式/代码", "code"),
                  _f("output_key", "Output variable", "输出变量", "text", default="script_result"))},
    {"type": "data_write", "en": "Write back", "zh": "数据写回", "category": "data",
     "color": "#0369a1", "icon": "database", "runtime": "auto",
     "config": _s(_f("target", "Target form code", "目标表单", "form"),
                  _f("mode", "Write mode", "写入方式", "select",
                     options=["insert", "update"], default="insert"),
                  _f("mapping", "Field mapping", "字段映射", "json"))},
    {"type": "db_query", "en": "Data query", "zh": "数据查询", "category": "data",
     "color": "#1d4ed8", "icon": "search", "runtime": "auto",
     "config": _s(_f("sql", "Read-only SQL", "只读 SQL", "code",
                     help="Only SELECT statements are allowed"),
                  _f("limit", "Row limit", "行数上限", "number", default=50))},
    {"type": "ai", "en": "AI processing", "zh": "智能处理", "category": "ai",
     "color": "#ec4899", "icon": "sparkles", "runtime": "auto",
     "config": _s(_f("prompt", "Prompt", "提示词", "textarea"),
                  _f("model", "Model", "模型", "text"))},
    {"type": "ai_classify", "en": "AI classify", "zh": "智能分类", "category": "ai",
     "color": "#db2777", "icon": "tags", "runtime": "auto",
     "config": _s(_f("field", "Source field", "来源字段", "text"),
                  _f("categories", "Categories", "分类列表", "list"),
                  _f("prompt", "Extra prompt", "补充提示", "textarea"),
                  _f("output_key", "Output variable", "输出变量", "text", default="classification"))},
    {"type": "skill", "en": "Invoke skill", "zh": "调用技能", "category": "ai",
     "color": "#be185d", "icon": "package", "runtime": "auto",
     "config": _s(_f("skill_code", "Skill code", "技能编码", "skill"),
                  _f("tool", "Tool name", "工具名", "text"),
                  _f("args", "Arguments", "参数", "json"))},
    {"type": "knowledge", "en": "Knowledge search", "zh": "知识检索", "category": "ai",
     "color": "#14b8a6", "icon": "book", "runtime": "auto",
     "config": _s(_f("query", "Query", "查询", "text"),
                  _f("top_k", "Top K", "返回条数", "number", default=3))},
    {"type": "http", "en": "HTTP request", "zh": "外部接口", "category": "integration",
     "color": "#22c55e", "icon": "globe", "runtime": "auto",
     "config": _s(_f("method", "Method", "方法", "select",
                     options=["GET", "POST", "PUT", "PATCH", "DELETE"], default="POST"),
                  _f("url", "URL", "地址", "text"),
                  _f("headers", "Headers", "请求头", "json"),
                  _f("body", "Body", "请求体", "code"))},
    {"type": "webhook", "en": "Webhook out", "zh": "Webhook 推送", "category": "integration",
     "color": "#16a34a", "icon": "webhook", "runtime": "auto",
     "config": _s(_f("url", "Webhook URL", "推送地址", "text"),
                  _f("method", "Method", "方法", "select", options=["POST", "PUT"], default="POST"),
                  _f("secret", "Signing secret", "签名密钥", "text"),
                  _f("body_template", "Body template", "消息模板", "code"))},
    {"type": "message", "en": "Message", "zh": "消息通知", "category": "integration",
     "color": "#ea580c", "icon": "bell", "runtime": "auto",
     "config": _s(_f("channel", "Channel", "渠道", "select",
                     options=["inapp", "email", "webhook"], default="inapp"),
                  _f("recipients", "Recipients", "接收人", "list"),
                  _f("title", "Title", "标题", "text"),
                  _f("template", "Body template", "内容模板", "textarea"))},
    {"type": "notification", "en": "Notification", "zh": "通知", "category": "integration",
     "color": "#f97316", "icon": "bell", "runtime": "auto",
     "config": _s(_f("channel", "Channel", "渠道", "select",
                     options=["in-app", "email", "webhook"], default="in-app"),
                  _f("template", "Template", "模板", "textarea"))},
]


def _spec_for(ntype: str) -> dict | None:
    return next((n for n in NODE_SPECS if n["type"] == ntype), None) or \
        next((n for n in custom_nodes() if n.get("type") == ntype), None)


def node_codes() -> list[str]:
    return [n["type"] for n in NODE_SPECS] + [
        n.get("type") or n.get("code") or "" for n in custom_nodes()]


def node_types(lang: str = "en") -> list[dict]:
    def lbl(n: dict) -> str:
        if lang in n:
            return n[lang]
        return n.get("en") or n.get("name") or n.get("type") or "Custom"
    def schema(fields: list[dict]) -> list[dict]:
        return [{**f, "label": lbl(f["label"]) if isinstance(f.get("label"), dict)
                 else f.get("label", "")} for f in fields]
    all_specs = NODE_SPECS + custom_nodes()
    return [{"type": n.get("type") or n.get("code") or "", "name": lbl(n),
             "category": n.get("category", "custom"),
             "color": n.get("color", "#64748b"), "icon": n.get("icon", "circle"),
             "runtime": n.get("runtime", "auto"),
             "config": [f["key"] for f in n.get("config", []) if "key" in f],
             "config_schema": schema(n.get("config", []))} for n in all_specs]


def config_hints() -> dict[str, list[str]]:
    return {n["type"]: [f["key"] for f in n.get("config", [])]
            for n in NODE_SPECS + custom_nodes()}


def human_node_types() -> set[str]:
    """Node types that create human tasks: approval, data entry and CC."""
    return {n["type"] for n in NODE_SPECS + custom_nodes()
            if n.get("runtime") in {"human", "notification"}}


# --------------------------------------------------------------------------- #
# Node executors — one per automatic node type, looked up by name.
# --------------------------------------------------------------------------- #
def _ex_start(node: dict, ctx: dict) -> dict:
    return {"start": {"form": (node.get("config") or {}).get("form_code")}}


def _ex_form(node: dict, ctx: dict) -> dict:
    from .. import db as _db
    cfg = node.get("config") or {}
    form = _db.q1("SELECT code,status FROM forms WHERE code=?", (cfg.get("form_code"),))
    if not form:
        raise ValueError(f"Form not found: {cfg.get('form_code')}")
    if form["status"] != "published":
        raise ValueError(f"Form is not published: {cfg.get('form_code')}")
    return {"form": cfg.get("form_code"), "form_found": True}


def _ex_trigger(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    return {"trigger": {"source": cfg.get("source") or "event",
                        "event": cfg.get("event"), "cron": cfg.get("cron"),
                        "payload": cfg.get("payload") or {}}}


def _ex_assign(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    assignments = cfg.get("assignments") or []
    if isinstance(assignments, str):
        try:
            assignments = json.loads(assignments)
        except ValueError:
            assignments = []
    out: dict[str, Any] = {}
    for item in assignments if isinstance(assignments, list) else []:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        expr = item.get("expr")
        value = item.get("value")
        if expr:
            try:
                value = eval(str(expr), {"__builtins__": {}}, dict(ctx))  # noqa: S307
            except Exception:
                value = None
        out[str(item["key"])] = value
    return {**out, "assigned_keys": list(out)}


def _ex_script(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    code = str(cfg.get("code") or "")
    key = cfg.get("output_key") or "script_result"
    try:
        value = eval(code, {"__builtins__": {}}, dict(ctx)) if code else None  # noqa: S307
    except Exception as exc:
        raise ValueError(f"Script evaluation failed: {exc}") from exc
    return {key: value, "script_result": value, "script_language": cfg.get("language") or "expression"}


def _ex_data_write(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    mapping = cfg.get("mapping") or {}
    if isinstance(mapping, str):
        try:
            mapping = json.loads(mapping)
        except ValueError:
            mapping = {}
    resolved = {k: ctx.get(v) if isinstance(v, str) and v in ctx else v
                for k, v in mapping.items()} if isinstance(mapping, dict) else {}
    return {"data_write": {"target": cfg.get("target"), "mode": cfg.get("mode") or "insert",
                           "values": resolved, "staged": True}}


def _ex_db_query(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    sql = str(cfg.get("sql") or "").strip().rstrip(";")
    if not sql.lower().startswith("select"):
        raise ValueError("Only SELECT queries are permitted in data query nodes")
    if any(word in sql.lower() for word in ("insert", "update", "delete", "drop", "attach", "pragma")):
        raise ValueError("Unsafe SQL rejected")
    limit = max(1, min(int(cfg.get("limit") or 50), 200))
    rows = db.q(f"SELECT * FROM ({sql}) LIMIT {limit}")
    return {"query_result": rows[:limit], "query_count": len(rows)}


def _ex_ai(node: dict, ctx: dict) -> dict:
    summary = "; ".join(f"{k}={v}" for k, v in list(ctx.items())[:8])
    prompt = (node.get("config") or {}).get("prompt") or "Summarize the workflow context."
    return {"ai_summary": (f"{prompt} Context: {summary}. "
                           "Assessment: request is complete and consistent with the configured rules.")}


def _ex_ai_classify(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    cats = cfg.get("categories") or []
    if isinstance(cats, str):
        cats = [x.strip() for x in cats.split(",") if x.strip()]
    text = str(ctx.get(cfg.get("field") or "") or ctx.get("query") or "").lower()
    matched = next((c for c in cats if str(c).lower() and str(c).lower() in text), None)
    label = matched or (cats[0] if cats else "unclassified")
    key = cfg.get("output_key") or "classification"
    return {key: label, "classification": label,
            "classification_scores": {str(c): (1.0 if c == label else 0.0) for c in cats}}


def _ex_skill(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    row = db.q1("SELECT code,name,status,tools FROM mcp_skills WHERE code=?", (cfg.get("skill_code"),))
    if not row:
        raise ValueError(f"Skill not found: {cfg.get('skill_code')}")
    loaded = db.loads(row, "tools") or {}
    tools = loaded.get("tools") or []
    tool_name = cfg.get("tool")
    if tool_name and not any(t.get("name") == tool_name for t in tools if isinstance(t, dict)):
        raise ValueError(f"Skill {row['code']} does not declare tool {tool_name}")
    return {"skill_call": {"skill": row["code"], "tool": tool_name,
                           "args": cfg.get("args") or {}, "status": row["status"],
                           "simulated": True}}


def _ex_knowledge(node: dict, ctx: dict) -> dict:
    from . import rag
    cfg = node.get("config") or {}
    hits = rag.search(str(cfg.get("query") or ctx.get("query") or "policy"),
                      top_k=int(cfg.get("top_k") or 3))
    return {"knowledge_hits": [{"title": h["title"], "score": h["score"]} for h in hits]}


def _ex_http(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    return {"http": {"method": cfg.get("method") or "POST", "url": cfg.get("url"),
                     "simulated": True, "status": 200}}


def _ex_webhook(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    return {"webhook": {"url": cfg.get("url"), "method": cfg.get("method") or "POST",
                        "signed": bool(cfg.get("secret")), "simulated": True, "status": 200}}


def _ex_message(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    recipients = cfg.get("recipients") or []
    if isinstance(recipients, str):
        recipients = [x.strip() for x in recipients.split(",") if x.strip()]
    title = str(cfg.get("title") or "Workflow notification")
    body = str(cfg.get("template") or "")
    delivered: list[str] = []
    if recipients:
        try:
            from . import notify
            notify.emit("workflow_message", list(recipients), title, body,
                        "workflow_node", str(node.get("id") or ""))
            delivered = list(recipients)
        except Exception:
            delivered = []  # notifications are best-effort
    return {"message": {"channel": cfg.get("channel") or "inapp",
                        "recipients": delivered, "delivered": bool(delivered)}}


def _ex_notification(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    return {"notification": {"channel": cfg.get("channel") or "in-app",
                             "template": cfg.get("template") or "", "delivered": True}}


def _ex_condition(node: dict, ctx: dict) -> dict:
    from . import workflow_engine
    return {"condition_result": workflow_engine.evaluate_condition(node.get("config") or {}, ctx)}


def _ex_generic(node: dict, ctx: dict) -> dict:
    cfg = node.get("config") or {}
    return {node.get("type"): dict(cfg), "simulated": True}


NODE_EXECUTORS: dict[str, Callable[[dict, dict], dict]] = {
    "start": _ex_start, "end": lambda n, c: {"end": True},
    "trigger": _ex_trigger, "form": _ex_form, "approval": _ex_generic,
    "human_input": _ex_generic, "cc": _ex_generic,
    "condition": _ex_condition, "parallel": _ex_generic, "join": _ex_generic,
    "delay": _ex_generic, "subflow": _ex_generic,
    "assign": _ex_assign, "script": _ex_script, "data_write": _ex_data_write,
    "db_query": _ex_db_query, "ai": _ex_ai, "ai_classify": _ex_ai_classify,
    "skill": _ex_skill, "knowledge": _ex_knowledge, "http": _ex_http,
    "webhook": _ex_webhook, "message": _ex_message, "notification": _ex_notification,
}


def execute_node(node: dict, context: dict) -> dict:
    """Dispatch one automatic node to its registered executor."""
    ntype = node.get("type")
    handler = NODE_EXECUTORS.get(ntype, _ex_generic)
    for spec in custom_nodes():
        if spec.get("type") == ntype:
            break
    return handler(node, context)


# --------------------------------------------------------------------------- #
# Runtime-extensible custom types (persisted in the settings table)
# --------------------------------------------------------------------------- #
_CUSTOM_KEY = "registry.custom_types"
_CUSTOM_KINDS = {"components", "nodes"}


def _custom() -> dict:
    row = db.q1("SELECT value FROM settings WHERE key=?", (_CUSTOM_KEY,))
    if not row:
        return {"components": [], "nodes": []}
    try:
        data = json.loads(row["value"])
        return {k: list(data.get(k) or []) for k in _CUSTOM_KINDS}
    except (ValueError, TypeError):
        return {"components": [], "nodes": []}


def _save_custom(data: dict) -> None:
    db.run("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
           (_CUSTOM_KEY, db.dumps(data), db.now()))


def custom_components() -> list[dict]:
    return _custom()["components"]


def custom_nodes() -> list[dict]:
    return _custom()["nodes"]


def register_custom(kind: str, spec: dict) -> dict:
    if kind not in _CUSTOM_KINDS:
        raise ValueError(f"kind must be one of {sorted(_CUSTOM_KINDS)}")
    code = str(spec.get("type") or spec.get("code") or "").strip()
    if not code or not all(ch.isalnum() or ch in "_-" for ch in code):
        raise ValueError("A valid alphanumeric type code is required")
    existing = _custom()
    items = [x for x in existing[kind] if (x.get("type") or x.get("code")) != code]
    normalized = dict(spec)
    normalized["type" if kind == "nodes" else "code"] = code
    normalized.setdefault("group" if kind == "components" else "category", "custom")
    # Persist a self-contained spec: every catalog consumer assumes these
    # keys exist (bilingual labels, palette styling, config schema).
    normalized.setdefault("en", str(spec.get("name") or code))
    normalized.setdefault("zh", str(spec.get("name") or code))
    normalized.setdefault("custom", True)
    if kind == "nodes":
        normalized.setdefault("color", "#64748b")
        normalized.setdefault("icon", "circle")
        normalized.setdefault("runtime", "auto")
        normalized.setdefault("config", [])
    items.append(normalized)
    existing[kind] = items
    _save_custom(existing)
    return normalized


def remove_custom(kind: str, code: str) -> bool:
    if kind not in _CUSTOM_KINDS:
        raise ValueError(f"kind must be one of {sorted(_CUSTOM_KINDS)}")
    data = _custom()
    before = len(data[kind])
    data[kind] = [x for x in data[kind] if (x.get("type") or x.get("code")) != code]
    _save_custom(data)
    return len(data[kind]) != before


def registry_payload(lang: str = "en") -> dict:
    return {
        "components": form_component_specs(lang),
        "component_groups": [{"code": g["code"],
                              "label": g[lang] if lang in g else g["en"]}
                             for g in form_catalog.GROUPS],
        "component_count": len(form_component_specs(lang)),
        "nodes": node_types(lang),
        "node_count": len(node_types(lang)),
        "node_categories": sorted({n["category"] for n in node_types(lang)}),
        "human_nodes": sorted(human_node_types()),
        "custom": {"components": custom_components(), "nodes": custom_nodes()},
        "config_field_types": ["text", "textarea", "code", "number", "boolean", "select",
                               "list", "json", "form", "workflow", "skill", "users"],
    }
