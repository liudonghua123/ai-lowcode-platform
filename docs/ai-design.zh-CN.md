# AI 系统设计

| 项目 | 内容 |
| --- | --- |
| 文档编号 | `AI-001` |
| 状态 | 基线（已实现并验证） |
| 版本 | 1.0 |
| 适用版本 | `ai-lowcode-platform` v0.1.0 |
| 读者 | AI 工程师、后端工程师、评审 |
| English | [ai-design.md](ai-design.md) |
| 关联文档 | [系统架构设计](architecture.zh-CN.md) · [安全架构](security.md) · [接口与 MCP 规范](api-reference.md) · [ADR 索引](adr/README.md) |

## 1. 范围与术语

本文档规定平台**已落地的 AI 子系统**：一条自然语言请求如何转化为有据回答和/或真实、经过权限校验的平台操作。

| 术语 | 在本系统中的含义 |
| --- | --- |
| **智能体 Agent** | 持久化配置（`agents` 表），含 `mode`、`system_prompt`、`kb_ids`、`model`、`temperature`、`enabled` |
| **查询型 query** | `mode=query`：基于检索的有据问答，**不向模型提供任何工具** |
| **操作型 act** | `mode=act`：工具驱动的操作（提交表单、运行流程、查询记录） |
| **混合型 hybrid** | `mode=hybrid`：同时具备知识 grounding 与工具执行能力 |
| **工具 Tool** | 在 `services/mcp_tools.py` 声明的能力，带 JSON Schema 输入契约与所需权限 |
| **ReAct 循环** | `llm.run_agent()` 的推理/行动循环：模型 → `tool_calls` → 工具执行 → `role=tool` 结果 → 最终回答 |
| **RAG** | 基于本地 BM25 的检索增强生成，检索结果注入 `[Knowledge Context]` |
| **有据回答 Grounding** | 回答必须引用检索片段；工具结果绝不编造 |

## 2. AI 能力地图

```mermaid
flowchart TB
    subgraph Entry[入口]
        UI[AI 智能体页面<br/>POST /api/v1/agents/{id}/chat]
        MCPC[MCP 客户端<br/>/mcp tools/call]
        REST[REST 调用台<br/>POST /api/v1/mcp/invoke]
        WF[流程 AI 节点<br/>workflow_engine]
    end
    subgraph Core[AI 核心]
        RT[LLM Runtime<br/>mock / openai 兼容 / agentscope]
        RA[ReAct 编排器<br/>llm.run_agent]
        RG[RAG<br/>rag.search + build_context]
        REG[★ 工具注册表<br/>mcp_tools.TOOL_SPECS]
    end
    subgraph Data[平台状态]
        DB[(SQLite<br/>表单 · 流程 · 知识库 · 用户)]
        AUD[(audit_logs · conversations)]
    end

    UI --> RA
    MCPC --> REG
    REST --> REG
    WF --> RG
    RA --> RT
    RA --> RG
    RA --> REG
    REG --> DB
    RG --> DB
    RA --> AUD
    REG --> AUD
```

三个消费方（MCP 客户端、AI 智能体、REST 调用台）共享**同一**注册表；流程中的 `ai` 节点亦可访问知识层。这正是"智能体能真正提交表单，而不是只描述表单"的结构性保证。

## 3. 分层架构

| 层 | 模块 | 职责 | 依赖 |
| --- | --- | --- | --- |
| L4 展现 | `pages/Agents.tsx`、`pages/McpSkills.tsx` | 对话、工具步骤可视化、来源引用、调用台 | `lib/api.ts` |
| L3 编排 | `services/llm.py::run_agent` | Prompt 组装、ReAct 循环、结果摘要 | L2、L1 |
| L2 能力 | `services/mcp_tools.py` | 工具声明、Schema、权限闸口、分派 | `db`、`rag`、`workflow_engine` |
| L1 知识 | `services/rag.py` | 分词、分块、BM25、上下文拼装 | `db` |
| L0 运行时 | `services/llm.py::chat` + 后端 | 模型 I/O、工具调用协议、降级 | `httpx`、`agentscope` |
| 治理 | `deps.py`、`main.py::MCPAuthASGIMiddleware` | 身份绑定、RBAC、审计 | — |

