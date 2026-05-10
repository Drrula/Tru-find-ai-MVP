# ADR-046 — Multi-region / data-residency posture

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Tenancy · Canonical entities · Irreversible schema · Operations |
| Date locked | 2026-05-10 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision

The platform commits to multi-region deployability as a future
capability. B.3 makes that commitment load-bearing at the **logical
layer** only — no physical region infrastructure lands in B.3.

### B.3 scope

- `account.region` column lands (B.3.5): `TEXT NOT NULL DEFAULT 'us'`
  with a `CHECK` constraint against an explicit allowlist starting
  at `{'us', 'ca', 'uk'}`. Future regions are added by migration +
  CHECK-constraint amendment.
- `Settings.default_region` field (env `DEFAULT_REGION`, default
  `'us'`) — used by code paths that create new `account` rows when
  the caller doesn't specify a region.
- The column is **informational only** in B.3. No routing decisions
  read it; no replication is wired; no per-region storage is
  partitioned.

### Hard rules for B.3+ commits

- New code MUST NOT assume US-only context. Specifically:
  - Phone numbers stored in E.164 (already required by ADR-041).
  - Country on `business` rows: ISO 3166-1 alpha-2 (slot reserved
    in `business` table per Lock §2.3; B.3+ commits adding business
    persistence MUST populate it).
  - Currency on billing rows: ISO 4217 alpha-3 (slot reserved in
    `purchase` / billing-event tables; future billing-persistence
    commits MUST populate it).
  - Timestamps: `timestamptz`, UTC at rest (already required by
    Lock §2 — re-stated for region awareness).
  - User-visible copy / prompts / gap strings: live in
    `vertical_copy` keyed by `(vertical_id, locale, key)` per
    ADR-011 + ADR-048 — never English-only string literals in core.

### Physical-distribution deferral (per the "logical modularity now,
physical distribution later" rule)

- Cross-region DB routing: out of scope. Single Postgres remains.
- Cross-region replication: out of scope.
- Region-aware load balancing: out of scope.
- Per-region secrets / per-region key material: out of scope.
- Region-specific compliance attestations (GDPR, UK DPA, PIPL, etc.):
  out of scope — placeholder; revisit when a non-`'us'` account is
  about to onboard.

These slot in via the existing seam (`account.region` already
exists; future code reads it) without changing the call sites
established in B.3.

## Why

The Platform Directive v1 names UK / Canada / China / US as
in-scope future deployments. Without a `region` tag landing now,
every account row created between now and the deferred multi-region
phase ships implicitly as `'us'` with no way to change without a
backfill on a populated `account` table. Landing the tag while the
table is effectively empty (post B.2 deployment, pre-traffic) costs
one migration; deferring costs a future backfill plus the risk that
US-only assumptions calcify into core code (currency, locale,
phone-format defaults).

The directive also explicitly rejects US-only assumptions in core
code. Naming the allowlist + currency + country + locale conventions
here gives every B.3+ commit a clear test: does this assume US? If
yes, reject.

## Tradeoffs

- Adds a column + a CHECK constraint per allowed region. Future
  region additions require a migration.
- Locale-aware copy via `vertical_copy` is more setup than
  English-only literals — but ADR-011 + ADR-048 already require it.

## Future limitations

- The `'us' | 'ca' | 'uk'` allowlist is intentionally small at
  launch. Adding `'eu'`, `'cn'`, `'au'`, etc. is a migration; doing
  so likely triggers a region-specific compliance review at that
  point.
- This ADR does not commit to a specific data-residency model
  (region-stamping rows vs. region-isolating databases vs. region-
  isolating cells). That decision rides on the operational need
  that justifies physical distribution.

## Migration cost if revisited

- Allowlist amendment: cheap (migration + CHECK update).
- Adding routing: this is the deferred work. Builds on the
  `account.region` seam established here; call sites that
  currently ignore the column will read it in that future phase.

## Scaling implications

None in B.3.

## Operational complexity

Negligible in B.3 (one column, one allowlist). Increases substantially
when the first non-`'us'` account onboards — that's when compliance,
data-residency promise enforcement, and operational region-routing
become real. This ADR makes that future complexity additive, not
destructive.

## Constraints this ADR imposes

- `account.region` is `NOT NULL`. Every account creation site
  supplies it explicitly or relies on the `DEFAULT 'us'`.
- New core code MUST NOT contain US-only literals (currency
  symbols, phone-format regexes, postal-code patterns, English-only
  copy). Use the established primitives.
- Phone formatting via E.164 (per ADR-041). Restated for region
  awareness.
- The ADR does NOT extend to billing/payment-method per-region
  routing — Stripe's multi-currency / multi-tax model is locked in
  ADR-023/043 and the per-region commerce model is out of scope
  here.

## See also

- Platform Directive v1 (Andrew, 2026-05-10)
- ADR-008 (tenancy via `account_id`)
- ADR-011 (verticals are data, not code — copy lives in
  `vertical_copy`)
- ADR-041 (phone intelligence — E.164 baseline)
- ADR-043 (finance & commercial compliance placeholder)
- ADR-048 (vertical pack lifecycle — locale-aware copy delivery)
- ARCHITECTURE-LOCK §2.1 (tenancy classes)
