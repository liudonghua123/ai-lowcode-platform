# AI System Design

| Field | Value |
| --- | --- |
| Document ID | `AI-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Audience | AI engineers, backend engineers, reviewers |
| 中文 | [ai-design.zh-CN.md](ai-design.zh-CN.md) |
| Related | [System Architecture](architecture.md) · [Security Architecture](security.md) · [API & MCP Reference](api-reference.md) · [ADR index](adr/README.md) |

## 1. Scope and terminology

This document specifies the **as-built AI subsystem**: how a natural-language request becomes a grounded answer and/or a real, permission-checked platform action.

| Term | Meaning in this system |
| --- | --- |
| **Agent** | A persisted configuration (`agents` table) with `mode`, `system_prompt`, `kb_ids`, `model`, `temperature`, `enabled`. |
| **Query agent** | `mode=query` — retrieval-grounded answering; **no tools** are offered to the model. |
| **Act agent** | `mode=act` — tool-driven operations (submit a form, run a workflow, query records). |
| **Hybrid agent** | `mode=hybrid` — both knowledge grounding and tool execution. |
| **Tool** | A capability declared in `services/mcp_tools.py` with a JSON Schema input contract and a required permission. |
| **ReAct loop** | The `llm.run_agent()` reasoning/acting cycle: model → `tool_calls` → tool execution → `role=tool` results → final answer. |
| **RAG** | Retrieval-Augmented Generation via local BM25 over knowledge documents, injected as `[Knowledge Context]`. |
| **Grounding** | Answers must cite retrieved excerpts; tool results are never fabricated. |

## 2. AI capability map

```mermaid
flowchart TB
    subgraph Entry["Entry points"]
        UI[AI Agents page<br/>POST /api/v1/agents/{id}/chat]
        MCPC[MCP client<br/>/mcp tools/call]
        REST[REST console<br/>POST /api/v1/mcp/invoke]
        WF[Workflow AI node<br/>workflow_engine]
    end
    subgraph Core["AI core"]
        RT[LLM Runtime<br/>mock / openai-compatible / agentscope]
        RA[ReAct orchestrator<br/>llm.run_agent]
        RG[RAG<br/>rag.search + build_context]
        REG[★ Tool Registry<br/>mcp_tools.TOOL_SPECS]
    end
    subgraph Data["Platform state"]
        DB[(SQLite<br/>forms · workflows · kb · users)]
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

Three consumers (MCP clients, AI agents, REST console) share **one** registry. A workflow `ai` node can also reach the knowledge layer. This is the structural guarantee that an agent can *actually* submit a form rather than merely describe it.

## 3. Layered architecture

| Layer | Module | Responsibility | Depends on |
| --- | --- | --- | --- |
| L4 Presentation | `pages/Agents.tsx`, `pages/McpSkills.tsx` | Chat, tool-step visualization, source citations, invocation console | `lib/api.ts` |
| L3 Orchestration | `services/llm.py::run_agent` | Prompt assembly, ReAct loop, result summarization | L2, L1 |
| L2 Capability | `services/mcp_tools.py` | Tool declaration, schema, permission gate, dispatch | `db`, `rag`, `workflow_engine` |
| L1 Knowledge | `services/rag.py` | Tokenize, chunk, BM25, context assembly | `db` |
| L0 Runtime | `services/llm.py::chat` + backends | Model I/O, tool-call protocol, degradation | `httpx`, `agentscope` |
| Governance | `deps.py`, `main.py::MCPAuthASGIMiddleware` | Identity binding, RBAC, audit | — |

## 4. LLM runtime (`services/llm.py`)

### 4.1 Backends and degradation chain

`chat(messages, tools, temperature)` resolves the backend by `LLM_PROVIDER`:

```
agentscope   ──(if AGENTSCOPE_ENABLED && LLM_API_KEY && import works)──┐
                                                                       ├─→ failure / no key ─┐
openai-compatible / openai / agentscope ──(if LLM_API_KEY)────────────┘                    │
                                                                                          ▼
                                                                      mock (always available, offline)
```

