# ADR-027 — Additive-only migrations between deploys

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Environment separation · Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Within a single deploy: only additive schema changes (new tables, new nullable columns, new indexes). Drops/renames happen at least one deploy *after* the code stops referencing the old shape. Every deploy is independently revertible without DB rollback.

## Why
A renamed-column migration coupled to its application code change makes the deploy non-revertible: rolling back the code leaves the column gone. Splitting into "expand → migrate → contract" is the standard solution.

## Tradeoffs
- Schema changes take 2–3 deploys instead of 1.
- Tests should exercise both old and new schema during the transition window.

## Future limitations
- True zero-downtime requires online-schema-change tooling at very large scale. Postgres handles most of our cases natively.

## Migration cost if revisited
Adopting this discipline after an incident where a deploy couldn't roll back is the universal lesson. Better to start.

## Scaling implications
Direct — this is what makes deploys safe at any rate.

## Operational complexity
Medium. A CI check that grep-rejects `DROP COLUMN` / `ALTER ... RENAME` in migrations (with override comments for the contract phase) enforces it cheaply.

## Constraints this ADR imposes
- Alembic migration template includes a "phase" header (expand | migrate | contract).
- One ALTER per migration (easier review, easier revert).
- No backfills inside migrations; backfills are jobs.
- CI check on migration files for forbidden statements without override comment.

## See also
- ADR-026 (tag-driven prod assumes safe rollback)
- ADR-029 (backups + PITR for catastrophic case)
