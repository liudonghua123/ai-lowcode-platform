# Security Architecture

| Field | Value |
| --- | --- |
| Document ID | `SEC-001` |
| Status | Baseline (implemented and verified) |
| Version | 1.0 |
| Applies to | `ai-lowcode-platform` v0.1.0 |
| Related | [System Architecture](architecture.md) · [AI System Design](ai-design.md) · [Data Model](data-model.md) · [ADR-0006](adr/0006-rbac-mfa-and-sso.md) |

> 中文摘要：本文档描述平台的身份、认证、授权与审计体系——HS256 JWT（access/mfa/enroll 三类令牌）、PBKDF2-SHA256 180k 轮密码哈希、RFC 6238 TOTP、WebAuthn Passkey、可按全局/角色/用户强制的 MFA 策略、25 项细粒度 RBAC 权限、CAS/OAuth2/OIDC/企业微信/钉钉五种 SSO，以及全量写操作审计。AI 工具调用复用同一套权限校验，详见 [AI 系统设计](ai-design.zh-CN.md)。

## 1. Identity and tokens

| Property | Value |
| --- | --- |
| Algorithm | HS256 (`hmac` + `hashlib.sha256`), header `{"alg":"HS256","typ":"JWT"}` |
| Signing key | `SECRET_KEY` env var (default `dev-only-secret-change-me` — **must be replaced in production**) |
| Claims | `sub` (user id), `iat`, `exp`, `typ` |
| Token types | `access` (TTL 7200 s, `ACCESS_TOKEN_TTL`), `mfa` (TTL 300 s, `MFA_TOKEN_TTL`), `enroll` |
| Validation | `jwt_decode(token, expected_type=...)` — signature, expiry **and** `typ` are all checked |

`get_current_user()` reads `Authorization: Bearer`, decodes with `expected_type="access"`, reloads the user from SQLite and rejects disabled/missing accounts. `get_optional_user()` is used for public/demo paths. A `401` from the frontend client triggers a global logout event.

## 2. Password storage

`hash_password()` uses **PBKDF2-HMAC-SHA256 with 180,000 iterations** and a random 16-byte salt, stored as:

```
pbkdf2_sha256$180000$<salt.hex>$<digest.hex>
```

`verify_password()` re-derives with the embedded round count and compares via `hmac.compare_digest`. Passwords are never returned by any API (`list_users` explicitly nulls `password_hash`).

## 3. Multi-factor authentication

### 3.1 TOTP / OTP

| Parameter | Value |
| --- | --- |
| Standard | RFC 6238, HMAC-SHA1 |
| Digits / period | 6 / 30 s |
| Drift window | ±1 step (`window=1`) |
| Enrollment | `otpauth://totp/{issuer}:{label}?secret=...&issuer=...&algorithm=SHA1&digits=6&period=30` (rendered as a QR code in the UI) |

Endpoints: `POST /auth/otp/setup|enable|disable`, `POST /auth/mfa/verify`.

### 3.2 WebAuthn / Passkey

`security.py` builds registration/authentication options with ES256 (`alg=-7`) and RS256 (`alg=-257`) credential parameters, generates one-time challenges stored in `mfa_challenges`, and binds credentials to `users.passkeys`. Configuration: `PASSKEY_RP_ID` (default `localhost`), `PASSKEY_RP_NAME`, `PASSKEY_ORIGIN` (default `http://localhost:5173`). WebAuthn requires a secure context (HTTPS or localhost).

Endpoints: `POST /auth/passkey/register/options|verify`, `POST /auth/passkey/authenticate/options|verify`, `GET|DELETE /auth/passkey/credentials`.

### 3.3 MFA policy

`mfa_required_for(user, role_codes)` returns true when any of these apply:

1. Global `MFA_REQUIRED=true` (or runtime `settings.mfa_policy.required`).
2. The username is in `MFA_ENFORCED_USERS` / `policy.enforced_users`.
3. Any of the user's roles is in `MFA_ENFORCED_ROLES` / `policy.enforced_roles`.
4. The role record itself carries `mfa_required`.

On login, a policy match returns a short-lived `mfa`/`enroll` token instead of an access token, driving the frontend's challenge or enrollment step. Defaults ship with MFA **off** so the seeded admin can sign in without an authenticator; CAS demo SSO is enabled for the same reason.

## 4. RBAC

### 4.1 Permission model

25 fine-grained permissions:

```
dashboard:view
form:read, form:write, form:delete, form:publish, form:submit
workflow:read, workflow:write, workflow:delete, workflow:run
knowledge:read, knowledge:write, knowledge:delete
agent:read, agent:write, agent:chat
mcp:read, mcp:write, mcp:invoke
rbac:read, rbac:write
auth:config, audit:read
settings:read, settings:write
```

`has_permission(user, permission)` grants when the user holds `*`, the exact code, or a resource wildcard (`resource:*`). The `admin` role resolves to `["*"]`.

### 4.2 Enforcement points

