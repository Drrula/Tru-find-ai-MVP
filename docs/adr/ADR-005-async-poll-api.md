# ADR-005 — Async-with-poll API contract

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
`POST /v1/analyses` returns `{ run_id, status: "pending" }`. Clients poll `GET /v1/analyses/{id}` (or subscribe via SSE later). A `?wait=true` query flag preserves a synchronous response for the batch script during transition.

## Why
Real signals (Places, scrape, LLM) take 5–60s. Blocking HTTP at p99 is fragile (timeouts, proxy buffering, browser fetch limits). Async-with-poll decouples request lifetime from work lifetime, makes retries safe, and keeps the API behind sensible 5–10s timeouts.

## Tradeoffs
- Frontend complexity rises: clients handle pending/running/complete/failed states.
- Tests are slower and more involved.
- The simpler sync model would have been faster to ship for a demo.

## Future limitations
- Sync-only consumers (Zapier, embedded scripts) need the `?wait=true` shim.
- Streaming partial results requires SSE/WebSockets later.

## Migration cost if revisited
**This is the highest-impact contract decision.** Going async-later forces every client to change. Going sync-later is trivial (just block on the queue). Async-first is one-way-door insurance.

## Scaling implications
Decouples API throughput from worker throughput. A burst of 1000 scans does not 1000× the API; it lengthens the queue and workers drain at their own rate.

## Operational complexity
Medium. We now have a queue, a worker, a status machine, and we monitor queue depth and worker lag.

## Constraints this ADR imposes
- `analysis_run` table required from Phase B.
- Status state machine in ARCHITECTURE-LOCK §3.1 enforced.
- Frontend uses `lib/api.js` poll helper; never fetches inline.
- Legacy `/analyze-business` alias preserved through Phase B for the batch script.

## See also
- ARCHITECTURE-LOCK §3.1
- ADR-010 (immutable runs)
- ADR-017 (API versioning)
- ADR-032 (idempotency)