## 4. LLM 运行时（`services/llm.py`）

### 4.1 后端与降级链

`chat(messages, tools, temperature)` 按 `LLM_PROVIDER` 选择后端：

```
agentscope   ──(当 AGENTSCOPE_ENABLED && LLM_API_KEY && 导入成功)──┐
                                                                   ├─→ 失败 / 无 Key ─┐
openai-compatible / openai / agentscope ──(当 LLM_API_KEY)────────┘                  │
                                                                                    ▼
                                                            mock（始终可用，离线）
```

| 后端 | 实现 | 使用时机 | 工具调用 |
| --- | --- | --- | --- |
| `mock`（默认） | `_mock_chat()`：确定性正则意图识别 + `_grounded_answer()` / `_summarize_tool_result()` | 无 API Key；所有演示离线可用 | 支持，产出 OpenAI 格式 `tool_calls` |
| `openai-compatible` | `_http_chat()` → `POST {LLM_BASE_URL}/chat/completions`，携带 `tools`、`tool_choice=auto`，60 s 超时 | 设置 `LLM_API_KEY` | 支持，原生 function calling |
| `agentscope` | `_agentscope_chat()` 构造 `agentscope.model.OpenAIChatModel`，通过签名反射过滤不支持的参数 | `AGENTSCOPE_ENABLED=true` + Key + 包可用 | 不支持（纯文本）；需要工具循环时降级到 HTTP 路径 |

`describe()` 为 `GET /api/v1/agents/meta/runtime` 提供数据：provider、model、temperature、AgentScope 可用性/版本/模块、编排方式、工具数量、是否配置 Key（仅布尔值）。

### 4.2 配置

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | 后端选择 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | chat-completions 基址 |
| `LLM_API_KEY` | `""` | 启用真实后端（不写日志，仅暴露 `has_api_key`） |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名，可按智能体覆盖 |
| `LLM_TEMPERATURE` | `0.3` | 采样温度，可按智能体覆盖 |
| `AGENTSCOPE_ENABLED` | `true` | 允许 AgentScope 适配器 |
| `RAG_TOP_K` | `4` | 检索深度 |

全部配置来自 `config.py` 的冻结 `Settings` dataclass（`python-dotenv`）。

## 5. ReAct 编排（`run_agent`）

### 5.1 算法

```
输入  agent, message, history, user, max_rounds=5
1  hits    ← rag.search(message, agent.kb_ids 或 None, top_k=RAG_TOP_K)
2  context ← rag.build_context(hits)                      # [Knowledge Context]
3  tools   ← mcp_tools.list_tools("openai") 当 agent.mode ∈ {act, hybrid}，否则 None
4  system  ← Prompt 模板（§8）：智能体配置 + 工具名 + 规则 + 上下文
5  messages← [system] + 最近 6 轮历史（user/assistant）+ [当前 user 消息]
6  FOR round IN 1..max_rounds:
       resp ← await chat(messages, tools, agent.temperature)
       若 resp.tool_calls 为空: answer ← resp.content; BREAK
       追加 assistant(tool_calls)
       对每个 call:
           result ← mcp_tools.call_tool(name, args, user)   # RBAC + ContextVar
           steps.append({tool, arguments, result})
           追加 role=tool 消息（JSON 结果）
7  若无 answer: answer ← _summarize_tool_result(messages, message)
8  输出 {answer, steps, sources, model, provider, orchestration}
```

`history` 截取最近 6 轮；`max_rounds=5` 同时约束延迟与非预期的工具级联。工具异常被捕获为 `{"error": str(exc)}` 并回注给模型，而不是中断请求。

### 5.2 输出契约

```json
{
  "answer": "最终自然语言回答",
  "steps": [{"tool": "run_workflow", "arguments": {"code": "..."}, "result": {}}],
  "sources": [{"doc_id": 12, "title": "Leave Policy", "score": 3.812}],
  "model": "gpt-4o-mini",
  "provider": "mock | openai-compatible | agentscope",
  "orchestration": "ReAct tool loop (AgentScope-compatible)"
}
```

