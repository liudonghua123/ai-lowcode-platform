# ADR-0008: Split MCP servers and Skills, add AI model providers, knowledge upload and agent bindings

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform maintainers |
| Related | [ADR-0002](0002-single-tool-registry.md) · [ADR-0005](0005-mcp-transport-and-auth.md) · [ADR-0007](0007-mcp-skill-lifecycle-and-journal.md) · [ARC-001](../architecture.md) · [AI-001](../ai-design.md) · [MCP-001](../mcp-skills.md) · [KNB-001](../knowledge-upload.md) · [AIM-001](../ai-models.md) |

## Context

Four requirements arrived together and exposed a structural problem in the pre-0008 design:

1. **MCP servers and Skills must be managed independently.** ADR-0005/0007 stored external MCP connection details (`transport`, `endpoint`, `command`, synced tools) in `mcp_skills`, conflating "a remote server I connect to" with "a skill I install, version and edit". Registering a new connection meant creating a fake skill; deleting a skill silently removed connectivity.
2. **Agent creation must configure its MCP / Skills / knowledge / workflow resources conveniently.** Agents only had `kb_ids`; there was no single endpoint returning all bindable resources, and no `server_ids` / `skill_ids` scoping of the ReAct tool set.
3. **Configuration must cover all model categories** (`llm`, `asr`, `tts`, `embedding`, `rerank`, …). LLM settings lived only in `LLM_*` environment variables read once at startup, with no place to declare other services or switch models at runtime.
4. **Knowledge bases must accept uploaded documents** in most Office formats, PDF and Markdown — not just hand-entered text.

Constraints: stay offline-first and dependency-light (ADR-0003/0004), keep one tool registry with one permission gate (ADR-0002), preserve existing databases through lazy `ALTER TABLE` migrations, and keep the demo runnable with zero external services.

## Decision

**1. Split the registries.** Introduce `mcp_servers` (connection config, health, declared tools) with its own router `GET|POST|PUT|DELETE /mcp/servers[...]`, and keep `mcp_skills` as the independent Skill registry with its own router `/skills` (lifecycle, catalog, manifest, editable files). Add a **nullable, non-owning** `mcp_skills.server_id` link. Deleting either entity must never cascade to the other. Move server probing/sync/invocation into `services/mcp_servers.py`; remove all skill lifecycle handling from `routers/mcp.py`, which now keeps only the shared MCP transport surface (`/mcp/tools`, `/mcp/status`, `/mcp/calls*`, `/mcp/invoke`). Add the `call_remote_tool` MCP bridge and extend `mcp_tools.list_tools()` with `include_external` / `server_ids` so enabled-server tools join the single registry under `mcp:invoke`.

**2. Make agent bindings declarative.** Add `server_ids` to `agents` (joining `kb_ids`, `skill_ids`, `workflow_ids`), add `GET /agents/meta/bindings` returning all four resource groups in one call, and clean stale ids on create/update via `_clean_ids()` against the four tables. `mcp_tools.agent_tools(agent, fmt)` narrows the ReAct tool set to bound servers/skills; unbound servers are invisible and uncallable. The create dialog uses searchable multi-select groups.

**3. Add a multi-category model registry.** Create `ai_providers` with six categories (`llm`, `asr`, `tts`, `embedding`, `rerank`, `vision`), vendor presets, one exclusive default per category, write-only `api_key` (responses expose only `has_api_key` / `api_key_masked`), `/ai/providers/meta`, `/{id}/default` and `/{id}/test`. `model_providers.effective_llm()` overlays the `llm` default on `LLM_*` environment variables and is consumed by `services/llm.py`. Reads use `mcp:read`, writes `settings:write`. Only `llm` drives inference; other categories are declared capability placeholders.

**4. Add multi-format knowledge upload.** Create `services/documents.py` — stdlib-only parsing of OOXML/OpenDocument/EPUB via `zipfile` + `ElementTree`, PDF via `pdftotext` (or `pypdf`), images via `tesseract`, legacy Office via best-effort CLI converters, plus text/data formats. `GET /knowledge/formats` exposes 43 allow-listed extensions; `POST /knowledge/upload` accepts ≤20 files of ≤20 MB each, isolates per-file failures, writes `kb_documents` file metadata (`file_name`, `file_type`, `file_size`, `parse_status`, `parse_error`) and immediately invokes `rag.index_document()` for BM25. No parser executes file content.