| Layer | Mechanism |
| --- | --- |
| REST | Every business route declares `Depends(require("resource:action"))` → 403 on denial |
| AI tools | `mcp_tools.call_tool()` re-checks `PERMISSION_MAP` with the real user |
| MCP | `MCPAuthASGIMiddleware` binds the bearer user via `ContextVar`; anonymous read-only is allowed |
| UI | `AppContext.can(permission)` hides/disables actions; server-side checks remain authoritative |

Built-in roles: `admin` (all), `developer` (build forms/workflows/agents/knowledge), `operator` (submit forms, run workflows, chat), `viewer` (read-only). The smoke test verifies that `bob/operator` receives 403 for form creation and 201 for a permitted form submission.

## 5. SSO

| Provider | Required credentials | Protocol path |
| --- | --- | --- |
| CAS | `CAS_SERVER_URL`, `CAS_VERSION` | `/login?service=...` → ticket validation |
| OAuth2 | `OAUTH2_CLIENT_ID/SECRET`, `OAUTH2_AUTHORIZE_URL`, `OAUTH2_TOKEN_URL`, `OAUTH2_USERINFO_URL` | Authorization code → token → userinfo |
| OIDC | `OIDC_ISSUER` or `OIDC_DISCOVERY_URL`, `OIDC_CLIENT_ID/SECRET` | Discovery → ID token |
| WeCom 企业微信 | `WECOM_CORP_ID`, `WECOM_AGENT_ID`, `WECOM_SECRET` | QR / OAuth redirect |
| DingTalk 钉钉 | `DINGTALK_APP_KEY`, `DINGTALK_APP_SECRET` | QR / OAuth redirect |

`is_configured()` checks **real, protocol-specific** credentials (not placeholder fields). When unconfigured, a clearly flagged **demo mode** still exercises `authorize → callback → upsert_identity()`, provisioning a local user (e.g. `cas_demo`) with the `viewer` role. State/nonce is persisted in `sso_states`. `/auth/providers` never returns raw provider config to the browser. `PUT /auth/sso/providers/{code}` requires `auth:config`.

## 6. Audit

`deps.audit()` writes `audit_logs(actor, action, resource, detail, ip, level, created_at)` for every mutation (user/role changes, form publish, workflow run, agent config, MCP skill sync, settings updates, MFA policy changes). `GET /api/v1/audit/logs` supports filters; `GET /audit/actions` lists the action vocabulary. Agent conversations are persisted separately in `conversations`.

## 7. Threat model and mitigations

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Credential stuffing / brute force | PBKDF2 180k, no plaintext storage, account status check | No rate limiting yet |
| Token forgery / replay | HMAC signature, `exp`, strict `typ` check | Single symmetric key; no revocation list |
| Privilege escalation | Per-route `require()`, tool-level `PERMISSION_MAP`, wildcard semantics | Admin `*` is all-powerful by design |
| LLM-driven unauthorized write | ReAct tool calls re-check the logged-in user's permissions | Malicious tool arguments still need schema validation |
| Identity leak between concurrent requests | `ContextVar` binding with `try/finally` reset | — |
| SSO spoofing | `state`/`nonce` in `sso_states`, config stored server-side | Demo mode intentionally skips real IdP validation |
| Secret leakage | `.env` in `.gitignore`, no raw SSO provider config, `has_api_key` boolean only; `ai_providers.api_key` is write-only and responses expose only `has_api_key` / `api_key_masked` | Default `SECRET_KEY` must be replaced; provider keys are plaintext in SQLite — encrypt at rest in production |
| Untrusted document upload | Allow-listed extensions, ≤20 files / ≤20 MB each, `documents.parse()` never executes file content, extracted text is RBAC-scoped to the target collection | ZIP/XML parsers are best-effort; macro-enabled / legacy Office binaries are not safely parsed — quarantine untrusted files |
| Repudiation | Full audit trail with actor/IP/timestamp | Logs are local SQLite |

## 8. Production hardening checklist

- [ ] Replace `SECRET_KEY` with a high-entropy value; consider RS256 + key rotation.
- [ ] Set `APP_ENV=production`, enforce HTTPS, configure `CORS_ORIGINS` and `PUBLIC_BASE_URL`.
- [ ] Configure real SSO credentials; disable demo mode and review auto-provisioned accounts.
- [ ] Set `PASSKEY_RP_ID` / `PASSKEY_ORIGIN` to the production origin.
- [ ] Enable MFA policy for privileged roles and enroll authenticators.
- [ ] Add rate limiting, login lockout and structured security logging.
- [ ] Move SQLite to Postgres; encrypt backups; rotate audit-log retention.
- [ ] Add human approval for destructive AI tools (`submit_form`, `run_workflow`).
- [ ] Encrypt AI provider API keys at rest; restrict `settings:write` to trusted administrators.
- [ ] Quarantine / scan uploaded documents before parsing; disable the optional PDF/OCR helpers on untrusted hosts.