路由把本轮对话持久化到 `conversations`，并返回 `steps` + `sources`，供界面渲染**可见的工具调用步骤**与**来源引用**。

### 5.3 Mock 意图识别

`_intent_tool_calls()` 把中英双语表述映射为工具调用，每轮最多 3 个（列表类正则特意加锚，避免多意图误触发）。`_summarize_tool_result()` 把最近 3 条工具消息渲染成中英可读摘要，对 `forms`、`workflows`、`records`、`hits`、`instance_id`、`submission_id`、`users` 与平台统计分别设有分支。

### 5.4 意图规划与 schema 驱动的信息收集（`services/agent_intents.py`）

在 ReAct 循环之前，`plan(message, user, context)` 先对每轮消息分类：**`collect`**（「帮我创建一个 xxx 流程」）返回带动态 `FormField[]` schema 的 `action_request`，schema 来自绑定表单的 `form_rules.render_schema()`，且**不产生任何副作用**；**`tool`**（「我是谁」「我的权限」「查询我的审批及进度」「我发起的流程」「有哪些可发起的流程」）调用一个自身范围工具并生成自然语言摘要；**`chat`** 回退到 ReAct / RAG。查询类措辞在创建意图之前被拦截，避免「我发起的流程」被误判为创建流程。

`POST /agents/{id}/chat` 返回 `action_request`，前端渲染 `SchemaForm` 卡片，提交到 `POST /agents/{id}/actions` 后才真正执行并追加到同一会话。这与认证分享页保持一致的「规划 → 收集 → 确认 → 执行」边界。详见 [WFP-001 §5](workflow-portal-and-data-scopes.md)。

## 6. 统一工具注册表（`services/mcp_tools.py`）

### 6.1 声明

20 个工具（原有 12 个 + 新增 8 个自助/schema 工具）各只声明一次：`{name, description, inputSchema}`，其中 `inputSchema` 为严格 JSON Schema 对象（`additionalProperties: false`、显式 `required`）。`PERMISSION_MAP` 绑定工具与 RBAC 权限，`HANDLERS` 绑定工具与纯 Python 函数。

| 工具 | 所需权限 | 效果 |
| --- | --- | --- |
| `list_forms`、`get_form`、`query_records` | `form:read` | 读取表单定义 / 提交记录 |
| `submit_form` | `form:submit` | **写**：校验必填项、插入提交记录 |
| `list_workflows`、`get_workflow`、`get_workflow_instance` | `workflow:read` | 读取 DAG 与实例日志 |
| `run_workflow` | `workflow:run` | **写**：校验图、执行、持久化实例 |
| `list_collections`、`search_knowledge` | `knowledge:read` | 读取集合 / BM25 检索 |
| `list_users` | `rbac:read` | 读取用户（`password_hash` 恒为 `null`） |
| `get_stats` | `dashboard:view` | 读取平台计数 |
| `who_am_i`、`my_approvals`、`my_submissions`、`my_instances` | 自身上下文 | **仅绑定用户**的身份 / 审批 / 提交 / 实例 |
| `list_startable_workflows`、`get_form_schema` | `workflow:read`、`form:read` | 门户目录与动态 `FormField[]` schema |
| `start_workflow_instance`、`submit_form_data` | `workflow:run`、`form:submit` | **写入** — 自身范围动作执行 |

### 6.2 分派与身份隔离

```python
def call_tool(name, args=None, user=None):
    if name not in HANDLERS: raise ValueError(...)
    effective_user = user if user is not None else current_user()   # ContextVar
    if effective_user:
        needed = PERMISSION_MAP.get(name)
        if needed and not has_permission(effective_user, needed):
            raise PermissionError(...)
    ...
    return HANDLERS[name](args or {})
```

