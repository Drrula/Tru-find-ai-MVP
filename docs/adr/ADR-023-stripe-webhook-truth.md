# ADR-023 — Stripe webhook is the source of truth for purchases

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Billing/entitlements |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Checkout sessions are created server-side. The Stripe webhook (`/v1/webhooks/stripe`) is the *only* writer of `purchase` and `entitlement` rows. Webhook handler validates signature, deduplicates by `stripe_event_id`, is idempotent. A nightly reconciliation job pulls Stripe's API and verifies state.

## Why
Frontend success-page redirects are unreliable (closed tab, lost connection). Polling Stripe from frontend is not authoritative. The webhook is Stripe's contract for "payment really happened."

## Tradeoffs
- Webhook delivery has its own failure modes (network, our downtime, signature mismatches).
- Reconciliation job is mandatory, not optional.

## Future limitations
- Subscriptions, refunds, disputes, partial captures all flow through more event types. Handler designed as `(event_type, idempotency_key) → handler_fn` accommodates them.

## Migration cost if revisited
Replacing client-trust with webhook-trust later is post-incident work. Now, straightforward.

## Scaling implications
Webhook volume is tiny; reconciliation bounded by Stripe's pagination.

## Operational complexity
Medium. Monitor webhook failures (Stripe surfaces these), keep `STRIPE_WEBHOOK_SECRET` correct across environments, run reconciliation.

## Constraints this ADR imposes
- `stripe_event` table for idempotency by `stripe_event_id`.
- Webhook only validates + enqueues; the worker (`payments.process_event`) does the actual write.
- All purchase/entitlement creation goes through the webhook processor; no admin shortcut without an explicit `audit_log` entry.
- Refund/dispute → `purchase.status` transition + `entitlement.revoked_at`.

## See also
- ARCHITECTURE-LOCK §3.6
- ADR-019 (entitlement is the paywall)
- ADR-032 (idempotency)
