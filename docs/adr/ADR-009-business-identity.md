# ADR-009 — Business canonical identity

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Primary key is UUIDv7 (ADR-033). Business uniqueness is `(account_id, name_norm, location_norm)`, expressed as `dedupe_hash = sha256(account_id || '|' || name_norm || '|' || location_norm)`. When Google Places resolves, store `place_id` as a non-unique secondary attribute; promote to a unique constraint only after data quality is validated.

## Why
`place_id` is authoritative when present but absent for unverified businesses, and Google occasionally retires/migrates IDs. Name+location normalization gives a stable identity from the moment a row is created (e.g. via CSV import) and lets us merge into `place_id` later without primary-key surgery.

## Tradeoffs
- Normalization rules (lowercasing, trimming, removing punctuation, expanding "St"/"Street") are now load-bearing — bugs create duplicates.
- Requires deterministic normalization tested explicitly.

## Future limitations
- Cross-locale normalization (international addresses) will force a revisit.
- Multiple physical locations under one brand name need a separate `business_location` model.

## Migration cost if revisited
Medium. Switching to `place_id`-as-primary requires backfill for unresolved businesses or accepting that some have no place_id. Promoting `place_id` to unique is straightforward.

## Scaling implications
None at any realistic scale.

## Operational complexity
Low. Normalization lives in one module with tests. Periodic dedupe job once `place_id` is populated.

## Constraints this ADR imposes
- `business.dedupe_hash` is a computed `bytea` column with a unique index where `deleted_at IS NULL`.
- Normalization function is deterministic, tested, and lives in `domain/businesses/normalize.py`.
- `place_id` indexed but not unique until validated.

## See also
- ARCHITECTURE-LOCK §2.3, §3.5
- ADR-033 (UUIDv7)
- ADR-016 (soft-delete + partial unique)
