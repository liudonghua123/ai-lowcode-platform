# 系统架构设计

| 项目 | 内容 |
| --- | --- |
| 文档编号 | `ARC-001` |
| 状态 | 基线（已实现并验证） |
| 版本 | 1.0 |
| 适用版本 | `ai-lowcode-platform` v0.1.0 |
| 读者 | 架构师、前后端工程师、运维 |
| English | [architecture.md](architecture.md) |
| 关联文档 | [AI 系统设计](ai-design.zh-CN.md) · [安全架构](security.md) · [数据模型](data-model.md) · [接口与 MCP 规范](api-reference.md) · [ADR 索引](adr/README.md) |

## 1. 目的与范围

本文档描述 AI 低代码平台的**已落地架构**：一套前后端分离的全栈系统，提供可视化表单设计、可视化 DAG 流程编排、版本化 REST API、带第三方技能注册的 MCP 服务、基于知识库的 AI 查询/操作智能体、RBAC、五种 SSO 协议，以及可按角色/用户配置的多因子认证。

**范围内**：系统上下文、容器视图、前后端组件、运行时流程、数据流、部署拓扑、横切关注点、质量属性与演进边界。

**范围外**：AI 算法细节见 [AI 系统设计](ai-design.zh-CN.md)，密码学与权限细节见 [安全架构](security.md)，逐表结构见 [数据模型](data-model.md)，端点契约见 [接口与 MCP 规范](api-reference.md)。

## 2. 目标、非目标与约束

| 目标 | 非目标 |
| --- | --- |
| 零外部依赖即可完整运行（离线优先演示） | 分布式 / 多租户生产部署 |
| 平台能力单一事实来源（统一工具注册表） | 托管向量库或托管 LLM 服务 |
| 所有写操作均经授权（RBAC）并记录审计 | 真实 WebAuthn 认证器 attestation 校验 |
| 界面风格一致，i18n 中英文（默认英文）、system/light/dark 主题 | 原生移动应用 |
| 单端口部署，运维简单 | 开箱即用的水平扩展 / 高可用 |

**约束**：Python 3.11+、Node 18+、`uv`、`pnpm`；SQLite 标准库（WAL）；`fastmcp` 4.x streamable HTTP；MIT 协议；界面禁用 emoji（仅 SVG）。

## 3. 架构原则

1. **一处注册、三处消费。** 暴露给 LLM 的每个能力只在 `backend/app/services/mcp_tools.py` 声明一次（名称、JSON Schema、权限、handler）。MCP 服务、AI ReAct 循环与 `POST /api/v1/mcp/invoke` 调用同一批 handler。见 [ADR-0002](adr/0002-single-tool-registry.md)。
2. **离线优先、优雅降级。** 默认 `mock` LLM 后端无需 API Key；`fastmcp` 不可用时 MCP 自动回退到内置 JSON-RPC 传输。见 [ADR-0003](adr/0003-offline-first-llm-runtime.md)。
3. **声明式授权。** 每个业务路由使用 `Depends(require("resource:action"))`；工具调用通过注册表再次执行同一权限校验。
4. **元数据驱动 UI。** 前端不硬编码目录数据；`/meta/bootstrap` 一次返回字段类型、节点类型、权限、Provider、Agent 运行时、i18n 语言与主题。
5. **无状态请求身份 + 本地持久化。** JWT 承载身份；SQLite 以 WAL、线程局部连接与写锁保存状态。

## 4. 系统上下文（C4 Level 1）

```mermaid
flowchart TB
    User[终端用户 / 管理员]
    MCPClient[外部 MCP 客户端<br/>Claude Desktop、IDE、Agent]
    IdP[身份提供商<br/>CAS · OAuth2 · OIDC · 企业微信 · 钉钉]
    LLM[LLM 服务<br/>mock / OpenAI 兼容 / AgentScope]

    User -->|HTTPS| System[AI 低代码平台]
    MCPClient -->|MCP streamable HTTP /mcp| System
    System -->|OIDC / CAS / OAuth2 重定向| IdP
    System -->|chat completions，可选| LLM
```

平台是**单一可部署单元**：一个 FastAPI 进程同时提供 REST API、MCP 端点、OpenAPI 文档，以及（单端口模式下）构建后的 SPA。

## 5. 容器视图（C4 Level 2）