- `bind_user()` / `current_user()` 使用 `contextvars.ContextVar`，并发请求（含 MCP 会话）之间不会串身份。
- `list_tools(fmt)` 从同一份 specs 输出 **MCP** 形态（`{name, description, inputSchema}`）或 **OpenAI function-calling** 形态（`{type:"function", function:{...}}`）。
- `as_mcp_content()` 把结果包装为 MCP `content` + `structuredContent` + `isError:false`。

### 6.3 三个消费方

| 消费方 | 路径 | 身份 |
| --- | --- | --- |
| MCP 服务 | `mcp_server.py` → `call_tool` | `MCPAuthASGIMiddleware` 绑定 Bearer；允许匿名 |
| AI 智能体 | `llm.run_agent()` → `call_tool(name, args, user)` | 当前对话登录用户（显式传参） |
| REST 调用台 | `POST /api/v1/mcp/invoke` | `Depends(require("mcp:invoke"))` + 绑定用户 |

## 7. RAG 流水线（`services/rag.py`）

### 7.1 阶段

1. **分词** — 英文按 `[a-z0-9]+` 取词；每段中文切为**单字 + 重叠双字 bigram**，从而支持中英混合查询。
2. **分块** — `chunk_text(text, size=480)` 先按空行切分，再按集合的 `chunk_size` 打包段落，超长段落强制切分。`index_document()` 把 `chunks` 以 JSON 持久化并置 `status='indexed'`。
3. **检索** — `search(query, collection_ids, top_k=4)` 在 `status='indexed'` 文档上计算 BM25：

$$\text{score}=\sum_{t\in q}\text{IDF}(t)\cdot\frac{f(t,D)\,(k_1+1)}{f(t,D)+k_1\left(1-b+b\cdot\frac{|D|}{\text{avgdl}}\right)},\quad k_1=1.5,\ b=0.75$$

$$\text{IDF}(t)=\ln\left(1+\frac{N-\text{df}(t)+0.5}{\text{df}(t)+0.5}\right)$$

4. **片段** — 以首个命中词为中心截取 320 字符窗口，两端加省略号。
5. **拼装** — `build_context(hits, max_chars=2200)` 渲染 `[n] 标题 (集合, 分数)\n片段` 区块；无命中时返回 `No relevant knowledge base documents were retrieved.`

### 7.2 参数

| 参数 | 值 | 位置 |
| --- | --- | --- |
| 分块大小 | 480 字符（可按集合覆盖） | `chunk_text` / `kb_collections.chunk_size` |
| `k1`、`b` | `1.5`、`0.75` | `rag.search` |
| `top_k` | 4（`RAG_TOP_K`，MCP 工具上限 10） | `settings` / `search_knowledge` |
| 上下文预算 | 2200 字符 | `build_context` |
| 返回来源 | `doc_id`、`title`、`score` | `run_agent` 输出 |

**理由**：无需 embedding 服务、无需向量库，确定性且完全离线；`search` 是生产替换为向量库的唯一切入点（见 [ADR-0004](adr/0004-sqlite-and-local-bm25.md)）。

## 8. Prompt 规范

系统提示在 `run_agent()` 中确定性组装：

```
{system_prompt 或 "You are a helpful platform assistant."}

[Agent] name={name} mode={mode} model={model}
[Available tools] {逗号分隔的工具名}
[Rules] Use tools for live platform data and actions. Never invent tool results.
        Answer in the same language as the user. Cite knowledge sources when used.

[Knowledge Context]
{build_context(hits)}
```

| 规则 | 落实方式 |
| --- | --- |
| 绝不编造工具结果 | 所有数据来自 `call_tool`；mock 摘要只读取真实 `role=tool` 消息 |
| 语言一致 | `_is_zh()` 检测 ≥2 个 CJK 字符，回答与摘要自动切换中英 |
| 引用来源 | 回答同时返回 `sources[]` 给界面 |
| 最小权限 | `query` 模式 `tools=None`；工具调用仍按 `PERMISSION_MAP` 复核 |
| 成本可控 | `max_rounds=5`、历史 6 轮、`top_k=4`、上下文 2200 字符 |

## 9. MCP 暴露（`mcp_server.py`）

### 9.1 双传输

