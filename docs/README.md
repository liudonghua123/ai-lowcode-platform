# Documentation Index / 文档索引

This directory contains the platform's **standard design and architecture documents**, plus real UI screenshots. All figures (table counts, permission codes, endpoint paths, BM25 parameters, tool names) are derived from the code and verified by the smoke suite.

本目录存放平台的**标准化设计与架构文档**及真实界面截图。文中所有数字（表数量、权限码、端点路径、BM25 参数、工具名）均取自代码并经冒烟测试验证。

## Document map

| ID | Document | Language | Content |
| --- | --- | --- | --- |
| `ARC-001` | [architecture.md](architecture.md) · [中文](architecture.zh-CN.md) | EN / 中文 | C4 context–container–component views, request pipeline, runtime sequences, deployment, quality attributes, traceability |
| `AI-001` | [ai-design.md](ai-design.md) · [中文](ai-design.zh-CN.md) | EN / 中文 | **AI system design**: LLM runtime, ReAct orchestration, unified tool registry, RAG/BM25, MCP exposure, prompt spec, safety boundary, upgrade path |
| `SEC-001` | [security.md](security.md) | EN (中文摘要) | Identity/JWT, PBKDF2, TOTP, WebAuthn, MFA policy, 26 RBAC permissions, SSO, audit, threat model, production checklist |
| `DAT-001` | [data-model.md](data-model.md) | EN (中文摘要) | 26 tables, 17 indexes, JSON columns, ER diagram, data-access helpers, seed data, migration notes |
| `API-001` | [api-reference.md](api-reference.md) | EN (中文摘要) | REST conventions, all **126 OpenAPI paths**, MCP methods, 20 tool schemas, examples |
| `MCP-001` | [mcp-skills.md](mcp-skills.md) | EN (中文摘要) | Independent MCP server and Skill registries, skill lifecycle, editable files, call journal, sources and RBAC |
| `KNB-001` | [knowledge-upload.md](knowledge-upload.md) | EN (中文摘要) | Multi-format knowledge upload, parsing pipeline, format catalog, API and validation |
| `AIM-001` | [ai-models.md](ai-models.md) | EN (中文摘要) | Six AI model categories, provider CRUD, write-only keys, defaults and runtime resolution |
| `FFC-001` | [form-flow-domestic.md](form-flow-domestic.md) | EN (中文摘要) | **Domestic form & approval spec**: 44 China-localized fields, statutory validation, AST formula sandbox, detail tables, conditional rules, node field permissions, 14-node human approval runtime, countersign / parallel / delegation, versions, print & CSV, `expense_claim` example |
| `WFP-001` | [workflow-portal-and-data-scopes.md](workflow-portal-and-data-scopes.md) | EN (中文摘要) | **Data scopes & workflow portal**: all/audit/self/anonymous scopes, read-only auditor, schema-driven launch form, auth-gated `/#/start/{code}` share URL, agent intents + 20 tools |
| `ADR-*` | [adr/README.md](adr/README.md) | EN | 10 accepted architecture decision records + ADR template and conventions |
| — | [README.md](../README.md) · [中文](../README.zh-CN.md) | EN / 中文 | Project overview, quick start, demo accounts, screenshots |
| — | [backend/README.md](../backend/README.md) · [中文](../backend/README.zh-CN.md) | EN / 中文 | Backend runbook, endpoints, security, configuration |
| — | [frontend/README.md](../frontend/README.md) · [中文](../frontend/README.zh-CN.md) | EN / 中文 | Frontend pages, layout, design system, i18n/theme, data flow |

## Suggested reading paths

| Role | Order |
| --- | --- |
| Reviewer / architect | `ARC-001` → `ADR-*` → `AI-001` → `SEC-001` |
| AI engineer | `AI-001` → `ADR-0002/0003/0004/0005` → `API-001` → `services/llm.py`, `mcp_tools.py`, `rag.py` |
| Backend engineer | `ARC-001 §6` → `DAT-001` → `API-001` → `SEC-001` → `routers/` |
| Frontend engineer | `ARC-001 §6.2/§10` → `frontend/README.md` → `API-001 §1` (bootstrap contract) |
| Form / approval engineer | `FFC-001` → `ADR-0009` → `DAT-001 §3/§4` → `API-001 §2.2/§2.3` |
| Portal / agent engineer | `WFP-001` → `ADR-0010` → `API-001 §2.3` → `SchemaForm.tsx`, `agent_intents.py` |
| SRE / operator | `ARC-001 §9/§12/§13` → `SEC-001 §8` → `README.md` Quick start |

## Conventions / 约定

1. **Primary design documents are bilingual** (`architecture`, `ai-design`); supporting reference documents are English with a Chinese summary at the top.
2. Every design document carries a **document-control table** (ID, status, version, applicable release, related docs).
3. Diagrams use **Mermaid** so GitHub renders them inline.
4. Decisions are recorded as **ADRs**; an accepted ADR is never edited in place — it is superseded.
5. Documents describe the **as-built** system. When behaviour changes, update the doc and the related ADR in the same commit.
6. Machine-readable contracts win: `/openapi.json` is authoritative for endpoints, `backend/app/db.py::SCHEMA` for tables, `TOOL_SPECS` for tools.

## Verification / 一致性校验

```bash
cd backend
python3 -m ruff check app tests # code style
python3 tests/smoke.py             # 189 end-to-end assertions
python3 -c "from app.main import app; print(len(app.openapi()['paths']))"      # 126

cd ../frontend
pnpm typecheck && pnpm build
pnpm check:i18n                    # en/zh key parity
```

## Screenshots / 界面截图

`docs/screenshots/` contains 18 real Chromium headless captures (the two domestic captures are 1680×1050), referenced by both root READMEs:

| File | View |
| --- | --- |
| `login.png` | Login, demo accounts, SSO, MFA |
| `dashboard.png` / `dashboard-dark.png` | Light and dark theme |
| `form-designer.png` | Visual form designer |
| `form-domestic.png` | Domestic form designer: grouped 44-field palette, Rules tab, `TABLE_SUM` formula, field permissions |
| `workflow-studio.png` | DAG workflow canvas |
| `workflow-domestic.png` | Domestic approval studio: 14-node palette, task center, approve / reject / return / transfer / add signer |
| `knowledge-rag.png` | Knowledge base + retrieval test |
| `knowledge-upload.png` | Multi-format drag-and-drop upload dialog and results |
| `ai-agents.png` | Agent chat with tool steps |
| `agent-bindings.png` | Agent creation with searchable resource bindings |
| `mcp-servers.png` | Independent MCP server registry, tools and journal |
| `skills.png` | Skill catalog, lifecycle and editable files |
| `model-providers.png` | AI model services by category with defaults |
| `rbac.png` | Users, roles, permission matrix |
| `workflow-portal.png` | Redesigned workflow portal: startable catalogue, my-workflows filters, approvals |
| `agent-dynamic-form.png` | Agent chat with a schema-driven dynamic collection form |
| `workflow-share.png` | Public, auth-gated shared start page |
