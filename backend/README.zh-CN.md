# 后端 — AI 低代码平台

基于 **uv + python-dotenv + FastAPI + fastmcp + AgentScope** 的服务端：SQLite 持久化、JWT/RBAC 安全体系、SSO/MFA、DAG 流程引擎、BM25 RAG、AI 智能体与 MCP streamable HTTP 服务。

English: [README.md](README.md) · [顶层文档](../README.md)

## 运行

```bash
cp .env.example .env
uv sync                          # 或 pip3 install fastapi uvicorn python-dotenv httpx fastmcp agentscope
uv run uvicorn app.main:app --reload --port 8000
```

- REST：`http://localhost:8000/api/v1` · OpenAPI：`/docs` · MCP：`http://localhost:8000/mcp`
- 若 `../frontend/dist` 存在，会由 `/` 直接托管前端（单端口模式）。
- 首次启动自动创建并填充 `data/platform.db`；删除该文件可重新初始化。
- 冒烟测试：`python tests/smoke.py`（47 项断言，不依赖外部服务）。

## 目录

```
app/
  main.py            FastAPI 应用、CORS、路由、SPA 托管、MCP ASGI 挂载、生命周期
  config.py          dotenv 配置（单一 Settings 实例）
  db.py              SQLite 辅助函数（q/q1/run/insert/update/delete + JSON 列）
  security.py        PBKDF2、JWT HS256、TOTP、WebAuthn challenge、MFA 策略
  deps.py            get_current_user / require(permission) / audit()
  seed.py            权限、角色、用户、表单、流程、知识库、智能体、技能
  mcp_server.py      fastmcp 工具定义 + 内置 JSON-RPC 降级实现
  routers/           auth · rbac · forms · workflows · knowledge · agents · mcp · audit · meta
  services/
    mcp_tools.py       统一工具注册表（Schema + 权限 + 处理函数）
    workflow_engine.py DAG 校验、条件路由、执行日志
    rag.py             中英分词、分块、BM25 检索、上下文组装
    llm.py             mock / OpenAI 兼容 / AgentScope 对话 + ReAct 循环
    sso.py             CAS、OAuth2、OIDC、企业微信、钉钉
```

## REST 接口（前缀 `/api/v1`）

| 分组 | 接口 |
| --- | --- |
| 认证 | `POST /auth/login`、`/auth/mfa/verify`、`/auth/change-password`，`GET /auth/me`，`POST /auth/logout` |
| OTP | `POST /auth/otp/setup`、`/auth/otp/enable`、`/auth/otp/disable` |
| Passkey | `POST /auth/passkey/register/options` + `/verify`，`POST /auth/passkey/authenticate/options` + `/verify`，`GET|DELETE /auth/passkey/credentials[/{id}]` |
| MFA 策略 | `GET|PUT /auth/mfa-policy` |
| SSO | `GET /auth/providers`、`GET /auth/sso/providers`、`PUT /auth/sso/providers/{code}`、`GET /auth/sso/{code}/authorize`、`GET|POST /auth/sso/{code}/callback` |
| RBAC | `GET /rbac/permissions`、`/rbac/matrix`，`GET|POST|PUT|DELETE /rbac/users[/{id}]`、`/rbac/roles[/{id}]`，`POST /rbac/users/{id}/reset-password`、`POST /rbac/check` |
| 表单 | `GET /forms/field-types`，`GET|POST /forms`，`GET /forms/code/{code}`，`GET|PUT|DELETE /forms/{id}`，`POST /forms/{id}/publish`，`GET|POST /forms/{id}/submissions` |
| 流程 | `GET /workflows/node-types`，`GET|POST /workflows`，`GET|PUT|DELETE /workflows/{id}`，`POST /workflows/{id}/validate`、`/run`，`GET /workflows/{id}/instances`、`GET /workflows/instances/{id}` |
| 知识库 | `GET|POST|PUT|DELETE /knowledge/collections[/{id}]`、`/knowledge/documents[/{id}]`，`POST /knowledge/documents/{id}/reindex`，`POST /knowledge/search`，`GET /knowledge/stats` |
| 智能体 | `GET /agents/meta/runtime`，`GET|POST|PUT|DELETE /agents[/{id}]`，`POST /agents/{id}/chat`，`GET|DELETE /agents/conversations[/{id}]` |
| MCP | `GET /mcp/tools`、`/mcp/status`，`GET|POST|PUT|DELETE /mcp/skills[/{id}]`，`POST /mcp/skills/{id}/sync`，`POST /mcp/invoke` |
| 审计 / 元数据 | `GET /audit/logs`、`/audit/actions`，`GET /meta/health`、`/meta/version`、`/meta/stats`、`/meta/bootstrap`，`GET|PUT /settings` |

