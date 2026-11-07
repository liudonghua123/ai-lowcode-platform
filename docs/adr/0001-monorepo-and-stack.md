# ADR-0001: Monorepo with separated frontend and backend toolchains

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform Team |
| Related | `ARC-001` §2, §9 · `README.md` |

## Context

The platform must ship a visual form designer, a visual workflow canvas, a REST API, MCP, AI agents, RBAC, SSO and MFA in one deliverable, while remaining runnable from a single clone. The required stacks are fixed: `Vite + React + TypeScript + shadcn/ui` on the front end and `uv + python-dotenv + FastAPI + fastmcp + AgentScope` on the back end. i18n (en/zh, default en) and theme (system/light/dark) are cross-cutting requirements.

## Decision

Adopt a **monorepo with four top-level areas**:

```
backend/    uv project, FastAPI app, SQLite, tests
frontend/   pnpm + Vite SPA
docs/       design, architecture, API, ADR, screenshots
scripts/    setup.sh / dev.sh / start.sh
```

- Each side keeps its **own toolchain**: `backend/pyproject.toml` with `[tool.uv] package = false`, `frontend/package.json` with pnpm scripts (`dev`, `build`, `typecheck`, `check:i18n`).
- **Two run modes**: `dev.sh` (HMR on `:5173` proxying `/api` + `/mcp` to `:8000`) and `start.sh` (build `dist/`, serve everything from the FastAPI process on `:8000`).
- Use `HashRouter` so single-port static hosting needs no server-side route table.
- Every README ships in **en + zh-CN**; MIT license; `.gitignore` excludes generated artifacts, `.env` and runtime DB.

## Consequences

### Positive
- One `git clone` + `./scripts/setup.sh` yields a running system.
- Independent dependency cycles; either side can be built/tested alone.
- Single-port mode removes CORS/reverse-proxy concerns for demos.
- Consistent documentation and licensing across the repo.

### Negative
- Two lockfiles / package managers to maintain.
- Single-port mode requires a frontend build step before the SPA appears (mitigated: the catch-all resolves `dist/index.html` per request, so the API can start first).
- `HashRouter` URLs are less clean than history mode.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Separate repositories | Cross-cutting i18n/theme/permission contracts would drift; harder to demo |
| Single package.json with a Python subprocess | Conflicts with the required `uv` workflow |
| Server-side rendered frontend | Contradicts the Vite SPA requirement |
| History-mode router | Needs server-side fallback rules in every deployment mode |

## Verification

`./scripts/dev.sh` starts both ports; `./scripts/start.sh` serves SPA + API + MCP on `:8000`; `pnpm typecheck && pnpm build`, `ruff check`, `python tests/smoke.py` and `pnpm check:i18n` all pass.
