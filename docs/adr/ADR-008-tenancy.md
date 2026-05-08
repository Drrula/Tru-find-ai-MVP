# ADR-008 — Tenancy via `account_id` on every owned row

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Create the `account` table in the first migration. Every business-owned table has `account_id NOT NULL`, indexed, with row-level access enforced in the repository layer (ADR-031). Even when one account = one user today, multi-tenancy is structurally present.

## Why
Retrofitting `account_id` onto a populated database is the single most common rebuild driver in B2B products. Adding it later requires backfilling every row, rewriting every query, and reasoning about historical data ownership. Adding it now costs one column and one index.

## Tradeoffs
- Slight schema verbosity; every query joins or filters by `account_id`.
- Marginal disk and index overhead.

## Future limitations
- Cross-account features (admin views, white-label parents) require an explicit "scope override" mechanism designed deliberately, not ad-hoc.

## Migration cost if revisited
**This ADR is the migration.** Making it now is what averts a six-month rewrite later.

## Scaling implications
Per-account partitioning of large tables becomes a partition-key choice rather than a re-architecture. Read replicas with per-account routing are straightforward.

## Operational complexity
Higher than ignoring tenancy. Lower than retrofitting it. The repository-layer enforcement is the operational discipline that pays the dividend.

## Constraints this ADR imposes
- `account_id` on `business`, `analysis_run`, `signal_result`, `gap`, `competitor_snapshot`, `ai_probe`, `verification_result`, `import_batch`, `import_row`, `lead`, `sms_thread`, `sms_message`, `purchase`, `entitlement`.
- `account_id` denormalized onto child tables (no join required to filter).
- Repository base class enforces `account_id = :ctx_account_id` for tenant-owned and tenant-derived classes.
- Identity and system tables have explicit, audited bypass paths.

## See also
- ARCHITECTURE-LOCK §2.1, §2.3
- ADR-031 (repository pattern)
