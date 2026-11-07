# Frontend — AI Low-Code Platform

**Vite + React 18 + TypeScript** SPA with a hand-built **shadcn/ui-style** component library, **i18n (en/zh, English by default)** and **system / light / dark** theming.

中文：[README.zh-CN.md](README.zh-CN.md) · [Root README](../README.md)

## Run

```bash
cp .env.example .env        # optional; defaults proxy /api and /mcp to :8000
pnpm install
pnpm dev                    # http://localhost:5173
pnpm typecheck && pnpm build
```

The Vite dev server proxies `/api` and `/mcp` to `http://127.0.0.1:8000`. After `pnpm build`, the FastAPI backend also serves `dist/` at `/` (single-port mode via `scripts/start.sh`).

## Pages (HashRouter)

| Route | Page | Highlights |
| --- | --- | --- |
| `/login` | Login | demo accounts, SSO buttons, MFA challenge, OTP enrollment, passkey sign-in |
| `/sso/callback` | SSO callback | consumes the token from a real SSO redirect |
| `/` | Dashboard | live stats, activity chart, quick actions, recent runs & audit activity |
| `/forms` | Form Designer | field palette, drag-to-reorder canvas, property editor, live preview, submissions |
| `/workflows` | Workflow Studio | draggable DAG canvas, bezier edges, connect mode, node config, validate/run, instance logs |
| `/knowledge` | Knowledge Base | collections, documents, chunking, BM25 retrieval test with assembled context |
| `/agents` | AI Agents | chat with tool-call steps & source citations, agent config, runtime info, tool catalog |
| `/mcp` | MCP Skills | platform tool catalog, installable skill catalog, install/enable/disable/uninstall, editable file manager (view/create/update/delete/reload), call journal dashboard with stats/charts/filters/CSV export, sync, REST tool invocation |
| `/rbac` | Users & Roles | user/role CRUD, reset password, role×permission matrix |
| `/auth` | Authentication | SSO provider config, global/role/user MFA policy |
| `/audit` | Audit Logs | filterable log table with JSON detail viewer |
| `/settings` | Settings | locale, theme, profile, password, OTP QR enrollment, passkey management, platform settings |

Deep links: `/#/forms?form=leave_request`, `/#/workflows?workflow=leave_approval`, `/#/agents?agent=general_copilot`.

## Layout

```
src/
  main.tsx                 providers: HashRouter · Theme · I18n · Toast · AppContext
  App.tsx                  routes + auth guard + splash screen
  index.css                shadcn HSL design tokens, animated background, utilities
  components/ui/           basic.tsx (Button/Input/Card/Badge/Select/Switch/Segmented…)
                           overlay.tsx (Dialog/Confirm/Tabs/Toast/Dropdown)
                           table.tsx
  components/layout/       AppShell.tsx (sidebar, header, theme/locale switches, user menu)
  components/              PageHeader.tsx, Charts.tsx (SVG chart, stat cards, donut)
  i18n/                    locales.ts (496 leaf keys per locale), index.tsx (provider + t())
  theme/ThemeProvider.tsx  system/light/dark with prefers-color-scheme listener
  store/AppContext.tsx     session, /meta/bootstrap catalogs, can(permission)
  lib/                     api.ts (fetch client + 401 handling), utils.ts, webauthn.ts
  pages/                   12 page modules
  types.ts                 shared TypeScript models
```

## Design system

- shadcn/ui conventions: HSL CSS variables (`--background`, `--primary`, `--border`, …), `radius`, `cn()` = `clsx` + `tailwind-merge`, `cva` variants, lucide-react icons.
- Light animated gradient background with a subtle grid; dark theme uses the same tokens. No emoji — all iconography is SVG.
- Mobile-first: the sidebar becomes a drawer, grids collapse to one column, and toolbars wrap.

## i18n & theme

- `I18nProvider` defaults to **English**, persists the choice in `localStorage`, sets `<html lang>`, and falls back to English when a key is missing.
- `ThemeProvider` defaults to **system**, listens to `prefers-color-scheme`, toggles the `dark` class and updates `meta[theme-color]`.
- Both are switchable from the header and from the Settings page; server-side defaults come from `/api/v1/settings`.

## Data flow

`lib/api.ts` wraps `fetch` with the JWT bearer token, JSON serialization, `ApiError` and a global `401 → logout` event. `AppContext` loads `/auth/me` and `/meta/bootstrap` once after login; pages then read catalogs (field types, node types, permissions, providers, agent runtime) from context instead of hard-coding them.

## License

[MIT](../LICENSE)