| Backend | Implementation | When used | Tool calls |
| --- | --- | --- | --- |
| `mock` (default) | `_mock_chat()` — deterministic regex intent recognition + `_grounded_answer()` / `_summarize_tool_result()` | No API key; every demo works offline | Yes — emits OpenAI-shaped `tool_calls` |
| `openai-compatible` | `_http_chat()` → `POST {LLM_BASE_URL}/chat/completions`, `tools`, `tool_choice=auto`, 60 s timeout | `LLM_API_KEY` set | Yes — native function calling |
| `agentscope` | `_agentscope_chat()` builds `agentscope.model.OpenAIChatModel`; signature introspection filters unsupported kwargs | `AGENTSCOPE_ENABLED=true` + key + package | No (text-only); degrades to HTTP path for tool loops |

`describe()` powers `GET /api/v1/agents/meta/runtime`: provider, model, temperature, AgentScope availability/version/modules, orchestration label, tool count, whether a key is configured.

### 4.2 Configuration

| Env var | Default | Effect |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | Backend selection |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Chat-completions base URL |
| `LLM_API_KEY` | `""` | Enables real backends (never logged; `has_api_key` boolean only) |
| `LLM_MODEL` | `gpt-4o-mini` | Model name, overridable per agent |
| `LLM_TEMPERATURE` | `0.3` | Sampling temperature, overridable per agent |
| `AGENTSCOPE_ENABLED` | `true` | Allow the AgentScope adapter |
| `RAG_TOP_K` | `4` | Retrieval depth |

All settings come from the frozen `Settings` dataclass (`config.py`, `python-dotenv`).

## 5. ReAct orchestration (`run_agent`)

### 5.1 Algorithm

```
INPUT  agent, message, history, user, max_rounds=5
1  hits    ← rag.search(message, agent.kb_ids or None, top_k=RAG_TOP_K)
2  context ← rag.build_context(hits)                      # [Knowledge Context]
3  tools   ← mcp_tools.list_tools("openai")  iff agent.mode ∈ {act, hybrid}, else None
4  system  ← prompt template (§8) with agent config, tool names, rules, context
5  messages← [system] + last 6 history turns (user/assistant) + [user message]
6  FOR round IN 1..max_rounds:
       resp ← await chat(messages, tools, agent.temperature)
       IF resp.tool_calls is empty: answer ← resp.content; BREAK
       append assistant(tool_calls)
       FOR each call:
           result ← mcp_tools.call_tool(name, args, user)   # RBAC + ContextVar
           steps.append({tool, arguments, result})
           append role=tool message with JSON result
7  IF no answer: answer ← _summarize_tool_result(messages, message)
8  OUTPUT {answer, steps, sources, model, provider, orchestration}
```

`history` is capped at the last 6 turns; `max_rounds=5` bounds both latency and unintended tool cascades. Tool exceptions are captured as `{"error": str(exc)}` and fed back to the model rather than aborting the request.

### 5.2 Output contract

```json
{
  "answer": "string — final natural-language answer",
  "steps": [{"tool": "run_workflow", "arguments": {"code": "..."}, "result": {}}],
  "sources": [{"doc_id": 12, "title": "Leave Policy", "score": 3.812}],
  "model": "gpt-4o-mini",
  "provider": "mock | openai-compatible | agentscope",
  "orchestration": "ReAct tool loop (AgentScope-compatible)"
}
```

The router persists the turn to `conversations` and returns `steps` + `sources` so the UI can render **visible tool-call steps** and **source citations**.

### 5.3 Mock intent recognition

`_intent_tool_calls()` maps bilingual phrasing to tool calls with a cap of 3 per turn (list-intent regexes are deliberately anchored to avoid multi-intent false positives). `_summarize_tool_result()` renders the last 3 tool messages into a bilingual human-readable summary, with dedicated branches for `forms`, `workflows`, `records`, `hits`, `instance_id`, `submission_id`, `users` and platform stats.

