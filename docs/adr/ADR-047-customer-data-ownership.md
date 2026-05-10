# ADR-047 — Customer data ownership vs. platform IP

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Security / compliance · Canonical entities · Governance |
| Date locked | 2026-05-10 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision

The platform distinguishes **customer-owned operational data** from
**platform-owned proprietary intelligence**. Customers retain the
right to export their operational data; the platform retains its
IP.

### Customer-owned (exportable)

Operational business data created by or on behalf of the tenant
through normal product use. Exportable via `POST /v1/account/export`
(stub lands in B.3.7; implementation deferred to a later phase).

Tables in this class (current + planned per ARCHITECTURE-LOCK §2):

- `account` (the account row itself; not the relations to children)
- `user` (within the account)
- `business` (when it lands)
- `analysis_run` (the runs the customer paid for) + `analysis_result`
- `lead` + `lead_event` (when they land)
- `sms_thread` / `sms_message` (when they land)
- `purchase` + `entitlement` (the customer's billing record)
- `opt_out` (account-scoped — global blocklist intelligence stays
  platform-owned, see below)
- `import_batch` (raw inputs the customer uploaded)

### Platform-owned (NOT exportable; platform IP)

Intelligence, methodology, configuration, and aggregated cross-
tenant data that the platform produces.

- `signal_definition` (the platform's measurement methodology)
- `vertical_*` tables (`vertical`, `vertical_signal_weight`,
  `vertical_prompt_version`, `vertical_copy`, `vertical_template`)
  per ADR-011 + ADR-048
- `prompt_version` (LLM prompt IP)
- `audit_log` (platform records of platform actions; includes
  references to customer activity but the audit log itself is
  platform IP)
- `blocklist` global rows (per ADR-039 — platform-aggregated
  intelligence; the account-scoped suppression slice IS exportable
  through `opt_out`)
- `compliance_policy_evaluation` (platform's compliance reasoning)
- `external_cache` (platform-derived enrichments)
- Future analytics / benchmark / scoring-methodology tables

### Boundary clarifications

- **The customer's analysis_run rows ARE customer-owned** (they
  purchased the run). The methodology that produced the score
  (`signal_definition`, `vertical_signal_weight`, the active
  prompt_version) is NOT — only the inputs + outputs + the
  identifier of the methodology version used.
- **Aggregate benchmarks derived from many customers' data** are
  platform-owned (per the directive: "platform owns the proprietary
  intelligence, automation, benchmarking, orchestration, scoring
  methodology, and adaptation systems"). The customer's own
  benchmark percentile within an aggregate IS exportable; the
  aggregate itself is not.
- **`audit_log` is platform-owned**, but customers may request
  audit records concerning their own account on a separate
  customer-facing audit-export endpoint (deferred; explicit future
  decision required before that endpoint lands).

### Export contract (B.3.7 stub; deferred implementation)

- Endpoint: `POST /v1/account/export` — auth-gated.
- Returns `501 Not Implemented` in B.3.7 with a documented response
  schema describing what the eventual export will contain
  (customer-owned tables, JSON format, schema versioning).
- Format: JSON, machine-readable, schema-versioned (matches the
  envelope discipline of ADR-044).
- Triggering: on-demand by an authenticated user with appropriate
  account-level role (B.3 stores `user.role` but does not enforce
  RBAC yet per phase-b2-plan.md decision #13 — the deferred
  implementation will).
- Out of scope: automated continuous export (S3 sync, etc.) — that
  rides on a separate decision when an enterprise customer requires it.

## Why

The directive establishes retention through continuous operational
value, not lock-in. A documented, enforceable right-to-export is
the operational instantiation of that commitment — customers know
they can leave with their data, which builds the trust required for
enterprise adoption. The flip side — keeping the platform's
methodology + benchmarking + intelligence proprietary — is what
makes the platform a defensible business rather than a thin SaaS
wrapper.

Codifying the boundary now, before either customer count or
intelligence volume grows, prevents two failure modes:

1. **Implicit lock-in:** features get built that bundle customer
   data with platform IP in ways that prevent clean export later.
2. **Implicit IP leak:** export features get built that include
   platform IP (weights, prompts, methodology) because no one
   thought to draw the line.

## Tradeoffs

- Forces every new table going forward to answer "customer-owned
  or platform-owned?" before it lands. That's the point.
- Audit-log access for customers is now a deferred design rather
  than an implicit yes/no.

## Future limitations

- The boundary may need finer slicing for enterprise customers
  (e.g. on-prem deployments where the customer arguably owns even
  the platform IP for their instance). That's an enterprise-tier
  exception, not the default.
- Aggregate benchmarks may need a customer-visible "your data
  contributed" disclosure (compliance requirement in some regions
  per ADR-046). Deferred until non-`'us'` regions onboard.

## Migration cost if revisited

- Re-classifying a table from customer-owned to platform-owned
  (taking back a right) is expensive — customers will object.
- Re-classifying from platform-owned to customer-owned (extending a
  right) is cheap and additive.
- Therefore: when in doubt at design time, classify as
  platform-owned. Extending later is safe; retracting is not.

## Scaling implications

Export endpoint will need pagination + streaming + rate-limiting
when implemented. None of that lands in B.3.7 — only the API
surface lock.

## Operational complexity

Low in B.3 (just an API stub + the classification table above).
Increases when the export endpoint is implemented — at that point
ownership of running long-form exports, securing the export
artifact, expiring download links, etc. become operational
concerns.

## Constraints this ADR imposes

- Every new table landed in B.3+ MUST be explicitly classified as
  customer-owned or platform-owned in the table's docstring AND in
  the migration's docstring.
- The export endpoint stub returns a documented response schema
  reflecting the customer-owned classification above; the schema
  MUST be updated when new customer-owned tables land.
- The "platform owns the methodology" line means scoring weights,
  prompt versions, gap copy, competitor pools, and signal weights
  are NEVER included in account exports — they are in vertical_*
  tables that are platform IP.
- Audit-log access for customers is a separate decision; the export
  endpoint MUST NOT return audit_log rows without explicit ADR
  approval.

## See also

- Platform Directive v1 (Andrew, 2026-05-10)
- ADR-011 (verticals as data — vertical_* tables are platform IP)
- ADR-014 (opt_out — account-scoped suppression IS exportable)
- ADR-015 (audit_log — platform-owned, customer access deferred)
- ADR-039 (blocklist — global rows platform-owned, account slice
  customer-owned)
- ADR-046 (region — compliance disclosure obligations may differ
  per region)
- ADR-048 (vertical pack lifecycle — packs are platform IP)
- ARCHITECTURE-LOCK §2 (full table catalog)
