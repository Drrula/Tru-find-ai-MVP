# ADR-022 — Per-run AI cost cap

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | AI mutation behavior · Operations |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Each `analysis_run` has `cost_cap_usd_cents` (env-configured default, vertical-overridable). The AI client tracks running cost via `analysis_run.cost_usd_cents`; exceeding the cap aborts further probes and marks the run `partial` with `failure_reason='cost_cap_reached'`.

## Why
A misconfigured prompt or runaway loop can spend hundreds of dollars before anyone notices. A cap turns "infinite blast radius" into "bounded blast radius" and makes pricing predictable.

## Tradeoffs
- Slight complexity in the AI client (cost tracking per run scope).
- Some runs will be cost-capped and need re-running with a higher budget — a real product surface.

## Future limitations
- Per-account caps (free-tier user can't burn budget) and per-vertical caps both extend this naturally.

## Migration cost if revisited
Adding a cap after a cost incident is the most stressful version of this work. Adding it now is ~50 lines.

## Scaling implications
Direct: caps the upper bound on per-run cost regardless of bug or growth.

## Operational complexity
Low. A daily report ("runs that hit the cap") is the operational touchpoint.

## Constraints this ADR imposes
- `analysis_run.cost_usd_cents`, `cost_cap_usd_cents` columns mandatory.
- Atomic UPDATE of running cost (`SET cost_usd_cents = cost_usd_cents + N` with row lock).
- Cost cap exhaustion → `partial`, never `failed` (per ADR-010).
- Concrete dollar default outstanding (§5.7), gate Phase H.

## See also
- ARCHITECTURE-LOCK §3.1, §3.3
- ADR-010 (run lifecycle)
- ADR-020 (prompt versions)