## 6. Unified tool registry (`services/mcp_tools.py`)

### 6.1 Declaration

Each of the 12 tools is declared once as `{name, description, inputSchema}` where `inputSchema` is a strict JSON Schema object (`additionalProperties: false`, explicit `required`). `PERMISSION_MAP` binds each tool to an RBAC permission; `HANDLERS` binds it to a pure Python function.

| Tool | Required permission | Effect |
| --- | --- | --- |
| `list_forms`, `get_form`, `query_records` | `form:read` | Read form definitions / submissions |
| `submit_form` | `form:submit` | **Write** — validate required fields, insert submission |
| `list_workflows`, `get_workflow`, `get_workflow_instance` | `workflow:read` | Read DAGs and instance logs |
| `run_workflow` | `workflow:run` | **Write** — validate graph, execute, persist instance |
| `list_collections`, `search_knowledge` | `knowledge:read` | Read collections / BM25 retrieval |
| `list_users` | `rbac:read` | Read users (password hash always `null`) |
| `get_stats` | `dashboard:view` | Read platform counters |

### 6.2 Dispatch and identity isolation

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

- `bind_user()` / `current_user()` use a `contextvars.ContextVar`, so concurrent requests (including MCP sessions) do not leak identity.
- `list_tools(fmt)` emits **MCP** shape (`{name, description, inputSchema}`) or **OpenAI function-calling** shape (`{type:"function", function:{...}}`) from the same specs.
- `as_mcp_content()` wraps a result into MCP `content` + `structuredContent` + `isError:false`.

### 6.3 Three consumers

| Consumer | Path | Identity |
| --- | --- | --- |
| MCP server | `mcp_server.py` → `call_tool` | `MCPAuthASGIMiddleware` binds bearer token; anonymous allowed |
| AI agent | `llm.run_agent()` → `call_tool(name, args, user)` | The logged-in chat user (explicit argument) |
| REST console | `POST /api/v1/mcp/invoke` | `Depends(require("mcp:invoke"))` + bound user |

## 7. RAG pipeline (`services/rag.py`)

### 7.1 Stages

1. **Tokenize** — English `[a-z0-9]+` words; each Chinese run is split into **unigrams + overlapping bigrams**, so mixed zh/en queries match.
2. **Chunk** — `chunk_text(text, size=480)` splits on blank lines, packs paragraphs up to the collection's `chunk_size`, and hard-splits oversized paragraphs. `index_document()` persists `chunks` as JSON and sets `status='indexed'`.
3. **Retrieve** — `search(query, collection_ids, top_k=4)` computes BM25 over `status='indexed'` documents:

$$\text{score}=\sum_{t\in q}\text{IDF}(t)\cdot\frac{f(t,D)\,(k_1+1)}{f(t,D)+k_1\left(1-b+b\cdot\frac{|D|}{\text{avgdl}}\right)},\quad k_1=1.5,\ b=0.75$$

$$\text{IDF}(t)=\ln\left(1+\frac{N-\text{df}(t)+0.5}{\text{df}(t)+0.5}\right)$$

4. **Snippet** — 320-character window around the first matching term, with ellipses.
5. **Assemble** — `build_context(hits, max_chars=2200)` renders `[n] Title (collection, score)\nSnippet` blocks, or `No relevant knowledge base documents were retrieved.`

### 7.2 Parameters

| Parameter | Value | Location |
| --- | --- | --- |
| Chunk size | 480 chars (collection-overridable) | `chunk_text` / `kb_collections.chunk_size` |
| `k1`, `b` | `1.5`, `0.75` | `rag.search` |
| `top_k` | 4 (`RAG_TOP_K`, max 10 via MCP tool) | `settings` / `search_knowledge` |
| Context budget | 2200 chars | `build_context` |
| Sources returned | `doc_id`, `title`, `score` | `run_agent` output |

