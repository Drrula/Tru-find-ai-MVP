# ADR-029 — Backups, PITR, and tested restore

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Operations |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
Daily Postgres backups + point-in-time recovery on the production database. Quarterly restore drill: restore yesterday's backup into a scratch database and run a smoke test. The drill is a calendar event, not an aspiration.

## Why
Untested backups are hopes, not strategies. The restore process always reveals a problem the first time you run it; you want that to happen on a Wednesday morning, not during an incident.

## Tradeoffs
- Storage cost (small).
- One day of engineering attention per quarter.

## Future limitations
- Cross-region disaster recovery is a separate (later) decision; daily backups alone don't survive a region outage.

## Migration cost if revisited
Setting up backups after losing data is the worst possible time. Setting them up now is one Railway toggle plus a calendar reminder.

## Scaling implications
None at our size.

## Operational complexity
Low up front, low ongoing — once a quarter.

## Constraints this ADR imposes
- Production Postgres provisioned with PITR enabled from creation (Phase B).
- Quarterly restore drill on calendar; outcome documented in `docs/ops/restore-drills/`.
- Backup retention: 7 daily, 4 weekly, 3 monthly minimum.

## See also
- ADR-002 (Postgres)
- ADR-027 (additive migrations)
