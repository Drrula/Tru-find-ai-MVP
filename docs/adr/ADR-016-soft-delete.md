# ADR-016 — Soft-delete via `deleted_at` on user-owned data

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
User-owned tables (`business`, `analysis_run`, `lead`, `import_batch`, `sms_thread`, `account`, `user`) have `deleted_at TIMESTAMPTZ NULL`. Repository queries default-filter to `deleted_at IS NULL`. Hard-delete is a separate, audited admin operation. Internal/derived tables (`signal_result`, `external_cache`) hard-delete.

## Why
"Restore my account" is a request every product receives. Soft-delete makes it cheap. Also makes accidental deletes recoverable without backup restore. Only user-facing entities are soft-deleted to avoid burying everything in `WHERE deleted_at IS NULL`.

## Tradeoffs
- Every query in the repo layer must include the filter — handled by a base repository method.
- Indexes need partial-index versions (`WHERE deleted_at IS NULL`) for query performance.
- Hard-delete-for-GDPR-erasure must be explicitly designed (cascade plus a `deleted_at`-bypassing erase routine).

## Future limitations
- Soft-deleted rows still count toward unique constraints unless we use partial unique indexes — easy to forget.

## Migration cost if revisited
Switching policies (soft → hard or vice versa) is doable but requires rewriting unique constraints and queries.

## Scaling implications
Slightly bigger tables; partial indexes mitigate query cost.

## Operational complexity
Medium. The discipline is "default-filter by deleted_at, partial-unique indexes, GDPR-erase is a separate path."

## Constraints this ADR imposes
- Partial unique indexes everywhere a unique constraint exists with soft-delete: `... WHERE deleted_at IS NULL`.
- Repository base class default-filters; explicit `include_deleted=True` for admin paths.
- GDPR erase routine: hard-delete with audit_log entry.

## See also
- ARCHITECTURE-LOCK §2.3
- ADR-031 (repository pattern)
