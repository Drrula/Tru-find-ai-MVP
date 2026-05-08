# ADR-018 — DIY magic-link auth, hosted-provider escape hatch

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Security/compliance · Application |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Email magic-link auth implemented in-house. Sessions are signed cookies (or short-lived JWTs in API surface). The user table includes `external_auth_id` (nullable) so swapping in Clerk/Supabase Auth/WorkOS later is mapping IDs.

## Why
Current product is one user per account, low risk surface. Hosted auth providers introduce vendor lock-in, latency, monthly cost, and (for Clerk specifically) UI you can't fully control. DIY magic-link is ~300 lines and zero external dependencies.

## Tradeoffs
- We own the failure modes: token leakage, replay, rate limiting, email deliverability, MFA later.
- Auth bugs are catastrophic — must be done correctly.

## Future limitations
- SSO (Google, Microsoft) is non-trivial to add to DIY.
- MFA, social login, organization-level B2B auth are real chunks of work.
- If product becomes B2B-heavy, switching to WorkOS becomes very attractive.

## Migration cost if revisited
Designed-for now: `user.external_auth_id` nullable from the start. Migrating means provisioning users into the hosted provider and rewriting the login route. Medium effort, low risk.

## Scaling implications
None at our scale.

## Operational complexity
Medium. We are responsible for email-delivery, token rotation, abuse monitoring. The single most arguable decision in this stack; choosing a hosted provider on day one is a valid alternative.

## Constraints this ADR imposes
- `magic_link_token` table per ARCHITECTURE-LOCK §2.3.
- Token TTL in `MAGIC_LINK_TOKEN_TTL_MIN` env var (default 15).
- `token_hash = sha256(plaintext)`; plaintext only in the email.
- Rate limit per `email_hash` (Redis, ADR-003).
- Sessions in `session` table; `expires_at` enforced on every request.

## See also
- ARCHITECTURE-LOCK §3.8
- ADR-013 (email_hash)
