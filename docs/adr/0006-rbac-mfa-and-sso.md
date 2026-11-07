# ADR-0006: Declarative RBAC with policy-driven MFA and demo-capable SSO

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| Deciders | Platform Team |
| Related | `SEC-001` · `ARC-001` §7.1 · `AI-001` §10 |

## Context

Requirements call for "complete RBAC", CAS/OAuth2/OIDC/WeCom/DingTalk integration, and Passkey + OTP configurable **per role and per user**. The system must remain demonstrable without a real identity provider, and the seeded admin must be able to sign in immediately.

## Decision

**RBAC.** 25 fine-grained `resource:action` permissions, stored in `permissions`; roles hold `permission_ids` as JSON. `deps._load_user()` resolves role codes + permissions (`admin` → `["*"]`), and `has_permission()` supports exact codes and `resource:*` wildcards. Every business route declares `Depends(require("resource:action"))`; the same check is reused by the tool registry. Built-in roles: `admin`, `developer`, `operator`, `viewer`.

**Authentication primitives.** PBKDF2-HMAC-SHA256 (180,000 rounds, random salt) for passwords; HS256 JWT with `typ` ∈ `{access, mfa, enroll}`, TTL 7200 s / 300 s; `jwt_decode` validates signature, expiry **and** token type.

**MFA.** RFC 6238 TOTP (SHA1, 6 digits, 30 s, ±1 window) with `otpauth://` QR enrollment; WebAuthn Passkey challenges (`mfa_challenges`) with ES256/RS256 parameters. `mfa_required_for()` enforces the policy in this order: global flag → enforced user list → enforced role list → role-level `mfa_required`. A policy match returns a short-lived `mfa`/`enroll` token at login, driving the frontend challenge/enrollment step.

**SSO.** Five adapters in `services/sso.py`, each with protocol-specific credential checks in `is_configured()`. When credentials are absent, a clearly flagged **demo mode** still runs `authorize → callback → upsert_identity()` (state/nonce persisted in `sso_states`), provisioning a local `viewer` user. `/auth/providers` never returns raw provider config.

**Defaults.** `MFA_REQUIRED=false`, `MFA_ENFORCED_ROLES=` empty, admin role `mfa_required=0`, CAS enabled in demo mode — so the out-of-the-box login works while every MFA/SSO path remains reachable from the UI.

## Consequences

### Positive
- One authorization model covers REST, AI tools and MCP.
- Policy is inspectable and editable at runtime via `GET/PUT /auth/mfa-policy` and the `settings` table.
- Full auth surface demonstrable with no IdP, no authenticator app and no hardware key.
- All mutations are recorded in `audit_logs`.

### Negative
- A single symmetric `SECRET_KEY` with no revocation list; default value must be replaced in production.
- Demo SSO intentionally skips real IdP validation and auto-provisions users — must be disabled in production.
- WebAuthn uses challenge/credential binding without full attestation verification; `PASSKEY_ORIGIN` must match the deployment.
- No rate limiting / login lockout yet.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Third-party auth service (Keycloak/Auth0) | External dependency; contradicts offline-first |
| Coarse role-only checks | Cannot express `form:submit` vs `form:publish` |
| Global on/off MFA only | Does not satisfy the per-role/per-user requirement |
| Fail when SSO credentials are missing | Would make the login demo unusable |

## Verification

`backend/tests/smoke.py` verifies admin login, permission matrix, RBAC denial for `bob/operator` on form creation, allowed `form:submit`, SSO provider listing, demo authorize/callback provisioning (`cas_demo`), MFA policy read/update, TOTP setup/enrollment and audit logs.
