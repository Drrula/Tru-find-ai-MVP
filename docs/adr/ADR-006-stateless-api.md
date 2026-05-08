# ADR-006 — Stateless API; durable state in Postgres only

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
API processes hold no per-request state across requests. Auth context, queues, caches all read from Postgres or Redis.

## Why
Multiple API replicas behind Railway's edge with no session affinity, safe deploys (kill any replica), no "works on my machine" in-process cache bugs.

## Tradeoffs
- Small latency cost re-reading hot data per request — mitigated by a thin Redis cache (ADR-012).
- No "warm process" tricks.

## Future limitations
- Long-lived WebSockets need a sticky layer or pub/sub fan-out.
- Some optimizations (per-process model loading) are off the table.

## Migration cost if revisited
Trivial to keep this way. Adding sticky-session behavior later is medium effort.

## Scaling implications
Linear horizontal scaling. The constraint becomes Postgres connection count, addressed via PgBouncer when needed.

## Operational complexity
Lower than the alternative. Restart, deploy, scale — same operation.

## Constraints this ADR imposes
- No process-local caches that affect correctness.
- Auth token validation reads from DB (or signed token, no server memo).

## See also
- ARCHITECTURE-LOCK §1
- ADR-002 (Postgres source of truth)
- ADR-012 (cache layer)