**5. Provision idempotently.** `seed.ensure_registries()` runs on every startup and fills `mcp_servers`, `mcp_skills` and `ai_providers` for databases created before the split. `db.init_db()` executes `SCHEMA` → `_migrate()` → `INDEX_SCHEMA`, so indexes on newly migrated columns are created only after the columns exist.

**6. Keep the UI and docs aligned.** Replace the single `McpSkills.tsx` page with `McpServers.tsx` (`/mcp`), `Skills.tsx` (`/skills`) and `ModelProviders.tsx` (`/models`); extend `Knowledge.tsx` and `Agents.tsx`; keep en/zh i18n at parity; document the change in ARC-001 / AI-001 / MCP-001 / KNB-001 / AIM-001 / API-001 / DAT-001 and this ADR in the same change set.

ADR-0005 and ADR-0007 remain Accepted for their transport, auth, lifecycle and journal decisions; their **registry ownership semantics** are superseded by §1 above.

## Consequences

### Positive

- A connection and a skill can now be created, synced, disabled and deleted on independent lifecycles; `server_id` expresses the optional relationship without ownership.
- Agent configuration is a single API call plus four id arrays; runtime tool exposure is enforced in code, not only in the UI.
- Models can be switched without a restart; secrets never leave the server in full.
- Knowledge ingestion covers real-world file formats with no new Python dependencies, and uploaded content is searchable immediately.
- Existing SQLite databases upgrade in place; the offline demo still boots with no API keys.

### Negative / residual risks

- `mcp_skills` still carries legacy `endpoint` / `command` / `type` columns for backward compatibility; they are no longer authoritative for connections and should be removed in a future major release.
- Only `llm` is wired into inference; `asr` / `tts` / `embedding` / `rerank` / `vision` are declarative placeholders and could mislead operators if not read with AIM-001 §8.
- Document parsing is best-effort (text only, no tables/layout fidelity); legacy Office and OCR depend on host CLI tools.
- Provider keys are plaintext in SQLite; external MCP servers are trusted once registered, and `call_remote_tool` widens the reachable tool surface (still gated by `mcp:invoke`).
- Three new routers plus two new services increase surface area; the smoke suite grew from 69 to 110 assertions to compensate.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Keep one `mcp_skills` table with a `kind` discriminator | Still couples connection lifecycle to skill lifecycle; does not satisfy "independently managed" and complicates delete/sync semantics |
| Store model configs in the existing `settings` table | `settings` is key/value runtime state with no category, default exclusivity, masking or per-row audit |
| Add `python-docx` / `openpyxl` / `python-pptx` / PyMuPDF dependencies | Heavyweight, breaks the offline-first/zero-extra-dependency constraint; ZIP+XML stdlib parsing covers the needed text |
| Require a vector DB / embedding service for uploads | Contradicts ADR-0004; BM25 already exists and works offline |
| Hard-code bindable resources in the frontend | Violates the metadata-driven UI principle; a dedicated `/agents/meta/bindings` endpoint stays authoritative |

## Verification

Falsifiable checks (all green at acceptance):

```bash
cd backend
python3 -m ruff check app tests                    # All checks passed
python3 tests/smoke.py                             # 110 passed, 0 failed
python3 -c "from app.main import app; print(len(app.openapi()['paths']))"   # 96
python3 -c "from app import db; print(db.SCHEMA.count('CREATE TABLE'), db.INDEX_SCHEMA.count('CREATE INDEX'))"  # 21 10

cd ../frontend
pnpm typecheck && pnpm build
pnpm check:i18n                                    # en 635 / zh 635, 0 missing
```

Endpoints to exercise: `GET /mcp/servers`, `POST /mcp/servers/{id}/sync`, `GET /mcp/servers/{id}/tools`, `POST /mcp/servers/{id}/invoke`; `GET /skills`, `GET /skills/catalog`, `POST /skills/install`, `POST /skills/{id}/sync`; `GET /ai/providers/meta`, `POST /ai/providers/{id}/default`, `POST /ai/providers/{id}/test`; `GET /knowledge/formats`, `POST /knowledge/upload`, `GET /knowledge/stats`; `GET /agents/meta/bindings`. Smoke coverage includes independent CRUD, delete-isolation, stale-id cleanup, bound chat, key masking, exclusive defaults, `effective_llm()` override, docx/xlsx/pdf/csv/md parsing and unsupported-format rejection.