**Rationale:** no embedding service, no vector DB, deterministic and fully offline; the `search` function is the single swap point for a production vector store (see [ADR-0004](adr/0004-sqlite-and-local-bm25.md)).

## 8. Prompt specification

The system prompt is assembled deterministically in `run_agent()`:

```
{system_prompt or "You are a helpful platform assistant."}

[Agent] name={name} mode={mode} model={model}
[Available tools] {comma-separated tool names}
[Rules] Use tools for live platform data and actions. Never invent tool results.
        Answer in the same language as the user. Cite knowledge sources when used.

[Knowledge Context]
{build_context(hits)}
```

| Rule | Enforcement |
| --- | --- |
| Never fabricate tool results | All data comes from `call_tool`; mock summary only reads actual `role=tool` messages |
| Language parity | `_is_zh()` detects ≥2 CJK chars; answer and summaries switch en/zh |
| Cite sources | `sources[]` returned to UI alongside the answer |
| Least privilege | `query` mode receives `tools=None`; tool calls are re-checked against `PERMISSION_MAP` |
| Bounded cost | `max_rounds=5`, history 6 turns, `top_k=4`, context 2200 chars |

## 9. MCP exposure (`mcp_server.py`)

### 9.1 Dual transport

| Backend | Trigger | Capabilities |
| --- | --- | --- |
| **fastmcp** (primary) | `MCP_ENABLED=true` and `from fastmcp import FastMCP` succeeds | Real MCP SDK, JSON Schema generated from typed `@mcp.tool` signatures, streamable HTTP at `/mcp`, `stateless_http` + `json_response` from config |
| **builtin JSON-RPC** (fallback) | SDK missing / import error | `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list|read|templates/list`, `prompts/list|get`, notifications |

`build_mcp()` returns `(routes, http_app, mode)`; `main.py` runs `async with mcp_http_app.lifespan(mcp_http_app)` inside the FastAPI lifespan (required by `StreamableHTTPSessionManager`) and extends `app.router.routes` with the MCP routes.

### 9.2 Protocol surface

| Method | Result |
| --- | --- |
| `initialize` | `protocolVersion` (negotiated), `capabilities{tools,prompts,resources}`, `serverInfo{name,version}`, `instructions` |
| `tools/list` | 12 tools from `TOOL_SPECS` |
| `tools/call` | RBAC-checked handler result as MCP content |
| `resources/list` | `platform://stats`, `platform://forms/{code}`, `platform://workflows/{code}` |
| `prompts/list` | `analyze_workflow`, `answer_from_kb` |

### 9.3 Authentication

`MCPAuthASGIMiddleware` is a pure ASGI wrapper: for `/mcp` requests it decodes the optional bearer token, loads the user via `security.jwt_decode` + `deps._load_user`, and calls `mcp_tools.bind_user(user)`. With no token, read-only anonymous use is permitted; with a token, every tool call is RBAC-checked. This keeps MCP usable from external clients without bypassing platform authorization (see [ADR-0005](adr/0005-mcp-transport-and-auth.md)).

### 9.4 Third-party MCP skills

`mcp_skills` records external servers (`http` / `sse` / `stdio`), their config and synced tool lists. `POST /api/v1/mcp/skills/{id}/sync` refreshes tool catalogs; the registry UI and `/mcp/status` expose mode, tool count and provider state. Platform tools and third-party skills are kept in separate namespaces.

## 10. Governance and safety boundary

