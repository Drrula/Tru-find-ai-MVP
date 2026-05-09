# ADR-043 — Finance & commercial compliance placeholder

| Field | Value |
|---|---|
| Status | **Locked (placeholder)** |
| Class | Billing/entitlements · Security/compliance · Canonical entities |
| Date locked | 2026-05-09 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision

Carve out architectural space for subscriptions, invoices, refunds, credits, billing addresses, tax jurisdictions, tax exemptions, and a billing-domain audit log. Stripe is the locked payments primitive (extending ADR-023). Tax and accounting providers sit behind adapters, with no concrete vendor selected yet (deferred to §5.14 and §5.15).

A hard architectural boundary is stated below and is **not** a deferrable decision.

## The hard boundary (locked, not deferrable)

The platform does not handle third-party customer funds, contractor payouts, escrow, marketplace settlement, money transmission, or revenue-share disbursement to non-platform parties. Stripe is used **only** to take payment for the platform's own services from the platform's own customers. Stripe Connect, Stripe Issuing, custom platforms, and any payout API are explicitly out of scope.

This boundary is what keeps the platform out of money-transmitter regulation, KYC/KYB obligations on third parties, and PCI scope expansion. It is not a deferral — it is a permanent product-shape decision.

## Why

Tax law, multi-state operations, accounting integrations, and subscription billing all evolve. Embedding their shapes in code creates rebuild risk. A placeholder layer reserves the schema space and provider abstraction so concrete decisions land into a known shape — without committing to specific tax/accounting providers, subscription tiers, or pricing logic now.

The hard boundary above is the largest scope-control decision in the architecture: every alternative (Connect, marketplace, payouts) carries a regulatory blast radius the project is not ready to absorb.

## Tradeoffs

- Schema space defined now even without implementation; minor disk overhead in Phase B's first migration.
- Provider adapters add a thin layer that will feel speculative until tax/accounting are concrete.
- Subscription placeholder shape may need adjustment when §5.16 finalizes pricing/dunning/proration.

## Future limitations

- The boundary forecloses any future move to marketplace / Connect-style architecture without a major rewrite (intentional).
- Tax computation always occurs at invoice time via a provider — no offline / precomputed rates.
- Accounting export is provider-mediated; no in-house GL.

## Migration cost if revisited

Low to tighten the placeholder once a tax/accounting provider is selected. **High-risk** if the boundary is later relaxed: Connect / payouts / escrow would require state money-transmitter licensing, KYC/KYB on third parties, PCI scope expansion, and significant re-architecture. Plan accordingly.

## Scaling implications

Standard billing-volume scaling. Append-only tables (invoice, refund, credit, billing_event) indexed by `(account_id, created_at DESC)`; partition by month at high volume.

## Operational complexity

Medium once active. Stripe webhook handler scope expands to subscription / invoice / refund event types. Reconciliation jobs cover subscriptions, invoices, refunds, credits. Tax exemption certificates require manual review on intake.

## Constraints this ADR imposes

### Schema additions (placeholder shapes; full DDL deferred)
- New tables: `billing_subscription`, `invoice`, `invoice_line`, `refund`, `credit`, `billing_address`, `tax_jurisdiction`, `tax_exemption`, `billing_event`.
- `entitlement` gains `subscription_id` (alongside `source_purchase_id`); CHECK that exactly one source is populated.
- `purchase` gains `tax_amount_cents`, `tax_jurisdiction_id`.

### Behavior
- Stripe webhook (ADR-023) handles subscription / invoice / refund event types with the same idempotency model (`stripe_event_id`).
- **Tax computed at invoice time via provider adapter** — never from a static rates table.
- Tax exemption is versioned via `effective_from` / `effective_to`; certificate documents stored **externally** (object storage per §5.9), referenced by URL.
- Refund authorization: `account.owner` role and `system_admin` only. Every refund writes a `billing_event` and an `audit_log` entry.
- Credit consumption order: **FIFO by `expires_at` then `created_at`**.
- Billing event log is append-only; richer billing-domain shape than the system `audit_log`. Cross-references via `billing_event.target_kind` / `target_id`.
- Entitlements (ADR-019) link to either `purchase` (one-time) or `billing_subscription` (recurring); the entitlement check itself is unchanged.

### Provider abstraction
- `clients/stripe.py` — Stripe payments + subscriptions (locked, no abstraction).
- `clients/tax_provider.py` — placeholder adapter; interface: `calculate(amount, billing_address) → (tax_amount_cents, jurisdiction_code, breakdown_json)`. Concrete provider deferred (§5.14).
- `clients/accounting_provider.py` — placeholder adapter; interface: `sync_invoice(invoice) → external_id`. Concrete provider deferred (§5.15).

### Billing event seed types
`subscription_created`, `subscription_canceled`, `subscription_renewed`, `invoice_issued`, `invoice_paid`, `invoice_voided`, `refund_issued`, `credit_granted`, `credit_consumed`, `address_updated`, `exemption_recorded`, `exemption_revoked`, `tax_calculated`. Add via migration (no enum hardcoding in code; same definition-driven pattern as ADR-040 events).

## What this ADR explicitly forbids

- Stripe Connect, Stripe Issuing, custom-platform / express accounts.
- Any code path that routes money to a third party.
- Hardcoding tax rates, exemption rules, or accounting account codes in Python.
- Storing PCI-scope card data anywhere in our DB. Stripe holds card data; we hold tokenized references only.
- Computing taxes from a static rates table.
- Refund or credit issuance bypassing `audit_log` + `billing_event`.

## What this ADR makes possible

- Switching tax providers (Stripe Tax → Avalara, etc.) → swap one adapter; rest of the system untouched.
- Subscriptions can launch in Phase E without schema work — the tables are already in place.
- Tax exemption customers (B2B resellers, nonprofits) onboard via the existing `tax_exemption` table without a new migration.
- A specific tax dispute → `billing_event` + `tax_jurisdiction.raw_classification` reproduces "this tax was computed by this provider on this date for this address."
- A refund / chargeback → existing `entitlement.revoked_at` flow (ADR-019) handles paywall revocation; `refund` / `billing_event` capture the financial side.

## See also

- ARCHITECTURE-LOCK §2.6 (placeholder schema)
- ADR-013 (PII for `billing_address`, `tax_id`)
- ADR-019 (server-side entitlement; gains `subscription_id` link)
- ADR-023 (Stripe webhook is source of truth; scope expanded)
- ADR-027 (additive migrations)
- ADR-031 (repository pattern for billing data)
- ADR-032 (idempotency via `stripe_*_id`)
- ADR-042 (compliance policy may add billing-related rules)
- §5.14 (tax provider selection — gate Phase E)
- §5.15 (accounting integration — deferred)
- §5.16 (subscription pricing, dunning, proration — gate Phase E)
