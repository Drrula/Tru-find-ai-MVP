# ADR-015 — `audit_log` from day one

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Security/compliance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
An append-only `audit_log(actor, actor_kind, action, target_type, target_id, payload_hash, request_id, recorded_at)` table. Privileged operations (entitlement grants, refunds, manual overrides, account merges, prompt edits, force-sends) write to it. No reads from log into business logic.

## Why
Every product eventually needs "who did what when," and back-filling from application logs is unreliable (logs rotate, levels differ, formats drift). Cheapest insurance against "did we charge this user twice?" disputes.

## Tradeoffs
- Storage growth (small — text fields and IDs).
- Discipline: every privileged operation must remember to log. Mitigated by putting the log call inside the domain service that performs the action.

## Future limitations
- True compliance audit (immutable, signed, off-site) eventually wants a stronger primitive (append-only log shipped to S3 with object lock). The DB table is the first 90%.

## Migration cost if revisited
Adding it later is fine but back-history is permanently missing. Adding it now costs ~50 lines.

## Scaling implications
Append-only, indexed by `(target_type, target_id)`. Trivial at any volume; partition by month at >10M rows.

## Operational complexity
Low. The discipline is a one-line call in privileged code paths.

## Constraints this ADR imposes
- Schema: see ARCHITECTURE-LOCK §2.3 system tables.
- `payload_hash = sha256(serialized_input)` so we don't store sensitive payloads inline.
- `request_id` propagated from API middleware (ADR-030).
- Domain services (`domain/payments/grant_entitlement`, etc.) call `audit_log.record(...)` as part of the same transaction that performs the action.

## See also
- ARCHITECTURE-LOCK §2.3
- ADR-030 (request_id)