| Risk | Mitigation |
| --- | --- |
| Unauthorized action via LLM | `call_tool` re-checks `PERMISSION_MAP` with the real user; `query` mode gets no tools |
| Identity leak across requests | `ContextVar` binding + explicit `user` argument; `try/finally` resets the previous context |
| Prompt injection via knowledge content | Retrieved text is placed in a clearly delimited `[Knowledge Context]` block with an explicit "never invent tool results" rule; write tools still require RBAC |
| Runaway tool cascades | `max_rounds=5`, ≤3 intents per mock turn, `top_k` cap 10, context cap 2200 chars |
| Secret exposure | `/auth/providers` never returns raw provider config; `list_users` nulls `password_hash`; runtime exposes only `has_api_key` boolean |
| Untraceable actions | `deps.audit()` records every mutation; conversations persist agent turns |
| Unbounded external calls | 60 s `httpx` timeout; failures degrade to `mock` instead of failing the request |

**Residual risks (production):** real LLMs may still hallucinate tool arguments — add JSON-Schema validation at the boundary and human approval for destructive tools; WebAuthn and SSO demo modes must be replaced with real credentials and TLS.

## 11. Agent configuration model

| Field | Type | Default / source |
| --- | --- | --- |
| `code`, `name`, `description` | string | UI |
| `mode` | `query \| act \| hybrid` | gates tool availability |
| `system_prompt` | text | injected verbatim as the first system line |
| `kb_ids` | JSON array of collection ids | scopes RAG (`None` = all collections) |
| `model`, `temperature` | string / float | overrides `settings` |
| `enabled` | int | UI visibility / availability |
| conversations | JSON turns | `conversations` table, last 6 replayed |

## 12. Observability and persistence

- `GET /api/v1/agents/meta/runtime` — provider, model, AgentScope modules, tool count.
- `GET /api/v1/mcp/status` — MCP mode (`fastmcp` / `builtin-jsonrpc`), tool count, skills state.
- `steps[]` in every chat response — full tool name, arguments and result.
- `sources[]` — retrieval evidence with BM25 score.
- `audit_logs` — actor/action/resource/detail/ip/level/timestamp for writes.
- `conversations` — persisted chat history.

## 13. Test coverage

`backend/tests/smoke.py` includes dedicated AI assertions: RAG search with mixed zh/en query, document auto-indexing, query agent returning `sources`, act/hybrid agents executing ≥2 real tool calls, tool-result summarization, `tools/list` and `tools/call` over `/mcp`, REST `/mcp/invoke`, third-party skill sync, and RBAC denial for tool calls. Total: **47 passed / 0 failed**.

## 14. Production upgrade path

| Current | Upgrade |
| --- | --- |
| `mock` intent recognition | Set `LLM_PROVIDER=openai-compatible` (or `agentscope`) + `LLM_API_KEY`; the ReAct loop and tool schemas are already model-agnostic |
| BM25 over SQLite | Replace `rag.search` with a vector/embedding store; keep `build_context` contract |
| Synchronous workflow execution | Move `run_workflow` handler to a task queue |
| Anonymous MCP read | Require bearer token; add per-client scopes and rate limiting |
| Tool calls execute immediately | Add an approval step for `submit_form` / `run_workflow` |
| No LLM observability | Log prompt/response metadata, token usage, tool latency |

## 15. Traceability

| Design element | Code | Verified by |
| --- | --- | --- |
| LLM runtime & degradation | `services/llm.py::chat`, `_mock_chat`, `_http_chat`, `_agentscope_chat` | smoke: agent chats |
| ReAct loop | `services/llm.py::run_agent` | smoke: act/hybrid multi-tool |
| Tool registry | `services/mcp_tools.py` | smoke: invoke, tools/list, RBAC |
| RAG | `services/rag.py` | smoke: zh/en retrieval, reindex |
| MCP transports | `mcp_server.py`, `main.py` | smoke: initialize/list/call |
| Governance | `deps.py`, `main.py::MCPAuthASGIMiddleware` | smoke: RBAC denial |

Related decisions: [ADR-0002](adr/0002-single-tool-registry.md), [ADR-0003](adr/0003-offline-first-llm-runtime.md), [ADR-0004](adr/0004-sqlite-and-local-bm25.md), [ADR-0005](adr/0005-mcp-transport-and-auth.md).