```mermaid
flowchart LR
    subgraph Browser[浏览器]
        SPA[Vite SPA<br/>React 18 · TS · HashRouter]
    end
    subgraph Process["uvicorn :8000（FastAPI）"]
        API["REST 层<br/>/api/v1 · 9 个 router"]
        MCPS["MCP 服务<br/>/mcp · fastmcp + 内置回退"]
        SVC["服务层<br/>workflow_engine · rag · llm<br/>mcp_tools · sso"]
        SEC["安全层<br/>JWT · PBKDF2 · TOTP<br/>WebAuthn · RBAC"]
        HOST["SPA 静态托管<br/>frontend/dist 回退"]
    end
    DB[(SQLite<br/>WAL · 19 张表)]
    FS[("dist/ 静态资源")]

    SPA -->|JSON + Bearer| API
    SPA -->|静态资源| HOST
    API --> SEC
    API --> SVC
    MCPS -->|ASGI 中间件 bind_user| SEC
    MCPS --> SVC
    SVC --> DB
    SEC --> DB
    HOST --> FS
```

| 容器 | 职责 | 技术 |
| --- | --- | --- |
| SPA | 全部 UI、可视化设计器、i18n、主题 | Vite 6、React 18、TypeScript、Tailwind 3、shadcn/ui 风格组件、lucide-react |
| REST 层 | 80 个 OpenAPI 路径、Pydantic 模型、错误语义 | FastAPI 0.128+、`APIRouter`、`Depends` |
| MCP 服务 | `initialize` / `tools/list` / `tools/call` / resources / prompts | `fastmcp` 4.1.6 `http_app(path="/mcp")` + 内置 JSON-RPC 回退 |
| 服务层 | 纯业务逻辑，不感知 HTTP | `app/services/` 下 Python 模块 |
| 安全层 | 身份、令牌、密码/MFA、权限校验 | 标准库 `hashlib`/`hmac`、HS256 JWT、`contextvars` |
| 持久化 | 全部状态 | `sqlite3`（WAL、JSON 列、线程局部连接、写锁） |

## 6. 组件视图（C4 Level 3，后端）

```
app/
├── main.py            lifespan（init_db → seed → fastmcp lifespan）、CORS、
│                      MCPAuthASGIMiddleware、路由注册、SPA catch-all
├── config.py          冻结 Settings dataclass，dotenv（backend/.env + 根目录 .env）
├── db.py              schema、连接生命周期、insert/update/delete/q/q1/scalar
├── security.py        密码哈希、JWT（access/mfa/enroll）、TOTP、WebAuthn、MFA 策略
├── deps.py            get_current_user、has_permission、require()、audit()
├── seed.py            首次启动的确定性演示数据
├── mcp_server.py      fastmcp 工具 + 无依赖 JSON-RPC 回退
├── routers/           auth · rbac · forms · workflows · knowledge · agents · mcp · audit · meta
└── services/
    ├── mcp_tools.py        ★ 能力注册表（12 工具、Schema、权限）
    ├── workflow_engine.py  DAG 校验（环检测）、条件路由、执行
    ├── rag.py              中英混合分词、分块、BM25、上下文拼装
    ├── llm.py              3 个后端、ReAct 编排、有据回答
    └── sso.py              5 种 Provider 适配、demo 模式、身份自动建号
```

### 6.1 请求管线

```
HTTP → CORS → 路由匹配 → Depends(get_current_user) → Depends(require(permission))
     → Pydantic 校验 → router → service → db（WAL）→ audit() → JSON 响应
```

MCP 请求走并行路径：纯 ASGI 的 `MCPAuthASGIMiddleware` 解析可选 `Authorization: Bearer`，通过 `ContextVar` 调用 `mcp_tools.bind_user(user)`，随后 fastmcp / 内置 handler 调用 `mcp_tools.call_tool()` 执行同一套权限校验。

### 6.2 前端组合

```
main.tsx → HashRouter · ThemeProvider · I18nProvider · ToastProvider · AppContext
         → App.tsx（鉴权守卫、Splash）→ AppShell（侧栏/顶栏/用户菜单）
         → 12 个页面模块
```

`lib/api.ts` 封装 `fetch`，统一注入 JWT、`ApiError` 与全局 `401 → 登出` 事件。`AppContext` 登录后一次性加载 `/auth/me` + `/meta/bootstrap`，并暴露 `can(permission)`。

