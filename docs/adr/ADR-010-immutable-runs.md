# ADR-010 — `analysis_run` is immutable and reproducible

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Once an `analysis_run` reaches `complete`, `partial`, or `failed`, its rows are never updated. Re-scanning creates a new `analysis_run`. Each run captures: prompt versions used (`prompt_version_snapshot`), weight snapshot (`weight_snapshot`), provider response references (`raw_payload_ref`), model identifiers (per `ai_probe`), code version (`code_sha`).

## Why
Customers reference past reports. Disputes ("my score changed last week") require a defensible audit trail. Immutability is what lets us reason about caching and idempotency: a row is either there or not, never partially mutated by a retry.

## Tradeoffs
- Storage grows linearly with scans.
- Updating a UI label means writing it as a new run, not editing the old one.

## Future limitations
- "Live" dashboards (always-current score) need a *separate* derived view atop the latest run; we cannot mutate one row.

## Migration cost if revisited
Adding mutability later: straightforward. Removing it after the fact (to gain reproducibility): requires backfill from logs, unreliable.

## Scaling implications
Storage cost low (signal payloads are small JSONB). At >1M runs we'd consider partitioning by month.

## Operational complexity
Low. The discipline is "no `UPDATE analysis_run SET ... WHERE status = 'complete'`" — enforced by review and a database trigger if we want belt-and-suspenders.

## Constraints this ADR imposes
- State machine (ARCHITECTURE-LOCK §3.1) enforced; only legal transitions.
- `weight_snapshot`, `prompt_version_snapshot`, `code_sha` sealed at terminal status.
- Re-running creates a new row; no reopens.
- Cost cap exhaustion → `partial` with `failure_reason='cost_cap_reached'`, never `failed`.

## See also
- ARCHITECTURE-LOCK §3.1
- ADR-020 (versioned prompts)
- ADR-022 (cost cap)