| 后端 | 触发条件 | 能力 |
| --- | --- | --- |
| **fastmcp**（主） | `MCP_ENABLED=true` 且 `from fastmcp import FastMCP` 成功 | 真实 MCP SDK，由带类型的 `@mcp.tool` 签名生成 JSON Schema，`/mcp` streamable HTTP，`stateless_http` 与 `json_response` 由配置控制 |
| **内置 JSON-RPC**（回退） | SDK 缺失 / 导入异常 | `initialize`、`ping`、`tools/list`、`tools/call`、`resources/list|read|templates/list`、`prompts/list|get`、通知 |

`build_mcp()` 返回 `(routes, http_app, mode)`；`main.py` 在 FastAPI lifespan 内执行 `async with mcp_http_app.lifespan(mcp_http_app)`（`StreamableHTTPSessionManager` 要求），并把 MCP 路由追加到 `app.router.routes`。

### 9.2 协议面

| 方法 | 结果 |
| --- | --- |
| `initialize` | `protocolVersion`（协商）、`capabilities{tools,prompts,resources}`、`serverInfo{name,version}`、`instructions` |
| `tools/list` | 来自 `TOOL_SPECS` 的 20 个工具，外加 `call_remote_tool` 桥接工具 |
| `tools/call` | 经 RBAC 校验的 handler 结果，包装为 MCP content |
| `resources/list` | `platform://stats`、`platform://forms/{code}`、`platform://workflows/{code}` |
| `prompts/list` | `analyze_workflow`、`answer_from_kb` |

### 9.3 鉴权

`MCPAuthASGIMiddleware` 是纯 ASGI 包装层：对 `/mcp` 请求解析可选 Bearer Token，经 `security.jwt_decode` + `deps._load_user` 加载用户，并调用 `mcp_tools.bind_user(user)`。无 Token 时允许匿名只读；带 Token 时每次工具调用都做 RBAC 校验。既让外部 MCP 客户端可用，又不绕过平台授权（见 [ADR-0005](adr/0005-mcp-transport-and-auth.md)）。

### 9.4 MCP 服务与技能两套独立注册表

MCP 服务与技能是**独立实体，各自拥有路由、数据表与生命周期**（见 [ADR-0008](adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md) 与 [MCP-001](mcp-skills.md)）：

| 注册表 | 数据表 | 路由 | 职责 |
| --- | --- | --- | --- |
| MCP 服务 | `mcp_servers` | `/mcp/servers` | 连接配置（`transport`、`endpoint` / `command`、`auth_config`）、`probe()` + `sync()` 工具发现、健康/状态、`invoke_on_server()` |
| 技能 | `mcp_skills` | `/skills` | 生命周期（`installed` / `disabled` / `uninstalled` / `error`）、目录、manifest、可编辑文件、可选 `server_id` 关联 |

`mcp_skills.server_id` 是可空的非拥有型关联：删除服务不会删除其技能，反之亦然。`services/mcp_servers.py::declared_tools(server_ids)` 把已启用服务声明的工具合并进 `mcp_tools.list_tools(include_external=True)`；`call_remote_tool` MCP 桥接工具以 `mcp:invoke` 权限把调用转发给所属服务，并写入 `target=server:<code>` 的日记记录。`mcp_tools.agent_tools(agent, fmt)` 按智能体的 `server_ids` / `skill_ids` 收窄 ReAct 工具集，未绑定的服务既不可见也不可调用。平台工具与外部工具仍保持命名空间隔离。

### 9.5 技能生命周期与可编辑文件

独立的技能注册表（`mcp_skills`，由 `/skills` 提供）新增 `status` 状态机（`installed` / `disabled` / `uninstalled` / `error`）、`version`、`source`、`manifest`、安装时间戳，以及可空的 `server_id` 关联。`GET /skills/catalog` 提供 5 个可安装模板；`POST /skills/install` 安装技能并在 `mcp_skill_files` 中生成 5 个可编辑文件，同时镜像到 `data/skills/<code>/`。界面支持 `enable` / `disable` / `uninstall` / `reinstall` 以及完整的文件增删查改（含路径穿越校验）。详见 [MCP-001](mcp-skills.md) 与 [ADR-0007](adr/0007-mcp-skill-lifecycle-and-journal.md)。

