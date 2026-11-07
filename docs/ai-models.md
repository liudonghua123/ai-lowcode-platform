# AI Model Services

| Field | Value |
| --- | --- |
| Document ID | `AIM-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Machine-readable source | `GET /api/v1/ai/providers/meta`, `backend/app/services/model_providers.py` |
| Related | [REST & MCP API Reference](api-reference.md) · [Data Model](data-model.md) · [AI System Design](ai-design.md) · [Security Architecture](security.md) · [ADR-0008](adr/0008-mcp-skills-split-model-providers-and-knowledge-upload.md) |

> 中文摘要：平台把 AI 能力抽象为**六类模型服务**（`llm` / `asr` / `tts` / `embedding` / `rerank` / `vision`），配置存于 `ai_providers` 表，可在界面运行时增删改与切换。每类**有且仅有一个默认项**；`api_key` 为**只写字段**，读取仅返回 `has_api_key` 与 `api_key_masked`。`llm` 默认项通过 `effective_llm()` 在运行时覆盖 `LLM_*` 环境变量，并接入 `services/llm.py` 的 ReAct 循环；`embedding` / `rerank` 默认项在知识库统计中展示，为后续向量化/重排序留出入口。当前只有 `llm` 真正驱动推理，其余类别是可配置的能力占位（见 §8 限制）。

## 1. Why a model registry

The first release read LLM settings exclusively from `LLM_*` environment variables at process start. That made it impossible to switch models from the UI and left no place to declare ASR/TTS/embedding/rerank/vision services. AIM-001 introduces a database-backed registry so:

- model services are **first-class, editable resources** with RBAC and audit;
- one **default per category** gives the runtime a single source of truth;
- secrets are never returned in full to the browser;
- non-LLM categories are declared now so knowledge/RAG and future voice features can bind to them without another schema change.

`LLM_*` environment variables remain the **bootstrap fallback**: a default `llm` provider overrides them at runtime.

## 2. Categories

`CATEGORIES` in `services/model_providers.py` drives backend validation, the `/ai/providers/meta` response and the UI tabs.

| Code | Label | Default model | API path | Purpose |
| --- | --- | --- | --- | --- |
| `llm` | Chat / LLM (对话大模型) | `gpt-4o-mini` | `/chat/completions` | Query / action agents and the ReAct loop |
| `asr` | ASR / Speech-to-Text (语音识别) | `whisper-1` | `/audio/transcriptions` | Voice input, meeting transcription |
| `tts` | TTS / Text-to-Speech (语音合成) | `tts-1` | `/audio/speech` | Spoken answers, notifications |
| `embedding` | Embedding (向量嵌入) | `text-embedding-3-small` | `/embeddings` | Knowledge vectorization / semantic retrieval |
| `rerank` | Rerank (重排序) | `bge-reranker-v2-m3` | `/rerank` | Reorder BM25 / vector candidates |
| `vision` | Vision (视觉理解) | `gpt-4o-mini` | `/chat/completions` | Image / scanned-document understanding |

`VENDORS` ships 9 presets with per-category model suggestions: `openai`, `deepseek`, `qwen` (通义千问), `zhipu` (智谱), `moonshot` (月之暗面), `ollama` (local), `siliconflow` (硅基流动), `azure`, `custom`.

## 3. Data model

`ai_providers` (one of the 26 tables): `id`, `code` (unique), `name`, `category`, `vendor`, `base_url`, `api_key`, `model`, `enabled`, `is_default`, `config` **JSON**, `description`, `created_at`, `updated_at`. `idx_ai_providers_category(category, is_default)` accelerates default lookups.

| Field | Notes |
| --- | --- |
| `code` | Immutable identity, `^[a-z][a-z0-9_-]{1,49}$` |
| `category` | Must be one of the six codes; rejected with `400` otherwise |
| `api_key` | Plaintext column, **never returned** — see §5 |
| `config` | Free-form JSON (e.g. `temperature`) merged by `effective_llm()` |
| `is_default` | At most one `1` per category, enforced in `set_default()` |
| `enabled` | Default rows may be shipped disabled until a key is provided |

## 4. API

| Endpoint | Permission | Purpose |
| --- | --- | --- |
| `GET /ai/providers` | `mcp:read` | List; filters `category`, `enabled_only` |
| `GET /ai/providers/meta` | `mcp:read` | Categories, vendors, current defaults, totals and effective LLM runtime (no key) |
| `GET /ai/providers/{id}` | `mcp:read` | One configuration (masked) |
| `POST /ai/providers` | `settings:write` | Create (`201`) |
| `PUT /ai/providers/{id}` | `settings:write` | Patch; `code` is immutable |
| `DELETE /ai/providers/{id}` | `settings:write` | Delete; promotes another row to default if needed |
| `POST /ai/providers/{id}/default` | `settings:write` | Make it the sole default of its category (also sets `enabled=1`) |
| `POST /ai/providers/{id}/test` | `mcp:read` | Static validation, optional live probe |
| `GET /settings/ai` | `settings:read` | Compact per-category view, prefilled from the default provider or `.env` |
| `PUT /settings/ai` | `settings:write` | Save the default provider of one or more categories at once |

Reads use `mcp:read` so the same viewer/operator roles that can see the MCP pages can see model metadata; all writes require `settings:write`. Mutations emit `ai.provider.create|update|delete|default|test` audit entries.

`POST /ai/providers/{id}/test` accepts `{"live": false}` (default). The static check validates `name`, `category`, `model`, `base_url` (optional for `local`/`custom` vendors) and `api_key` (optional for `local`). With `live=true` and both `base_url` and `api_key` present, it issues a short (4 s) `GET {base_url}/models` and reports `reachable` / `http_status`; otherwise `reachable=null` and no network request is made.

## 5. Write-only API keys

`model_providers._out()` strips `api_key` from every response and replaces it with:

| Field | Value |
| --- | --- |
| `has_api_key` | `true` / `false` |
| `api_key_masked` | `mask()`: first 3 chars + `******` + last 4 (short keys are fully starred) |

On `PUT`, sending an empty string **or the masked value** means "keep the stored secret" (`_normalize()` drops the field), so the UI can round-trip an edit without ever re-sending or displaying the real key. `GET /ai/providers/meta` likewise omits `api_key` from `effective_llm` and exposes only `has_api_key`. See [Security Architecture](security.md) for the threat-model entry.

## 6. Defaults and runtime resolution

`set_default()` runs `UPDATE ai_providers SET is_default=0 … WHERE category=? AND id!=?` then marks the target `is_default=1, enabled=1` — a category can never have two defaults. Deleting a default promotes the lowest-id remaining row in that category.

`effective_llm()` builds the runtime config:

1. Start from `settings`: `llm_provider`, `llm_base_url`, `llm_api_key`, `llm_model`, `llm_temperature`, `source="environment"`.
2. Load the `llm` default. If absent or disabled → return the environment config unchanged.
3. Overlay non-empty `base_url` / `api_key` / `model` from the row; if a key is now present while provider is `mock`, switch to `openai-compatible`.
4. Overlay `config.temperature` when numeric.
5. Set `source="provider:<code>"`.

`services/llm.py` calls `effective_llm()` in `describe()`, `_http_chat()`, `_agentscope_chat()`, `chat()` and `run_agent()`, so `GET /agents/meta/runtime` reports the actual provider/model/source. An agent's own `model` field still takes precedence for the request. Knowledge `/stats` reports the configured `embedding` and `rerank` defaults.

## 7. Seed defaults, `.env` bootstrap and frontend

`seed.ensure_registries()` runs on **every startup** and idempotently provisions one default row per category, then calls `model_providers.bootstrap_from_env()`:

| Code | Category | Initial model | `.env` source | Enabled |
| --- | --- | --- | --- | --- |
| `default-llm` | `llm` | `gpt-4o-mini` | `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | yes (mock works without a key) |
| `default-asr` | `asr` | `whisper-1` | `ASR_BASE_URL` / `ASR_API_KEY` / `ASR_MODEL` | only with URL + key |
| `default-tts` | `tts` | `tts-1` | `TTS_BASE_URL` / `TTS_API_KEY` / `TTS_MODEL` | only with URL + key |
| `default-embedding` | `embedding` | `bm25-local` | `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` | yes (local) |
| `default-rerank` | `rerank` | `none` | `RERANK_BASE_URL` / `RERANK_API_KEY` / `RERANK_MODEL` | only with URL + key |
| `default-vision` | `vision` | `gpt-4o-mini` | `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | only with URL + key |

**Bootstrap contract.** `bootstrap_from_env()` reads `config.settings` (which `python-dotenv` fills from `backend/.env` and the repository-root `.env`) and writes non-empty values onto the category's default row. A row is only touched while `config.env_managed` is not `false`:

- rows created by the seed start as `env_managed: true`;
- saving from Settings or editing `base_url` / `api_key` / `model` / `enabled` through `/ai/providers` sets `env_managed: false`;
- therefore a restart re-applies `.env` to untouched categories and **never overwrites values edited in the UI**.

Enabled flags are derived, not copied: a category with both URL and key becomes `enabled=1`; ASR/TTS/vision/rerank without credentials stay disabled; `llm` keeps its flag because the `mock` provider needs no key.

**Two frontends, one registry.** `frontend/src/pages/ModelProviders.tsx` (`/models`) is the full manager — tabs per category, multiple providers, vendor presets, default/test/delete. `frontend/src/pages/Settings.tsx` (`/settings`) embeds a compact **AI model services** card that edits only the default row of each category: `GET /settings/ai` prefills every field from the stored default (falling back to `.env`), `PUT /settings/ai` saves them, and **Load .env** re-reads the bootstrap values into the form without saving. The card also shows the runtime badge (`provider · model · config_source`) and links to `/models`.

## 8. Validation and limitations

`backend/tests/smoke.py` (157 assertions) covers category metadata, vendor presets, create/update/delete, invalid category rejection, exclusive default, masked keys, key retention on masked `PUT`, `effective_llm()` overriding environment values, static/live test endpoints, runtime metadata, the `/settings/ai` view with `.env` prefill, per-category save, unknown-category rejection, and the env-managed detach/restore cycle.

**Current limitations (intentional):**

- Only the `llm` category drives live inference. `asr`, `tts`, `embedding`, `rerank` and `vision` are configurable declarations; retrieval still uses in-process BM25 (`default-embedding` is explicitly `bm25-local`, `default-rerank` is `none`).
- `live=true` probes only `/models` — sufficient for OpenAI-compatible endpoints, not a substitute for a real completion/transcription request.
- Provider keys are stored as plaintext in SQLite; encrypt at rest and restrict `settings:write` in production.
- No per-agent or per-request provider override beyond the `model` field; no key rotation/versioning.

## 9. Production upgrade path

| Current | Upgrade |
| --- | --- |
| Plaintext `api_key` column | Secret manager / KMS reference, encrypted at rest, rotation policy |
| BM25 + `none` rerank | Wire `default-embedding` / `default-rerank` into `rag.py` behind the existing `build_context` contract |
| `llm`-only runtime | Add ASR/TTS/vision handlers that resolve their category default the same way |
| Static `/models` probe | Category-specific health checks (chat completion, transcription, embeddings) |
| Shared defaults | Per-agent / per-workspace provider overrides with quota and cost tracking |