## 7. 关键运行时流程

### 7.1 认证（MFA 与 SSO）

```mermaid
sequenceDiagram
    participant U as 用户
    participant F as SPA
    participant A as /api/v1/auth
    participant S as security.py
    participant D as SQLite

    U->>F: 账号密码或点击 SSO
    F->>A: POST /auth/login 或 /auth/sso/{code}/authorize
    A->>S: verify_password / exchange()
    S->>D: 读取用户、角色、权限
    alt 命中 MFA 策略（全局 / 角色 / 用户）
        A-->>F: mfa_required + enroll/verify token
        U->>F: OTP 动态码或 Passkey 断言
        F->>A: POST /auth/mfa/verify
    end
    A-->>F: access_token（HS256，typ=access，TTL 7200s）
    F->>A: GET /meta/bootstrap（目录数据）
```

### 7.2 AI 智能体执行真实平台操作

```mermaid
sequenceDiagram
    participant U as 用户
    participant R as agents 路由
    participant L as llm.run_agent
    participant G as rag
    participant T as mcp_tools
    participant D as SQLite

    U->>R: POST /agents/{id}/chat
    R->>T: bind_user(user)
    R->>L: run_agent(agent, message, history)
    L->>G: search(message, kb_ids, top_k)
    G-->>L: hits → [Knowledge Context]
    loop ReAct 循环（最多 5 轮）
        L->>L: chat(messages, tools) → tool_calls
        L->>T: call_tool(name, args, user)
        T->>T: 权限校验（PERMISSION_MAP）
        T->>D: 读写（提交表单、运行流程…）
        T-->>L: 结果 → role=tool 消息
    end
    L-->>R: answer + steps + sources + provider
    R->>D: 持久化会话
    R-->>U: 带可见工具调用步骤的响应
```

### 7.3 流程执行

`validate_graph()` 强制校验：唯一 `start`、至少一个 `end`、节点类型合法、边端点存在、无环（DFS 三状态）。`run()` 按 DAG 遍历，依据上下文求值 `condition` 节点（`gt/gte/lt/lte/eq/ne/contains`），分派 `form/approval/ai/knowledge/http/notification` 节点，返回 `{status, context, logs}` 并写入 `workflow_instances`。

## 8. 数据流

| 流程 | 路径 | 存储 |
| --- | --- | --- |
| 表单定义 | 设计器 → `PUT /forms/{id}` → JSON `schema` 列 | `forms`, `form_submissions` |
| 流程画布 | 画布 → `PUT /workflows/{id}` → JSON `graph` 列 | `workflows`, `workflow_instances` |
| 知识库 | 创建文档 → `rag.index_document()` → JSON `chunks` | `kb_collections`, `kb_documents` |
| 智能体会话 | 对话 → `run_agent()` → 会话轮次 | `conversations`, `audit_logs` |
| MCP 技能注册 | 外部服务配置 → 同步 → 工具缓存 | `mcp_skills` |
| 配置 | `.env` → `Settings` → 运行时覆盖 | `settings` |

复杂结构统一以 JSON 文本列存储，由 `db._enc/_dec` 与 `db.loads()` 透明序列化。

## 9. 部署视图

| 模式 | 命令 | 端口 | 用途 |
| --- | --- | --- | --- |
| 开发 | `./scripts/dev.sh` | `:8000` API + `:5173` Vite（代理 `/api`、`/mcp`） | 热更新、快速迭代 |
| 单端口 | `./scripts/start.sh` | 仅 `:8000` | 演示 / 简易部署，FastAPI 托管 `frontend/dist` |
| 纯 API | `uvicorn app.main:app --port 8000` | `:8000` | 无头 API + MCP 消费方 |

SPA catch-all 无条件注册，并在每次请求时解析 `dist/index.html`，因此后端可先于前端构建启动；`/api`、`/mcp`、`/docs`、`/openapi.json` 受保护不被回退。`HashRouter` 免去服务端路由配置。

## 10. 横切关注点

