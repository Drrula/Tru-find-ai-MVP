# ADR-002 — Postgres as primary datastore

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Single Postgres database for all durable state.

## Why
Data is relational (accounts → businesses → runs → signals). Mixed read/write patterns. ACID required for entitlements and idempotency. JSONB gives flexible payload columns; partial indexes support soft-delete; `pg_trgm` enables business-name search later. The most boring, most operationally proven choice.

## Tradeoffs
- Vertical scaling has a ceiling.
- Avoid SQLite (no concurrent writes), MongoDB (we have relations), DynamoDB (operationally heavy, query patterns hard to predict early).

## Future limitations
- Heavy analytical queries will eventually need an OLAP store or read replica.
- Full-text and vector search will outgrow extensions.
- Multi-region writes are not feasible without major surgery.

## Migration cost if revisited
Splitting into multiple Postgres databases (per-tenant, per-domain) is medium and well-trodden. Migrating to MySQL: medium. Migrating to a non-relational store: full domain-model rewrite.

## Scaling implications
Single instance handles 10k+ analyses/day. Read replicas extend an order of magnitude. Sharding is a project, not a setting.

## Operational complexity
Low on Railway (managed). The discipline is migration hygiene (ADR-027) and backup verification (ADR-029).

## Constraints this ADR imposes
- All durable state in Postgres (ADR-006).
- Schema lives in Alembic migrations under `backend/app/db/migrations/`.
- All access through repositories (ADR-031).

## See also
- ARCHITECTURE-LOCK §2
- ADR-027 (additive migrations)
- ADR-029 (backups)
- ADR-031 (repository pattern)
