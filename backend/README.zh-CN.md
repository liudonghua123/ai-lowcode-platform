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
- 冒烟测试：`python tests/smoke.py`（284 项断言，不依赖外部服务）。

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
    mcp_journal.py     调用日记持久化、查询、统计与导出数据
    skill_catalog.py   可安装技能模板与默认文件生成
    skill_files.py     可编辑技能文件、路径校验、磁盘镜像
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
| 知识库 | `GET|POST|PUT|DELETE /knowledge/collections[/{id}]`、`/knowledge/documents[/{id}]`，`POST /knowledge/documents/{id}/reindex`，`POST /knowledge/search`，`GET /knowledge/stats`，`GET /knowledge/formats`，`POST /knowledge/upload` |
| 智能体 | `GET /agents/meta/runtime`、`GET /agents/meta/bindings`，`GET|POST|PUT|DELETE /agents[/{id}]`，`POST /agents/{id}/chat`，`GET|DELETE /agents/conversations[/{id}]` |
| MCP 传输 | `GET /mcp/tools`、`/mcp/status`，`GET /mcp/calls[/stats,/export,{id}]`，`DELETE /mcp/calls`，`POST /mcp/invoke` |
| MCP 服务 | `GET|POST|PUT|DELETE /mcp/servers[/{id}]`，`GET /mcp/servers/summary`，`GET /mcp/servers/{id}/tools`，`POST /mcp/servers/{id}/{sync,enable,disable,invoke}` |
| 技能 | `GET|POST|PUT|DELETE /skills[/{id}]`，`GET /skills/catalog`，`POST /skills/install`，`POST /skills/{id}/{enable,disable,uninstall,reinstall,sync}`，`GET|PUT|DELETE /skills/{id}/files[/...]`，`POST /skills/{id}/files/reload` |
| AI 模型 | `GET /ai/providers/meta`，`GET|POST|PUT|DELETE /ai/providers[/{id}]`，`POST /ai/providers/{id}/{default,test}` |
| 审计 / 元数据 | `GET /audit/logs`、`/audit/actions`，`GET /meta/health`、`/meta/version`、`/meta/stats`、`/meta/bootstrap`，`GET|PUT /settings` |

所有写操作均记录审计日志，所有接口由 `Depends(deps.require(permission))` 守卫。

## MCP

`POST /mcp` 使用真实 `fastmcp` SDK 实现 streamable HTTP JSON-RPC（SDK 缺失时自动降级为内置实现）。支持 `initialize`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`、`resources/templates/list`、`prompts/list`、`prompts/get` 与通知。

工具在 `services/mcp_tools.py` 中统一声明，被 MCP 服务、智能体 ReAct 循环、`POST /api/v1/mcp/invoke` 三处复用：

`list_forms`、`get_form`、`submit_form`、`query_records`、`list_workflows`、`get_workflow`、`run_workflow`、`get_workflow_instance`、`list_collections`、`search_knowledge`、`list_users`、`get_stats`。

**两套独立注册表。** MCP 服务与技能是独立实体，各自拥有数据表、路由与生命周期（见 [ADR-0008](../docs/adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md)）：

| 注册表 | 数据表 | 路由 | 职责 |
| --- | --- | --- | --- |
| MCP 服务 | `mcp_servers` | `/mcp/servers` | 连接配置（`transport`、`endpoint` / `command`、`auth_config`）、`probe()` + `sync()` 工具发现、健康/状态、`invoke_on_server()` |
| 技能 | `mcp_skills` | `/skills` | 生命周期、目录、manifest、可编辑文件、可空 `server_id` 关联 |

`services/mcp_servers.py::declared_tools()` 把已启用服务声明的工具合并进 `mcp_tools.list_tools(include_external=True)`；`call_remote_tool` MCP 桥接工具以 `mcp:invoke` 权限把调用转发给所属服务，并写入 `target=server:<code>` 的日记记录。`mcp_tools.agent_tools(agent, fmt)` 按智能体的 `server_ids` / `skill_ids` 绑定收窄 ReAct 工具集。删除任一实体都不会连带删除另一实体。

**MCP 服务。** `GET /mcp/servers/summary` 返回注册表统计；`POST /mcp/servers` 注册 `http` / `sse` / `stdio` 连接；`POST /mcp/servers/{id}/sync` 以 `initialize` + `tools/list` 探测端点并刷新声明的工具；`GET /mcp/servers/{id}/tools`、`/{id}/enable`、`/{id}/disable`、`/{id}/invoke` 构成完整接口面。`/mcp` 上的 Bearer Token 由纯 ASGI 中间件绑定到工具上下文，从而执行 RBAC 校验。

**技能生命周期。** `GET /skills/catalog` 提供 5 个可安装模板；`POST /skills/install` 安装技能并生成 5 个可编辑文件（`SKILL.md`、`manifest.json`、`config.json`、`tools.json`、`README.md`），同时写入 `mcp_skill_files` 并镜像到 `data/skills/<code>/`。`enable` / `disable` / `uninstall` / `reinstall` 管理状态机；卸载删除文件但保留注册项。`POST /skills/{id}/sync` 从关联服务（`server_id`）刷新工具。文件增删查改位于 `/skills/{id}/files/{path}`，含路径穿越校验与 `POST .../files/reload` 磁盘重载。

**AI 模型服务。** `GET /ai/providers/meta` 返回六类模型（`llm`、`asr`、`tts`、`embedding`、`rerank`、`vision`）与厂商；`GET|POST|PUT|DELETE /ai/providers[/{id}]` 管理配置（`api_key` 只写，读取仅返回 `has_api_key` / `api_key_masked`）；`POST /ai/providers/{id}/default` 保证每类一个默认项，`/{id}/test` 探测连通性。`model_providers.effective_llm()` 让 `llm` 默认项在运行时覆盖 `LLM_*` 环境变量。

**知识库上传。** `GET /knowledge/formats` 列出支持的扩展名；`POST /knowledge/upload` 接收 multipart 批量文件，由 `services/documents.py` 解析（OOXML / OpenDocument / EPUB 走标准库 ZIP+XML，PDF 走 `pdftotext`，图片走 `tesseract`，另含文本/数据格式），并立即分块索引进 BM25。详见 [知识库上传](../docs/knowledge-upload.md)。

**智能体绑定。** `GET /agents/meta/bindings` 返回全部可绑定资源；创建/更新接受 `kb_ids`、`skill_ids`、`server_ids`、`workflow_ids`，保存时由 `routers/agents.py::_clean_ids()` 清理失效 id。

**调用日记。** `mcp_call_logs` 记录每次工具调用（MCP `tools/call`、REST `invoke`、智能体工具步骤）与所有非工具 JSON-RPC 方法，并以 `target` 列标识外部服务。ASGI 中间件为上下文打上 `source` / `actor` / `request_id` 标签并一次性缓冲请求体；`mcp_tools.call_tool()` 在 `finally` 中写入参数、结果预览、状态、错误与耗时，因此失败调用同样留痕。查询 / 统计 / CSV 导出 / 详情 / 清空分别由 `GET /mcp/calls`、`/calls/stats`、`/calls/export`、`/calls/{id}`、`DELETE /mcp/calls` 提供，受 `mcp:read` / `mcp:write` 约束。详见 [MCP 服务、技能与调用日记](../docs/mcp-skills.md)。

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
