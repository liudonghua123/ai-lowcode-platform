# Architecture Decision Records (ADR)

This directory records **significant, hard-to-reverse architectural decisions** using a lightweight ADR format. Each file is immutable once accepted; a decision that changes is superseded by a new ADR that links back to the original.

## Index

| ADR | Title | Status | Theme |
| --- | --- | --- | --- |
| [0001](0001-monorepo-and-stack.md) | Monorepo with separated frontend and backend toolchains | Accepted | Structure / toolchain |
| [0002](0002-single-tool-registry.md) | One registry for MCP tools, AI agents and REST invocation | Accepted | AI / capability model |
| [0003](0003-offline-first-llm-runtime.md) | Offline-first LLM runtime with three backends and degradation | Accepted | AI / runtime |
| [0004](0004-sqlite-and-local-bm25.md) | SQLite persistence and in-process BM25 retrieval | Accepted | Data / retrieval |
| [0005](0005-mcp-transport-and-auth.md) | fastmcp streamable HTTP with fallback and ASGI auth binding | Accepted | MCP / integration |
| [0006](0006-rbac-mfa-and-sso.md) | Declarative RBAC with policy-driven MFA and demo-capable SSO | Accepted | Security |
| [0007](0007-mcp-skill-lifecycle-and-journal.md) | Skill lifecycle, editable skill files and MCP call journal | Accepted | MCP / observability |
| [0008](0008-mcp-skills-split-model-providers-and-knowledge-upload.md) | Split MCP servers and Skills, AI model providers, knowledge upload and agent bindings | Accepted | MCP / AI platform |
| [0009](0009-domestic-forms-and-approval-runtime.md) | Domestic form engine and long-running human approval runtime | Accepted | Forms / workflow |

Referenced from [ARC-001 §11](../architecture.md), [AI-001 §15](../ai-design.md) and [FFC-001](../form-flow-domestic.md).

## When to write an ADR

Write one when the decision affects structure, cross-cutting behavior, a non-obvious technology choice, or something expensive to reverse. Do **not** write ADRs for routine implementation details — those belong in code comments or the relevant design document.

## Template

```markdown
# ADR-NNNN: <short, imperative title>

| Field | Value |
| --- | --- |
| Status | Proposed | Accepted | Deprecated | Superseded by ADR-NNNN |
| Date | YYYY-MM-DD |
| Deciders | <team / role> |
| Related | <doc IDs, code paths, other ADRs> |

## Context
What problem forces a decision? Constraints, requirements, observed failures.

## Decision
What was chosen, stated precisely and in the active voice.

## Consequences
### Positive
### Negative / residual risks

## Alternatives considered
| Alternative | Why rejected |

## Verification
How we know this decision is implemented and working (tests, endpoints, commands).
```

## Conventions

- File names: `NNNN-kebab-case.md`, zero-padded, sequential.
- Status transitions: `Proposed → Accepted → Deprecated/Superseded`; never edit an Accepted ADR's decision in place.
- Keep each ADR self-contained; a reader should not need the chat history.
- Cite concrete code paths and test results in **Verification** so the record stays falsifiable.
