# ADR-0004: SQLite persistence and in-process BM25 retrieval

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform Team |
| Related | `AI-001` §7 · `DAT-001` · `ARC-001` §12 |

## Context

Knowledge-grounded agents require document storage and retrieval. The platform must run with zero external services, and Chinese + English content must both be searchable (demo queries include mixed text such as `请假制度 leave policy`). A vector database or embedding API would add infrastructure and network dependencies.

## Decision

**Persistence:** use Python's built-in `sqlite3` with a single file, WAL journaling, `foreign_keys=ON`, `busy_timeout=5000`, a thread-local connection and an `RLock` for writes. 19 tables with complex structures (form `schema`, workflow `graph`, document `chunks`, role `permission_ids`, …) stored as JSON TEXT columns, transparently encoded by `db.insert/update/loads`. Seven indexes cover the hot query paths. `init_db()` also runs an idempotent `_migrate()` that adds columns introduced after the first release via `PRAGMA table_info` + `ALTER TABLE`, so existing databases upgrade in place.

**Retrieval:** implement BM25 locally in `services/rag.py` — no embedding service.

- `tokenize()`: English words + Chinese **unigrams and overlapping bigrams**, enabling mixed-language matching.
- `chunk_text(text, size=480)`: paragraph-aware packing, hard split for long paragraphs; `index_document()` persists `chunks` as JSON and sets `status='indexed'`.
- `search(query, collection_ids, top_k=4)`: BM25 with `k1=1.5`, `b=0.75`, IDF `ln(1 + (N-df+0.5)/(df+0.5))`, length normalization by `avgdl`; returns snippets around the first match.
- `build_context(hits, max_chars=2200)`: numbered, score-annotated excerpts injected into the agent system prompt.

`rag.search` is the **single swap point** for a future vector store.

## Consequences

### Positive
- Zero infrastructure; deterministic, fully offline retrieval.
- Mixed zh/en queries work without a tokenizer dependency or model download.
- JSON columns keep the schema flexible for the visual designers.
- Whole knowledge index is rebuilt with `POST /knowledge/documents/{id}/reindex`.

### Negative
- Single-node only: no cross-process index sharing; SQLite is not suited to multi-writer deployments.
- BM25 is lexical, not semantic — synonyms and paraphrases may miss.
- Scores are recomputed per query over all indexed documents; O(N·terms) grows with corpus size.
- No migration framework for schema changes.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| External vector DB (Qdrant/Milvus/pgvector) | Adds infrastructure, breaks offline demo |
| Embedding API | Requires a key and network; non-deterministic tests |
| SQLite FTS5 | Poor Chinese segmentation without a custom tokenizer; less control over scoring |
| Postgres + JSONB from day one | Needs a running service; contrary to "clone and run" |

## Verification

Smoke tests cover document creation with automatic chunking, `reindex`, mixed zh/en `search` hits with assembled context, and knowledge-scoped agent answers with `sources`. `DAT-001` lists all 19 tables and 7 indexes.
