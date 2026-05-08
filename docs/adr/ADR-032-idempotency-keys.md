# ADR-032 — Idempotency keys are explicit and stored

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Data · irreversible schema |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Any operation that mutates external state (charge, send SMS, create entitlement, dispatch import row, create analysis_run from import) carries a server-known `idempotency_key`. Stored in a dedicated column, indexed unique. Replays are detected and short-circuited at the repository boundary.

## Why
Workers retry; webhooks replay; import batches re-run. Without explicit keys, every retry is a potential double-write.

## Tradeoffs
- One extra column per such table, one index.
- Discipline: every command-style operation must define its key.

## Future limitations
- Cross-table idempotency (one logical operation spans multiple tables) requires a transaction boundary plus the key on the "outer" row only.

## Migration cost if revisited
Adding idempotency to an existing replay-unsafe pipeline is a delicate refactor with correctness consequences.

## Scaling implications
Trivial — one indexed lookup per write.

## Operational complexity
Low. The discipline is in command function signatures: every command takes `idempotency_key`.

## Constraints this ADR imposes
- `analysis_run.idempotency_key`, unique per `(account_id, idempotency_key)`.
- `import_row` idempotency = `hash(batch_id, row_index)`.
- `sms_message.idempotency_key` unique.
- `stripe_event.stripe_event_id` unique = idempotency.
- All command-style domain functions accept `idempotency_key` explicitly.

## See also
- ADR-005 (async-poll API; clients send `Idempotency-Key` header)
- ADR-023 (Stripe webhook idempotency)
- ADR-031 (repository pattern enforces)
