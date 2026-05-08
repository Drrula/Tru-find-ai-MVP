# ADR-019 — Server-side entitlement is the only paywall

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Billing/entitlements |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
A row in `entitlement(account_id, target_type, target_id, product_code, granted_at, expires_at NULL, revoked_at NULL)` is the only thing that unlocks a paid view. The frontend asks the API "is this report unlocked?" — never decides locally. The current `?paid=true` URL flag is removed.

## Why
Client-side gates are revenue leaks; anyone can type the URL or read the JS. They also break refunds, chargebacks, expirations, and admin grants — every business reality except "nominal happy path."

## Tradeoffs
- One extra API call on the results page (or include unlock state in the analysis response).
- Slightly more backend code.
- Stripe webhook becomes load-bearing.

## Future limitations
- Subscription products, credit packs, multi-business unlocks, gifting all extend `entitlement`. Designing as `(account_id, target, product_code)` from the start accommodates them.

## Migration cost if revisited
Replacing client-side gate with server-side gate is fine the first time. Doing it after a serious revenue incident is much more painful.

## Scaling implications
A single indexed lookup per gated render. Cacheable in Redis for hot reports.

## Operational complexity
Medium. Stripe webhook reliability becomes a dependency: dropped webhooks = customers paid but locked out. Mitigated by signature verification (ADR-023), idempotency (ADR-032), and a daily reconciliation job against Stripe's API.

## Constraints this ADR imposes
- `entitlement` table per ARCHITECTURE-LOCK §2.3.
- Frontend has no "is paid" boolean; it calls `GET /v1/analyses/{id}/entitlement`.
- Unique partial index `(account_id, target_type, target_id, product_code) WHERE revoked_at IS NULL`.
- Created only by Stripe webhook processor (ADR-023).
- Pricing model and refund/expiration policy: outstanding §5.2, §5.3 — gate Phase E.

## See also
- ARCHITECTURE-LOCK §3.6
- ADR-023 (Stripe webhook is source of truth)
- ADR-032 (idempotency)