| 关注点 | 实现 |
| --- | --- |
| i18n | 每种语言 496 个叶子键，默认 `en`，`localStorage` 持久化，同步 `<html lang>`，缺失回退英文 |
| 主题 | `system`（默认）/ `light` / `dark`，监听 `prefers-color-scheme`，HSL CSS 变量，`meta[theme-color]` |
| 审计 | 所有写操作 → `audit_logs(actor, action, resource, detail, ip, level, created_at)` |
| 配置 | `python-dotenv` → 冻结 `Settings`；`settings` 表支持运行时覆盖 |
| 错误 | `HTTPException` 401 / 403 / 404 / 422；客户端 `ApiError`；401 触发全局登出 |
| 可观测 | `/api/v1/meta/health`、`/meta/stats`、`/agents/meta/runtime`、`/mcp/status` |
| 测试 | `backend/tests/smoke.py` 47 项端到端断言；`pnpm typecheck`、`pnpm build`、`pnpm check:i18n`、`ruff check` |

## 11. 技术决策摘要

| 决策 | 理由 | ADR |
| --- | --- | --- |
| Monorepo、前后端分离、uv + pnpm | 工具链独立，一次 clone 即可运行 | [0001](adr/0001-monorepo-and-stack.md) |
| MCP / Agent / REST 共用工具注册表 | 避免能力漂移，统一权限闸口 | [0002](adr/0002-single-tool-registry.md) |
| 离线优先 LLM + 3 个后端 | 零配置演示，可升级真实模型 | [0003](adr/0003-offline-first-llm-runtime.md) |
| SQLite + 进程内 BM25 | 无外部服务，支持中英混合检索 | [0004](adr/0004-sqlite-and-local-bm25.md) |
| fastmcp 主通道 + 内置回退、ASGI 鉴权绑定 | 兼顾 MCP 合规与韧性 | [0005](adr/0005-mcp-transport-and-auth.md) |
| RBAC + 策略化 MFA + demo SSO | 不依赖外部 IdP 也具备完整认证面 | [0006](adr/0006-rbac-mfa-and-sso.md) |

## 12. 质量属性与取舍

| 属性 | 当前姿态 | 演进路径 |
| --- | --- | --- |
| 可用性 | 单进程、SQLite WAL | 多 worker + Postgres、共享会话存储 |
| 安全性 | HS256 JWT、PBKDF2、逐路由 RBAC、审计 | RS256 / 密钥轮换、限流、密钥管理 |
| AI 准确性 | 确定性 mock + BM25 有据回答 | 真实 LLM、向量库、重排序 |
| 可扩展性 | 进程内索引、同步执行 | 流程任务队列、外部向量库 |
| 可测试性 | 47 项冒烟断言，无需网络 | 契约测试、压力测试、MCP 一致性套件 |
| 可运维性 | health / stats / runtime 端点 | 结构化日志、指标、链路追踪 |

## 13. 已知限制

- SQLite 与进程内 BM25 为单节点，索引不跨进程共享。
- `mock` LLM 使用正则意图识别，是确定性逻辑而非生成式模型。
- WebAuthn 采用 challenge / credential 绑定，未做完整 attestation 校验；`PASSKEY_ORIGIN` 必须与部署一致（HTTPS 或 localhost）。
- SSO demo 模式不经过真实 IdP 校验即自动建号；生产需配置真实凭据与 TLS。
- 流程引擎在请求内同步执行；长流程应迁移到任务队列。

## 14. 需求可追溯性

| 需求 | 设计要素 | 代码 |
| --- | --- | --- |
| 可视化表单设计 | 元数据驱动设计器 | `routers/forms.py`, `pages/Forms.tsx` |
| 可视化流程编排 | DAG 校验器 + 执行引擎 | `services/workflow_engine.py`, `pages/Workflows.tsx` |
| REST API | 版本化路由 | `routers/*.py`（107 个路由装饰器 → 80 个 OpenAPI 路径） |
| MCP + 第三方 skills | 双传输 MCP + 注册表 | `mcp_server.py`, `routers/mcp.py` |
| AI 查询/操作智能体 | ReAct + 工具注册表 + RAG | `services/llm.py`, `services/rag.py` |
| 知识库 | BM25 + 分块 | `services/rag.py`, `routers/knowledge.py` |
| RBAC / SSO / MFA | 声明式守卫 + 适配器 | `deps.py`, `security.py`, `services/sso.py` |
| i18n / 主题 | Provider + bootstrap | `i18n/`, `theme/`, `routers/meta.py` |
