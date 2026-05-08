# ADR-033 — UUIDv7 for all primary keys

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Data · irreversible schema |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Primary keys are UUIDv7 (time-ordered) generated application-side. No serial integers for entity IDs.

## Why
UUIDv7 keeps inserts sequential (B-tree-friendly, unlike v4) while removing the leak of "we have N customers" via integer IDs and removing cross-shard collision risk later. Application-side generation lets us mint IDs before insert (useful for idempotency and outbox patterns).

## Tradeoffs
- 16 bytes per key vs 8 for bigint.
- Slightly noisier in logs.

## Future limitations
- Some external systems still expect integer IDs; we'd need a mapping table at integration boundaries (rare).

## Migration cost if revisited
Switching from integer to UUID later requires backfilling, FK rewrites, and a sustained cutover. Doing it now is free.

## Scaling implications
B-tree-friendly inserts; no hot-spot on a sequence. Cross-shard safe by construction.

## Operational complexity
Low. One generator function in `core/ids.py`.

## Constraints this ADR imposes
- All entity tables use `id uuid PK`.
- IDs minted application-side via `core.ids.new_id()` (UUIDv7).
- No `serial`/`bigserial` columns except in dedicated counters where order alone matters.

## See also
- ADR-002 (Postgres)
- ADR-031 (repositories)
- ADR-032 (idempotency uses pre-minted IDs)