### 9.6 调用日记

`mcp_call_logs` 记录 `mcp`、`rest`、`agent`、`internal` 四类来源的每次工具调用，并通过 `target` 列标识外部调用所属的 MCP 服务（`server:<code>`）。`mcp_tools.call_tool()` 在 `finally` 中写入参数、结果预览、状态、错误与耗时（尽力而为，不影响调用）；ASGI 中间件一次性缓冲 JSON-RPC 请求体，以记录 `initialize`、`tools/list` 等非工具方法。`GET /mcp/calls`、`/calls/stats`、`/calls/export`、`/calls/{id}` 与 `DELETE /mcp/calls` 支撑日记看板。内部仪表盘聚合通过 `journal=False` 避免产生噪音。

## 10. 治理与安全边界

| 风险 | 缓解措施 |
| --- | --- |
| LLM 越权操作 | `call_tool` 用真实用户复核 `PERMISSION_MAP`；`query` 模式不提供工具 |
| 请求间身份串漏 | `ContextVar` 绑定 + 显式 `user` 参数；`try/finally` 复位上下文 |
| 知识内容提示注入 | 检索文本置于明确分隔的 `[Knowledge Context]` 区块，配合"绝不编造工具结果"规则；写工具仍需 RBAC |
| 工具级联失控 | `max_rounds=5`、mock 每轮 ≤3 意图、`top_k` 上限 10、上下文上限 2200 字符 |
| 密钥泄漏 | `/auth/providers` 不返回原始配置；`list_users` 把 `password_hash` 置空；`ai_providers.api_key` 只写，响应仅暴露 `has_api_key` / `api_key_masked` |
| 操作不可追溯 | `deps.audit()` 记录所有写操作；会话持久化智能体对话 |
| 外部调用无界 | `httpx` 60 s 超时；失败降级到 `mock` 而非让请求失败 |

**生产残留风险**：真实 LLM 仍可能生成错误的工具参数——需在边界增加 JSON Schema 校验与破坏性工具的人工审批；WebAuthn 与 SSO demo 模式必须替换为真实凭据与 TLS。

## 11. 智能体配置模型

| 字段 | 类型 | 默认值 / 来源 |
| --- | --- | --- |
| `code`、`name`、`description` | string | 界面 |
| `mode` | `query \| act \| hybrid` | 决定是否提供工具 |
| `system_prompt` | text | 原样注入系统提示首行 |
| `kb_ids` | JSON 数组（集合 id） | 限定 RAG 范围（`None` = 全部集合） |
| `skill_ids` | JSON 数组（技能 id） | 限定技能声明的工具 |
| `server_ids` | JSON 数组（MCP 服务 id） | 限定已启用服务提供的外部工具 |
| `workflow_ids` | JSON 数组（流程 id） | 声明式流程绑定 |
| `model`、`temperature` | string / float | 覆盖 `settings` / `llm` 类别默认项 |
| `enabled` | int | 界面可见性 / 可用性 |
| conversations | JSON 轮次 | `conversations` 表，回放最近 6 轮 |

`GET /agents/meta/bindings` 一次返回四类可绑定资源（知识库集合、技能、MCP 服务、工作流），使创建对话框可提供带搜索的多选绑定。创建/更新时 `routers/agents.py::_clean_ids()` 会丢弃已不存在的 id，避免悬空绑定；运行时再由 `mcp_tools.agent_tools()` 落实该绑定。

## 12. 可观测性与持久化

