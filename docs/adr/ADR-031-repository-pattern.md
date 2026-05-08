# ADR-031 — Repository pattern for all DB access

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Data · irreversible schema |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Domain modules access the database only through repository objects (`businesses_repo`, `analyses_repo`, etc.), never via raw ORM queries. Repositories enforce tenancy, soft-delete, and audit semantics in one place.

## Why
The single most common multi-tenant data leak is "developer wrote a query and forgot the `account_id` filter." Centralizing DB access makes that structurally impossible.

## Tradeoffs
- One indirection layer.
- Occasional escape hatches for ad-hoc analytics queries (allowed, but read-only).

## Future limitations
- Repos can grow into "god classes" if not split per aggregate. Discipline: one repo per aggregate root.

## Migration cost if revisited
High. Retrofitting tenancy filters across scattered ORM queries is the canonical post-incident refactor.

## Scaling implications
Negligible direct cost. Enables future per-tenant routing or sharding.

## Operational complexity
Low. The discipline lives in one base class plus code review.

## Constraints this ADR imposes
- `db/repositories/<entity>_repo.py` is the only place that writes SQL or ORM queries against owned/derived tables.
- Base repository class injects `account_id` filter automatically.
- Soft-delete filter on by default; explicit `include_deleted=True` for admin paths.
- `audit_log.record(...)` called from privileged repo methods within the same transaction.

## See also
- ADR-008 (tenancy)
- ADR-016 (soft-delete)
- ADR-015 (audit log)