所有写操作均记录审计日志，所有接口由 `Depends(deps.require(permission))` 守卫。

## MCP

`POST /mcp` 使用真实 `fastmcp` SDK 实现 streamable HTTP JSON-RPC（SDK 缺失时自动降级为内置实现）。支持 `initialize`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`、`resources/templates/list`、`prompts/list`、`prompts/get` 与通知。

工具在 `services/mcp_tools.py` 中统一声明，被 MCP 服务、智能体 ReAct 循环、`POST /api/v1/mcp/invoke` 三处复用：

`list_forms`、`get_form`、`submit_form`、`query_records`、`list_workflows`、`get_workflow`、`run_workflow`、`get_workflow_instance`、`list_collections`、`search_knowledge`、`list_users`、`get_stats`。

第三方 MCP 服务登记在 `mcp_skills` 表（`builtin` / `http` / `sse` / `stdio`）；`POST /mcp/skills/{id}/sync` 会以 `initialize` + `tools/list` 探测端点并刷新工具目录。`/mcp` 上的 Bearer Token 由纯 ASGI 中间件绑定到工具上下文，从而执行 RBAC 校验。

## 认证与安全模型

- 密码：PBKDF2-HMAC-SHA256（18 万轮、独立盐）。令牌：HS256 JWT（`typ` = `access` / `mfa` / `enroll`）。
- OTP：RFC 6238 TOTP，6 位、30 秒、±1 窗口；`otpauth://` URI 用于扫码绑定。
- Passkey：WebAuthn challenge → `navigator.credentials.create/get` → 凭据绑定。演示级 attestation；安装 `webauthn` extra 启用完整校验（需 HTTPS）。
- MFA 策略：全局 / 按角色 / 按用户；命中策略但用户尚未绑定因子时，登录返回 `enroll_token`，前端引导完成注册。
- SSO：真实协议流程（CAS ticket 校验、OAuth2 code 交换 + userinfo、OIDC discovery + ID Token nonce 校验、企微/钉钉 token 与用户接口），凭据缺失时自动进入明确标注的演示模式。

## LLM / AgentScope

`LLM_PROVIDER=mock`（默认）提供确定性意图识别与基于知识的回答，保证离线可用。`openai-compatible` 调用任意 chat-completions 端点；`agentscope` 在已安装且有凭据时构建 `agentscope.model` 对话模型，否则透明降级。`services/llm.py` 实现 ReAct 循环：检索 RAG 上下文 → 模型请求工具 → 执行共享工具注册表 → 结果回灌 → 带来源回答。

## 配置

见 `.env.example`。全部配置由 `config.Settings` 从 `.env` 读取一次；SSO/MFA/平台设置还可通过接口在运行时修改（存入 `settings` 表）。

**生产建议**：设置强 `SECRET_KEY`、启用 HTTPS、替换 SQLite、配置真实 SSO/LLM 凭据、安装 `webauthn` 完成 Passkey 校验、对 MCP 强制认证。演示引擎中的审批/HTTP/通知节点为模拟实现。

## 协议

[MIT](../LICENSE)
