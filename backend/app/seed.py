"""Deterministic bootstrap data: permissions, roles, users and demo assets."""
from __future__ import annotations

from . import db, security
from .config import settings
from .services import model_providers, skill_catalog

PERMISSIONS = [
    ("dashboard:view", "View dashboard", "dashboard", "view"),
    ("form:read", "Read forms", "form", "read"),
    ("form:write", "Create / edit forms", "form", "write"),
    ("form:delete", "Delete forms", "form", "delete"),
    ("form:publish", "Publish forms", "form", "publish"),
    ("form:submit", "Submit forms", "form", "submit"),
    ("workflow:read", "Read workflows", "workflow", "read"),
    ("workflow:write", "Create / edit workflows", "workflow", "write"),
    ("workflow:delete", "Delete workflows", "workflow", "delete"),
    ("workflow:run", "Run workflows", "workflow", "run"),
    ("knowledge:read", "Read knowledge base", "knowledge", "read"),
    ("knowledge:write", "Manage knowledge base", "knowledge", "write"),
    ("knowledge:delete", "Delete knowledge assets", "knowledge", "delete"),
    ("agent:read", "Read agents", "agent", "read"),
    ("agent:write", "Manage agents", "agent", "write"),
    ("agent:chat", "Chat with agents", "agent", "chat"),
    ("mcp:read", "Read MCP skills", "mcp", "read"),
    ("mcp:write", "Manage MCP skills", "mcp", "write"),
    ("mcp:invoke", "Invoke MCP tools", "mcp", "invoke"),
    ("rbac:read", "Read users & roles", "rbac", "read"),
    ("rbac:write", "Manage users & roles", "rbac", "write"),
    ("auth:config", "Configure authentication", "auth", "config"),
    ("audit:read", "Read audit logs", "audit", "read"),
    ("data:audit", "Read all audit-class data (auditor)", "data", "audit"),
    ("settings:read", "Read settings", "settings", "read"),
    ("settings:write", "Manage settings", "settings", "write"),
]

# Auditor: read-only role that can see every row of the audit-class resources.
AUDITOR_PERMISSIONS = [
    "dashboard:view", "form:read", "workflow:read", "knowledge:read",
    "agent:read", "mcp:read", "rbac:read", "audit:read", "settings:read",
    "data:audit",
]

FORMS = [
    {
        "code": "leave_request", "name": "Leave Request / 请假申请", "status": "published",
        "description": "Employee leave application with manager approval.",
        "schema": [
            {"id": "f1", "key": "applicant", "type": "user", "label": "Applicant / 申请人",
             "required": True, "width": 50, "placeholder": "Current user"},
            {"id": "f2", "key": "department", "type": "select", "label": "Department / 部门",
             "required": True, "width": 50, "options": ["Engineering", "Product", "Sales", "HR", "Finance"]},
            {"id": "f3", "key": "leave_type", "type": "select", "label": "Leave Type / 请假类型",
             "required": True, "width": 50, "options": ["Annual", "Sick", "Personal", "Unpaid"]},
            {"id": "f4", "key": "start_date", "type": "date", "label": "Start Date / 开始日期",
             "required": True, "width": 25},
            {"id": "f5", "key": "end_date", "type": "date", "label": "End Date / 结束日期",
             "required": True, "width": 25},
            {"id": "f6", "key": "days", "type": "number", "label": "Days / 天数",
             "required": True, "width": 50, "validation": {"min": 0.5, "max": 30}},
            {"id": "f7", "key": "reason", "type": "textarea", "label": "Reason / 事由",
             "required": True, "width": 100, "placeholder": "Please describe the reason"},
            {"id": "f8", "key": "urgent", "type": "switch", "label": "Urgent / 紧急",
             "required": False, "width": 50, "defaultValue": False},
        ],
        "layout": {"columns": 2, "labelWidth": 130, "size": "default"},
    },
    {
        "code": "purchase_request", "name": "Purchase Request / 采购申请", "status": "published",
        "description": "Procurement request with budget validation.",
        "schema": [
            {"id": "p1", "key": "item", "type": "text", "label": "Item / 采购物品", "required": True, "width": 50},
            {"id": "p2", "key": "category", "type": "select", "label": "Category / 类别", "required": True,
             "width": 50, "options": ["Hardware", "Software", "Service", "Office"]},
            {"id": "p3", "key": "quantity", "type": "number", "label": "Quantity / 数量", "required": True, "width": 50},
            {"id": "p4", "key": "budget", "type": "number", "label": "Budget (CNY) / 预算", "required": True, "width": 50},
            {"id": "p5", "key": "justification", "type": "textarea", "label": "Justification / 说明",
             "required": False, "width": 100},
        ],
        "layout": {"columns": 2, "labelWidth": 140, "size": "default"},
    },
    {
        "code": "customer_feedback", "name": "Customer Feedback / 客户反馈", "status": "draft",
        "description": "Collect and triage customer feedback.",
        "schema": [
            {"id": "c1", "key": "customer", "type": "text", "label": "Customer / 客户", "required": True, "width": 50},
            {"id": "c2", "key": "rating", "type": "select", "label": "Rating / 评分", "required": True,
             "width": 50, "options": ["1", "2", "3", "4", "5"]},
            {"id": "c3", "key": "content", "type": "textarea", "label": "Feedback / 反馈内容", "required": True, "width": 100},
        ],
        "layout": {"columns": 2, "labelWidth": 130, "size": "default"},
    },
]