- `GET /api/v1/agents/meta/runtime` — provider、model、AgentScope 模块、工具数、`model_providers` 元数据。
- `GET /api/v1/agents/meta/bindings` — 可绑定的知识库 / 技能 / MCP 服务 / 工作流资源。
- `GET /api/v1/ai/providers/meta` — AI 模型类别与厂商。
- `GET /api/v1/knowledge/formats` — 支持的上传格式与解析器可用性。
- `GET /api/v1/mcp/status` — MCP 模式（`fastmcp` / `builtin-jsonrpc`）、工具数、服务/技能状态。
- 每次对话响应的 `steps[]` — 完整工具名、参数与结果。
- `sources[]` — 带 BM25 分数的检索证据。
- `audit_logs` — 写操作的 actor/action/resource/detail/ip/level/timestamp。
- `conversations` — 持久化对话历史。
- `mcp_call_logs` — 每次工具调用的来源、参数、结果预览、状态与耗时（日记看板、CSV 导出）。

## 13. 测试覆盖

`backend/tests/smoke.py` 含专门的 AI 断言：中英混合 RAG 检索、文档自动索引、query 智能体返回 `sources`、act/hybrid 智能体执行 ≥2 次真实工具调用、工具结果摘要、`/mcp` 的 `tools/list` 与 `tools/call`、REST `/mcp/invoke`、第三方技能同步，以及工具调用的 RBAC 拒绝。合计 **189 passed / 0 failed**（调用日记与技能生命周期新增 63 项断言：记录、统计、CSV 导出、清空、目录、安装、文件增删查改、路径穿越、启用/禁用/卸载/重装）。

## 14. 生产升级路径

| 当前 | 升级方式 |
| --- | --- |
| `mock` 意图识别 | 设置 `LLM_PROVIDER=openai-compatible`（或 `agentscope`）+ `LLM_API_KEY`，或在 `/ai/providers` 中把某个 `llm` 配置设为默认（运行时覆盖 `LLM_*`）；ReAct 循环与工具 Schema 已与模型无关 |
| SQLite 上的 BM25 | 用向量/embedding 库替换 `rag.search`，保持 `build_context` 契约 |
| 流程同步执行 | 把 `run_workflow` handler 迁到任务队列 |
| 匿名 MCP 只读 | 强制 Bearer Token，增加客户端 scope 与限流 |
| 工具立即执行 | 为 `submit_form` / `run_workflow` 增加人工审批步骤 |
| 缺少 LLM 可观测 | 记录 prompt/响应元数据、token 用量、工具延迟 |

## 15. 可追溯性

| 设计要素 | 代码 | 验证 |
| --- | --- | --- |
| LLM 运行时与降级 | `services/llm.py::chat`、`_mock_chat`、`_http_chat`、`_agentscope_chat` | 冒烟：智能体对话 |
| ReAct 循环 | `services/llm.py::run_agent` | 冒烟：act/hybrid 多工具 |
| 工具注册表 | `services/mcp_tools.py` | 冒烟：invoke、tools/list、RBAC |
| RAG | `services/rag.py` | 冒烟：中英检索、重建索引 |
| MCP 双传输 | `mcp_server.py`、`main.py` | 冒烟：initialize/list/call |
| MCP 服务 / 技能独立注册表 | `services/mcp_servers.py`、`routers/mcp_servers.py`、`routers/skills.py` | 冒烟：独立 CRUD、同步、关联隔离 |
| AI 模型服务 | `services/model_providers.py`、`routers/ai_providers.py` | 冒烟：类别、默认项、密钥脱敏、`effective_llm()` |
| 知识库上传 | `services/documents.py`、`routers/knowledge.py` | 冒烟：docx/xlsx/pdf/csv/md 解析、格式拒绝、stats |
| 智能体绑定 | `routers/agents.py`、`services/mcp_tools.py::agent_tools` | 冒烟：`/meta/bindings`、创建/更新清理、绑定后对话 |
| 治理 | `deps.py`、`main.py::MCPAuthASGIMiddleware` | 冒烟：RBAC 拒绝 |

相关决策：[ADR-0002](adr/0002-single-tool-registry.md)、[ADR-0003](adr/0003-offline-first-llm-runtime.md)、[ADR-0004](adr/0004-sqlite-and-local-bm25.md)、[ADR-0005](adr/0005-mcp-transport-and-auth.md)、[ADR-0007](adr/0007-mcp-skill-lifecycle-and-journal.md)、[ADR-0008](adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md)。
