# ADR-0003: Offline-first LLM runtime with three backends and graceful degradation

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform Team |
| Related | `AI-001` §4, §5, §14 · `ADR-0002` |

## Context

The platform must be demonstrable with no external services and no API key, yet the requirement explicitly names `AgentScope` and expects real AI query/action agents. A hard dependency on a hosted LLM would break the "clone and run" experience and make the 47-assertion smoke test non-deterministic.

## Decision

Implement `services/llm.py` with a **degradation chain** driven by `LLM_PROVIDER`:

1. `agentscope` — build `agentscope.model.OpenAIChatModel` when `AGENTSCOPE_ENABLED`, an API key and the package are available; signature introspection filters unsupported kwargs.
2. `openai-compatible` — `httpx` POST to `{LLM_BASE_URL}/chat/completions` with native `tools` / `tool_choice=auto`, 60 s timeout.
3. `mock` (default) — deterministic, offline: regex-based bilingual intent recognition that emits OpenAI-shaped `tool_calls`, plus `_grounded_answer()` for knowledge questions and `_summarize_tool_result()` for tool outcomes.

Any backend failure (missing key, import error, network error, empty response) **degrades** to the next backend rather than failing the request. `describe()` exposes the effective runtime to `GET /api/v1/agents/meta/runtime` without leaking the key (only `has_api_key: bool`).

`run_agent()` wraps this in a model-agnostic ReAct loop: `max_rounds=5`, last 6 history turns, `top_k=4` retrieval, 2200-char context budget.

## Consequences

### Positive
- Every demo, screenshot and test works offline; the smoke suite is deterministic.
- Upgrading to a real model is configuration-only — tool schemas and the ReAct loop are unchanged.
- AgentScope is genuinely integrated (adapter + runtime introspection) while remaining optional.
- Bounded cost/latency via round, history and context caps.

### Negative
- `mock` is intent recognition, not generation; answers follow templates rather than free-form reasoning.
- `_mock_chat` uses regexes that can misread unusual phrasing (mitigated by anchoring list-intent patterns and capping at 3 calls per turn).
- The AgentScope adapter is text-only; tool-calling loops fall through to the HTTP backend.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Require `LLM_API_KEY` at startup | Breaks offline demo and CI |
| Ship a local small model | Large dependency, slow startup, still non-deterministic |
| Return static canned responses | Would not exercise real tool execution or RBAC |

## Verification

`GET /api/v1/agents/meta/runtime` reports provider/model/AgentScope modules. Smoke tests verify query answers with `sources`, act/hybrid agents with ≥2 tool calls, tool-result summaries and RBAC denial — all with `LLM_PROVIDER=mock`.