LEAVE_GRAPH = {
    "nodes": [
        {"id": "n1", "type": "start", "name": "Start / 开始", "x": 80, "y": 200, "config": {}},
        {"id": "n2", "type": "form", "name": "Submit Leave / 提交请假单", "x": 260, "y": 200,
         "config": {"form_code": "leave_request", "assignee": "${initiator}"}},
        {"id": "n3", "type": "condition", "name": "Days > 3? / 天数判断", "x": 470, "y": 200,
         "config": {"expression": "days > 3", "field": "days", "operator": "gt", "value": 3}},
        {"id": "n4", "type": "approval", "name": "Manager / 部门经理", "x": 690, "y": 100,
         "config": {"approver_role": "operator", "mode": "any"}},
        {"id": "n5", "type": "approval", "name": "Director / 总监审批", "x": 690, "y": 300,
         "config": {"approver_role": "admin", "mode": "any"}},
        {"id": "n6", "type": "ai", "name": "AI Summary / 智能摘要", "x": 910, "y": 200,
         "config": {"prompt": "Summarize this leave request and assess its reasonableness."}},
        {"id": "n7", "type": "notification", "name": "Notify / 通知申请人", "x": 1120, "y": 200,
         "config": {"channel": "in-app", "template": "Your leave request has been processed."}},
        {"id": "n8", "type": "end", "name": "End / 结束", "x": 1320, "y": 200, "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "target": "n4", "label": "No / 否", "condition": "false"},
        {"id": "e4", "source": "n3", "target": "n5", "label": "Yes / 是", "condition": "true"},
        {"id": "e5", "source": "n4", "target": "n6"},
        {"id": "e6", "source": "n5", "target": "n6"},
        {"id": "e7", "source": "n6", "target": "n7"},
        {"id": "e8", "source": "n7", "target": "n8"},
    ],
}

PURCHASE_GRAPH = {
    "nodes": [
        {"id": "n1", "type": "start", "name": "Start", "x": 90, "y": 180, "config": {}},
        {"id": "n2", "type": "form", "name": "Purchase Form", "x": 290, "y": 180,
         "config": {"form_code": "purchase_request"}},
        {"id": "n3", "type": "condition", "name": "Budget > 10000", "x": 510, "y": 180,
         "config": {"field": "budget", "operator": "gt", "value": 10000}},
        {"id": "n4", "type": "approval", "name": "Finance", "x": 730, "y": 100, "config": {"approver_role": "admin"}},
        {"id": "n5", "type": "http", "name": "Sync ERP", "x": 730, "y": 280,
         "config": {"method": "POST", "url": "https://erp.example.com/api/orders"}},
        {"id": "n6", "type": "end", "name": "End", "x": 950, "y": 180, "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "target": "n4", "label": "Yes", "condition": "true"},
        {"id": "e4", "source": "n3", "target": "n5", "label": "No", "condition": "false"},
        {"id": "e5", "source": "n4", "target": "n6"},
        {"id": "e6", "source": "n5", "target": "n6"},
    ],
}

KB_DOCS = [
    ("platform-handbook", "Getting Started / 快速开始",
     "AI Low-Code Platform is an enterprise low-code platform. Users design forms with the drag-and-drop form designer, "
     "then orchestrate them into approval workflows on the visual canvas. Published forms can be submitted by operators. "
     "AI agents can query the knowledge base, run workflows and invoke MCP tools. 平台支持中英文界面、明暗主题、"
     "RBAC 权限控制，以及 CAS、OAuth2、OIDC、企业微信、钉钉等单点登录方式。"),
    ("platform-handbook", "Form Designer Guide / 表单设计指南",
     "The form designer supports text, number, select, date, textarea, switch, user picker and table fields. "
     "Each field has a unique key, label, width, required flag and validation rules. Forms have three statuses: "
     "draft, published and archived. Only published forms accept submissions. 表单发布后可被流程节点引用。"),
    ("platform-handbook", "Workflow Engine / 流程引擎",
     "A workflow is a directed acyclic graph (DAG) of nodes: start, end, form, condition, approval, ai, http, "
     "knowledge and notification. The engine topologically sorts nodes, evaluates conditions on outgoing edges "
     "and records every step in the instance log. 条件节点根据上下文数据选择分支，审批节点按角色分配审批人。"),
    ("platform-handbook", "Authentication & MFA / 认证与多因子",
     "Authentication supports local accounts plus CAS, OAuth2, OIDC, WeCom and DingTalk SSO. Multi-factor "
     "authentication can be enforced globally, per role or per user. Available factors are TOTP OTP and "
     "WebAuthn passkeys. 管理员可在认证设置中按角色或用户强制启用二次验证。"),
    ("policies", "Leave Policy / 请假制度",
     "Annual leave: employees with 1-5 years of service receive 10 days per year, 5-10 years receive 15 days, "
     "over 10 years receive 20 days. Leave of more than 3 consecutive days requires director approval. "
     "Sick leave requires a medical certificate for more than 2 days. 请假超过 3 天需总监审批，"
     "事假每年累计不得超过 15 天。"),
    ("policies", "Procurement Policy / 采购制度",
     "Purchases below CNY 10,000 require manager approval. Purchases of CNY 10,000 or more additionally require "
     "Finance approval and an ERP purchase order. All procurement must include three competitive quotations. "
     "采购金额超过一万元需财务审批并同步 ERP。"),
]

AGENTS = [
    {
        "code": "query_assistant", "name": "Knowledge Query Assistant / 知识查询助手",
        "mode": "query", "model": settings.llm_model,
        "description": "Answers questions grounded in the platform knowledge base (RAG).",
        "system_prompt": "You are a precise enterprise knowledge assistant. Answer strictly from the provided "
                         "context. Cite the source document titles. If the context is insufficient, say so.",
        "kb_ids": [1, 2], "skill_ids": [], "server_ids": [], "workflow_ids": [], "temperature": 0.2,
    },
    {
        "code": "ops_agent", "name": "Operations Agent / 流程操作智能体",
        "mode": "act", "model": settings.llm_model,
        "description": "Executes platform actions: submit forms, run workflows, query records, invoke MCP tools.",
        "system_prompt": "You are an operations agent. Translate the user's intent into platform tool calls. "
                         "Always confirm before destructive actions and report the tool result.",
        "kb_ids": [], "skill_ids": [2], "server_ids": [1], "workflow_ids": [1], "temperature": 0.1,
    },
    {
        "code": "general_copilot", "name": "AI Copilot / 全能助手",
        "mode": "hybrid", "model": settings.llm_model,
        "description": "Hybrid agent that retrieves knowledge and performs actions in one conversation.",
        "system_prompt": "You are the platform copilot. Retrieve relevant knowledge first, then decide whether "
                         "an action (form submission, workflow run, record query) is needed.",
        "kb_ids": [1, 2], "skill_ids": [1, 3], "server_ids": [1, 2],
        "workflow_ids": [1, 2], "temperature": 0.3,
    },
]

# The built-in server declares every platform tool so agent bindings can be
# expressed as a plain list of server ids.
BUILTIN_TOOLS = [
    {"name": "list_forms", "description": "List all form definitions"},
    {"name": "get_form", "description": "Get one form definition by code"},
    {"name": "submit_form", "description": "Submit data to a published form"},
    {"name": "query_records", "description": "Query form submissions"},
    {"name": "list_workflows", "description": "List workflow definitions"},
    {"name": "get_workflow", "description": "Get one workflow graph"},
    {"name": "run_workflow", "description": "Start a workflow instance"},
    {"name": "get_workflow_instance", "description": "Get a workflow instance"},
    {"name": "list_collections", "description": "List knowledge collections"},
    {"name": "search_knowledge", "description": "Search the knowledge base"},
    {"name": "list_users", "description": "List platform users"},
    {"name": "get_stats", "description": "Platform dashboard statistics"},
    {"name": "who_am_i", "description": "My identity, roles, permissions and data scope"},
    {"name": "my_approvals", "description": "My approval tasks and their progress"},
    {"name": "my_submissions", "description": "Form submissions I created"},
    {"name": "my_instances", "description": "Approval instances I started"},
    {"name": "list_startable_workflows", "description": "Published workflows with a start form"},
    {"name": "get_form_schema", "description": "Rendered schema for a dynamic collection form"},
    {"name": "start_workflow_instance", "description": "Start an approval instance from form data"},
    {"name": "submit_form_data", "description": "Submit collected data to a published form"},
]

PROVIDERS = [
    ("cas", "cas", "CAS / 中央认证服务", 1, {"server_url": "", "version": "3", "login_url": "", "validate_url": ""}),
    ("oauth2", "oauth2", "OAuth 2.0", 2, {"client_id": "", "client_secret": "", "authorize_url": "",
                                          "token_url": "", "userinfo_url": "", "scope": "openid profile email"}),
    ("oidc", "oidc", "OpenID Connect", 3, {"issuer": "", "discovery_url": "", "client_id": "",
                                           "client_secret": "", "scope": "openid profile email"}),
    ("wecom", "wecom", "WeCom / 企业微信", 4, {"corp_id": "", "agent_id": "", "secret": ""}),
    ("dingtalk", "dingtalk", "DingTalk / 钉钉", 5, {"app_key": "", "app_secret": ""}),
]


MCP_SERVERS = [
    {"code": "platform-builtin", "name": "Platform Built-in Tools / 平台内置工具",
     "description": "The platform's own /mcp endpoint and its 20 registered tools.",
     "transport": "builtin", "endpoint": f"{settings.public_base_url}/mcp", "enabled": 1,
     "health": "healthy", "tools": BUILTIN_TOOLS, "status": "active", "source": "builtin"},
    {"code": "thirdparty-http", "name": "Third-party HTTP MCP / 第三方 HTTP 示例",
     "description": "Example streamable-HTTP MCP server. Set an endpoint and sync to discover tools.",
     "transport": "http", "endpoint": "http://127.0.0.1:9100/mcp",
     "enabled": 0, "health": "unknown", "tools": [], "status": "active", "source": "manual"},
    {"code": "thirdparty-stdio", "name": "Local stdio MCP / 本地命令示例",
     "description": "Example stdio MCP server launched by a host-side command.",
     "transport": "stdio",
     "command": "npx -y @modelcontextprotocol/server-filesystem ./data",
     "enabled": 0, "health": "manual", "tools": [], "status": "active", "source": "manual"},
]


def ensure_security_upgrade(now: str | None = None) -> dict:
    """Idempotently add the data-scope permission, auditor role and demo user.

    Databases created before ADR-0010 are upgraded in place on every boot;
    existing rows (including user-edited role permissions) are never touched.
    """
    now = now or db.now()
    created = {"permission": 0, "role": 0, "user": 0}
    if not db.q1("SELECT id FROM permissions WHERE code=?", ("data:audit",)):
        db.insert("permissions", {"code": "data:audit",
                                  "name": "Read all audit-class data (auditor)",
                                  "resource": "data", "action": "audit",
                                  "description": "data / audit"})
        created["permission"] += 1
    if not db.q1("SELECT id FROM roles WHERE code=?", ("auditor",)):
        perm_map = {p["code"]: p["id"] for p in db.q("SELECT id,code FROM permissions")}
        db.insert("roles", {"code": "auditor", "name": "Audit Administrator / 审计管理员",
                            "description": "Read-only visibility of all audit-class data "
                                           "(submissions, instances, tasks, logs)",
                            "permission_ids": [perm_map[c] for c in AUDITOR_PERMISSIONS
                                               if c in perm_map],
                            "builtin": 1, "mfa_required": 0, "created_at": now})
        created["role"] += 1
    role = db.q1("SELECT id FROM roles WHERE code=?", ("auditor",))
    if role and not db.q1("SELECT id FROM users WHERE username=?", ("diana",)):
        db.insert("users", {"username": "diana", "email": "diana@platform.local",
                            "display_name": "Diana Zhao / 赵敏",
                            "password_hash": security.hash_password("demo1234"),
                            "status": "active", "dept": "Audit",
                            "role_ids": [role["id"]], "provider": "local",
                            "created_at": now, "updated_at": now})
        created["user"] += 1
    return created


def ensure_registries(now: str | None = None) -> dict:
    """Idempotently provision the three independent registries.

    Called on every startup so databases created before MCP / Skills were split
    (or before model providers existed) are upgraded in place, without touching
    user data. Returns a small summary for the boot log.
    """
    now = now or db.now()
    created = {"servers": 0, "skills": 0, "providers": 0}
    for srv in MCP_SERVERS:
        if db.q1("SELECT id FROM mcp_servers WHERE code=?", (srv["code"],)):
            continue
        db.insert("mcp_servers", {**srv, "auth_config": {}, "last_sync_at": now,
                                  "created_by": "admin", "created_at": now, "updated_at": now})
        created["servers"] += 1
    # Keep the built-in server's declared tool list in sync with the registry
    # on databases created before the self-service tools were added.
    builtin = db.q1("SELECT * FROM mcp_servers WHERE code=?", ("platform-builtin",))
    if builtin:
        declared = (db.loads(builtin, "tools") or {}).get("tools") or []
        known = {t.get("name") for t in declared if isinstance(t, dict)}
        missing = [t for t in BUILTIN_TOOLS if t["name"] not in known]
        if missing:
            db.update("mcp_servers", builtin["id"],
                      {"tools": declared + missing, "updated_at": now})
            created["tools_added"] = len(missing)
    server_map = {r["code"]: r["id"] for r in db.q("SELECT id,code FROM mcp_servers")}
    for spec in skill_catalog.CATALOG_SPECS:
        if db.q1("SELECT id FROM mcp_skills WHERE code=?", (spec["code"],)):
            continue
        linked = "thirdparty-http" if spec["type"] == "http" else "thirdparty-stdio"
        tools = [{"name": t["name"], "description": t["description"],
                  "inputSchema": {"type": "object", "properties": {}}} for t in spec["tools"]]
        db.insert("mcp_skills", {
            "code": spec["code"], "name": spec["name"], "type": spec["type"],
            "endpoint": spec.get("endpoint"), "command": spec.get("command"),
            "enabled": 1, "auth_config": {}, "tools": tools,
            "health": "unknown", "status": "installed", "version": spec["version"],
            "source": "catalog", "description": spec["description"],
            "manifest": {"schema": "ailp.mcp.skill/1", "capabilities": spec["capabilities"]},
            "server_id": server_map.get(linked), "installed_at": now,
            "created_at": now, "updated_at": now,
        })
        created["skills"] += 1
    for provider in model_providers.SEED_ROWS:
        if db.q1("SELECT id FROM ai_providers WHERE code=?", (provider["code"],)):
            continue
        db.insert("ai_providers", {**provider, "api_key": "", "config": {},
                                   "created_at": now, "updated_at": now})
        created["providers"] += 1
    # ``.env`` supplies the initial value of every model-service category;
    # rows edited from the UI are left untouched.
    boot = model_providers.bootstrap_from_env(now)
    created["providers"] += boot["created"]
    created["env_refreshed"] = boot["refreshed"]
    created["domestic"] = ensure_domestic_examples(now)
    created["security"] = ensure_security_upgrade(now)
    return created


def seed_if_empty() -> bool:
    if not db.is_empty():
        return False
    now = db.now()

    for code, name, resource, action in PERMISSIONS:
        db.insert("permissions", {"code": code, "name": name, "resource": resource,
                                 "action": action, "description": f"{resource} / {action}"})
    perm_map = {p["code"]: p["id"] for p in db.q("SELECT id,code FROM permissions")}

    def ids(*codes: str) -> list[int]:
        return [perm_map[c] for c in codes if c in perm_map]

    roles = [
        ("admin", "Administrator / 超级管理员", "Full platform access", ids("*") or list(perm_map.values()), 1, 0),
        ("developer", "Developer / 开发者", "Build forms, workflows, agents and skills",
         ids("dashboard:view", "form:read", "form:write", "form:publish", "workflow:read", "workflow:write",
             "workflow:run", "knowledge:read", "knowledge:write", "agent:read", "agent:write", "agent:chat",
             "mcp:read", "mcp:write", "mcp:invoke"), 1, 0),
        ("operator", "Operator / 运营人员", "Submit forms, run workflows, chat with agents",
         ids("dashboard:view", "form:read", "form:submit", "workflow:read", "workflow:run",
             "knowledge:read", "agent:read", "agent:chat", "mcp:read", "mcp:invoke"), 1, 0),
        ("viewer", "Viewer / 只读用户", "Read-only access to platform assets",
         ids("dashboard:view", "form:read", "workflow:read", "knowledge:read", "agent:read",
             "mcp:read", "rbac:read", "audit:read"), 1, 0),
        ("auditor", "Audit Administrator / 审计管理员",
         "Read-only visibility of all audit-class data (submissions, instances, tasks, logs)",
         ids(*AUDITOR_PERMISSIONS), 1, 0),
    ]
    for code, name, desc, pids, builtin, mfa in roles:
        db.insert("roles", {"code": code, "name": name, "description": desc,
                            "permission_ids": pids, "builtin": builtin, "mfa_required": mfa,
                            "created_at": now})
    role_map = {r["code"]: r["id"] for r in db.q("SELECT id,code FROM roles")}

    demo_pw = security.hash_password("demo1234")
    users = [
        (settings.bootstrap_admin, settings.bootstrap_admin_email, "Platform Admin / 平台管理员",
         security.hash_password(settings.bootstrap_admin_password), [role_map["admin"]], "IT"),
        ("alice", "alice@platform.local", "Alice Chen / 陈静", demo_pw, [role_map["developer"]], "Engineering"),
        ("bob", "bob@platform.local", "Bob Li / 李博", demo_pw, [role_map["operator"]], "Sales"),
        ("carol", "carol@platform.local", "Carol Wang / 王悦", demo_pw, [role_map["viewer"]], "HR"),
        ("diana", "diana@platform.local", "Diana Zhao / 赵敏", demo_pw, [role_map["auditor"]], "Audit"),
    ]
    for username, email, display, pwd, rids, dept in users:
        db.insert("users", {"username": username, "email": email, "display_name": display,
                            "password_hash": pwd, "status": "active", "dept": dept,
                            "role_ids": rids, "provider": "local", "created_at": now, "updated_at": now})

    for code, ptype, name, order, cfg in PROVIDERS:
        db.insert("auth_providers", {"code": code, "type": ptype, "name": name,
                                    # CAS ships enabled in demo mode so the SSO flow is
                                    # explorable on the login page without credentials.
                                    "enabled": 1 if code == "cas" else 0,
                                    "config": cfg, "sort_order": order,
                                    "created_at": now, "updated_at": now})

    for f in FORMS:
        db.insert("forms", {**f, "version": 1, "created_by": "admin",
                            "created_at": now, "updated_at": now})
    db.insert("form_submissions", {"form_id": 1, "data": {
        "applicant": "Bob Li", "department": "Sales", "leave_type": "Annual",
        "start_date": "2026-11-09", "end_date": "2026-11-10", "days": 2,
        "reason": "Family matters", "urgent": False}, "status": "approved", "submitted_by": "bob", "created_at": now})
    db.insert("form_submissions", {"form_id": 1, "data": {
        "applicant": "Alice Chen", "department": "Engineering", "leave_type": "Sick",
        "start_date": "2026-10-28", "end_date": "2026-10-29", "days": 2,
        "reason": "Flu", "urgent": True}, "status": "submitted", "submitted_by": "alice", "created_at": now})
    db.insert("form_submissions", {"form_id": 2, "data": {
        "item": "MacBook Pro", "category": "Hardware", "quantity": 2,
        "budget": 32000, "justification": "New hires"}, "status": "submitted",
        "submitted_by": "alice", "created_at": now})

    db.insert("workflows", {"code": "leave_approval", "name": "Leave Approval / 请假审批流程",
                            "description": "Conditional leave approval with AI summary and notification.",
                            "status": "published", "graph": LEAVE_GRAPH, "version": 1,
                            "created_by": "admin", "created_at": now, "updated_at": now})
    db.insert("workflows", {"code": "purchase_approval", "name": "Purchase Approval / 采购审批流程",
                            "description": "Budget based procurement approval.", "status": "draft",
                            "graph": PURCHASE_GRAPH, "version": 1, "created_by": "alice",
                            "created_at": now, "updated_at": now})
    db.insert("workflow_instances", {"workflow_id": 1, "status": "completed",
                                     "context": {"days": 2, "leave_type": "Annual", "applicant": "Bob Li"},
                                     "logs": [{"node": "n1", "type": "start", "status": "done"},
                                              {"node": "n2", "type": "form", "status": "done"},
                                              {"node": "n3", "type": "condition", "status": "done", "branch": "false"},
                                              {"node": "n4", "type": "approval", "status": "done", "result": "approved"},
                                              {"node": "n6", "type": "ai", "status": "done"},
                                              {"node": "n8", "type": "end", "status": "done"}],
                                     "started_by": "bob", "started_at": now, "finished_at": now})
    db.insert("workflow_instances", {"workflow_id": 1, "status": "completed",
                                     "context": {"days": 5, "leave_type": "Personal", "applicant": "Alice Chen"},
                                     "logs": [{"node": "n1", "type": "start", "status": "done"},
                                              {"node": "n3", "type": "condition", "status": "done", "branch": "true"},
                                              {"node": "n5", "type": "approval", "status": "done", "result": "approved"}],
                                     "started_by": "alice", "started_at": now, "finished_at": now})

    for code, name, desc in [
        ("platform-handbook", "Platform Handbook / 平台手册", "Product guides and engine documentation"),
        ("policies", "Company Policies / 企业制度", "HR and procurement policies"),
    ]:
        db.insert("kb_collections", {"code": code, "name": name, "description": desc,
                                     "embedding_model": "bm25-local", "chunk_size": 480,
                                     "created_by": "admin", "created_at": now})
    coll = {c["code"]: c["id"] for c in db.q("SELECT id,code FROM kb_collections")}
    for code, title, content in KB_DOCS:
        db.insert("kb_documents", {"collection_id": coll[code], "title": title, "content": content,
                                   "source": "seed", "status": "indexed", "chunks": [], "created_at": now})

    ensure_registries(now)

    for a in AGENTS:
        db.insert("agents", {**a, "status": "active", "created_by": "admin",
                             "created_at": now, "updated_at": now})
    db.insert("conversations", {"agent_id": 3, "title": "How do I design a workflow?",
                                "messages": [
                                    {"role": "user", "content": "How do I design a workflow?"},
                                    {"role": "assistant", "content": "Open the Workflow canvas, drag nodes, "
                                     "connect them and click Run. Conditional nodes choose a branch based on "
                                     "context fields."},
                                ], "user_id": "admin", "created_at": now})

    db.run("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)",
           ("mfa_policy", db.dumps(security.DEFAULT_MFA_POLICY), now))
    db.run("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)",
           ("platform_settings", db.dumps({
               "default_locale": "en", "default_theme": "system",
               "allow_signup": False, "audit_retention_days": 90,
               "password_min_length": 8, "session_idle_minutes": 120,
           }), now))

    for actor, action, resource, detail in [
        ("admin", "auth.login", "session", {"method": "local"}),
        ("alice", "form.publish", "form:leave_request", {"version": 1}),
        ("bob", "workflow.run", "workflow:leave_approval", {"instance": 1}),
        ("admin", "rbac.role.update", "role:operator", {"permissions": 10}),
        ("alice", "knowledge.document.create", "kb:platform-handbook", {"docs": 4}),
    ]:
        db.insert("audit_logs", {"actor": actor, "action": action, "resource": resource,
                                 "detail": detail, "ip": "127.0.0.1", "level": "info",
                                 "created_at": now})
    return True


# --------------------------------------------------------------------------- #
# Domestic form / approval examples (idempotently provisioned on every boot)
# --------------------------------------------------------------------------- #
ORG_UNITS = [
    ("HQ", "集团总部 / Headquarters", None, 1, "admin", 0),
    ("IT", "信息技术部 / IT", "HQ", 2, "admin", 1),
    ("Engineering", "技术研发部 / Engineering", "HQ", 2, "alice", 2),
    ("Sales", "销售部 / Sales", "HQ", 2, "bob", 3),
    ("HR", "人力资源部 / HR", "HQ", 2, "carol", 4),
    ("Finance", "财务部 / Finance", "HQ", 2, "admin", 5),
]

EXPENSE_FORM = {
    "code": "expense_claim", "name": "Expense Claim / 费用报销单", "status": "published",
    "description": "Domestic expense claim: serial number, detail table, RMB in words, "
                   "statutory identifiers, conditional display and conditional-required.",
    "schema": [
        {"id": "x1", "key": "serial_no", "type": "serial", "label": "单据编号 / No.",
         "width": 50, "serial": {"prefix": "BX", "date": True, "digits": 4}},
        {"id": "x2", "key": "applicant", "type": "user", "label": "报销人 / Applicant",
         "required": True, "width": 50},
        {"id": "x3", "key": "department", "type": "department", "label": "所属部门 / Dept",
         "required": True, "width": 50},
        {"id": "x4", "key": "mobile", "type": "mobile", "label": "手机号 / Mobile",
         "required": True, "width": 50},
        {"id": "x5", "key": "claim_type", "type": "select", "label": "报销类型 / Type",
         "required": True, "width": 50,
         "options": ["差旅", "办公采购", "业务招待", "其他"]},
        {"id": "x6", "key": "travel_region", "type": "region", "label": "出差地点 / Region",
         "width": 100, "visible_when": {"logic": "and", "conditions": [
             {"field": "claim_type", "operator": "eq", "value": "差旅"}]}},
        {"id": "x7", "key": "bank_account", "type": "bankcard", "label": "收款账号 / Bank card",
         "width": 50, "visible_when": {"logic": "and", "conditions": [
             {"field": "claim_type", "operator": "eq", "value": "差旅"}]}},
        {"id": "x8", "key": "supplier_uscc", "type": "uscc",
         "label": "供应商统一社会信用代码 / USCC", "width": 100,
         "visible_when": {"logic": "and", "conditions": [
             {"field": "claim_type", "operator": "eq", "value": "业务招待"}]}},
        {"id": "x9", "key": "idcard", "type": "idcard", "label": "身份证号 / ID card",
         "width": 50},
        {"id": "x10", "key": "items", "type": "table", "label": "费用明细 / Details",
         "width": 100, "columns": [
             {"key": "item", "label": "费用项目", "type": "text"},
             {"key": "qty", "label": "数量", "type": "number"},
             {"key": "price", "label": "单价", "type": "number"},
             {"key": "subtotal", "label": "小计", "type": "formula", "formula": "qty * price"},
         ], "summary": [{"key": "total", "label": "明细合计", "column": "subtotal", "op": "sum"}]},
        {"id": "x11", "key": "total_amount", "type": "amount", "label": "报销总额 / Total (CNY)",
         "required": True, "width": 50, "show_upper": True,
         "formula": "TABLE_SUM(\"items\", \"subtotal\")",
         "validation": {"min": 0, "precision": 2}},
        {"id": "x12", "key": "remark", "type": "textarea", "label": "备注 / Remark",
         "width": 100, "required_when": {"logic": "and", "conditions": [
             {"field": "total_amount", "operator": "gt", "value": 5000}]}},
        {"id": "x13", "key": "invoice", "type": "image", "label": "发票照片 / Invoice",
         "width": 50},
        {"id": "x14", "key": "signature", "type": "signature", "label": "本人签名 / Signature",
         "width": 50},
        {"id": "x15", "key": "notice", "type": "description", "label": "填写说明",
         "width": 100, "description": "单笔超过 5000 元需填写备注并走财务会签。"},
    ],
    "layout": {"columns": 2, "labelWidth": 150, "size": "default",
               "mobile": {"columns": 1, "hidden": ["supplier_uscc"]}},
    "print_template": {"title": "费用报销单", "show_serial": True,
                       "show_upper": True, "paper": "A4"},
    "settings": {"allow_draft": True, "unique_per_day": True},
}

EXPENSE_GRAPH = {
    "nodes": [
        {"id": "n1", "type": "start", "name": "发起报销 / Start", "x": 60, "y": 240,
         "config": {"form_code": "expense_claim"}},
        {"id": "n2", "type": "approval", "name": "部门主管 / Dept. leader", "x": 250, "y": 240,
         "config": {"approver_rule": "initiator_leader", "leader_level": 1,
                    "sign_mode": "any", "exclude_initiator": True, "empty_policy": "admin",
                    "timeout_hours": 24, "timeout_action": "remind",
                    "comment_required": True,
                    "field_permissions": {"serial_no": "readonly", "applicant": "readonly",
                                          "total_amount": "readonly", "items": "readonly"}}},
        {"id": "n3", "type": "condition", "name": "金额>5000 或 差旅 / Condition", "x": 470, "y": 240,
         "config": {"logic": "or", "conditions": [
             {"field": "total_amount", "operator": "gt", "value": 5000},
             {"field": "claim_type", "operator": "eq", "value": "差旅"}]}},
        {"id": "n4", "type": "parallel", "name": "并行会签 / Parallel", "x": 690, "y": 240,
         "config": {}},
        {"id": "n5", "type": "approval", "name": "财务会签 / Finance countersign", "x": 900, "y": 120,
         "config": {"approver_rule": "users", "assignees": ["admin", "alice"],
                    "sign_mode": "all", "allow_return": True, "reject_policy": "return"}},
        {"id": "n6", "type": "approval", "name": "总经理 / GM", "x": 900, "y": 360,
         "config": {"approver_rule": "users", "assignees": ["bob"], "sign_mode": "any"}},
        {"id": "n8", "type": "join", "name": "汇聚 / Join", "x": 1110, "y": 240,
         "config": {"join_mode": "all"}},
        {"id": "n7", "type": "cc", "name": "抄送人事 / CC HR", "x": 1300, "y": 240,
         "config": {"approver_rule": "users", "assignees": ["carol"]}},
        {"id": "n9", "type": "end", "name": "结束 / End", "x": 1490, "y": 240, "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "target": "n4", "label": "是 / Yes", "condition": "true"},
        {"id": "e4", "source": "n3", "target": "n7", "label": "否 / No", "condition": "false"},
        {"id": "e5", "source": "n4", "target": "n5"},
        {"id": "e6", "source": "n4", "target": "n6"},
        {"id": "e7", "source": "n5", "target": "n8"},
        {"id": "e8", "source": "n6", "target": "n8"},
        {"id": "e9", "source": "n8", "target": "n7"},
        {"id": "e10", "source": "n7", "target": "n9"},
    ],
}


def ensure_domestic_examples(now: str | None = None) -> dict:
    """Provision org units and the domestic example form/workflow idempotently."""
    now = now or db.now()
    created = {"org_units": 0, "forms": 0, "workflows": 0}
    for code, name, parent, level, leader, order in ORG_UNITS:
        if db.q1("SELECT id FROM org_units WHERE code=?", (code,)):
            continue
        db.insert("org_units", {"code": code, "name": name, "parent_code": parent,
                                "level": level, "leader": leader, "sort": order,
                                "created_at": now})
        created["org_units"] += 1
    if not db.q1("SELECT id FROM forms WHERE code=?", (EXPENSE_FORM["code"],)):
        db.insert("forms", {**EXPENSE_FORM, "version": 1, "created_by": "admin",
                            "created_at": now, "updated_at": now})
        created["forms"] += 1
    if not db.q1("SELECT id FROM workflows WHERE code=?", ("expense_approval",)):
        db.insert("workflows", {"code": "expense_approval",
                                "name": "Expense Approval / 费用报销审批",
                                "description": "Leader approval, amount/type condition group, "
                                               "parallel countersign + GM, join, CC and timeout.",
                                "status": "published", "form_code": EXPENSE_FORM["code"],
                                "graph": EXPENSE_GRAPH, "version": 1, "created_by": "admin",
                                "created_at": now, "updated_at": now})
        created["workflows"] += 1
    # Portal launch needs an explicit form binding on the definition (not only
    # inside a form node). Backfill demo workflows created before the portal.
    for wf_code, f_code in (("leave_approval", "leave_request"),
                            ("purchase_approval", "purchase_request"),
                            ("expense_approval", "expense_claim")):
        db.run("UPDATE workflows SET form_code=? WHERE code=? AND "
               "(form_code IS NULL OR form_code='')", (f_code, wf_code))
    return created
