# ADR-003 — Redis for queues and ephemeral state

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
Single Redis instance for job queues, rate limits, and short-TTL caches.

## Why
Workers (ADR-004) need a broker; rate limiting wants sub-millisecond reads; the LLM/Places `external_cache` (ADR-012) wants a hot tier in front of Postgres. The smallest tool that does all three.

## Tradeoffs
- In-memory: a restart loses queue state unless persistence is configured, and even then recovery is best-effort.
- Critical state (analysis runs, entitlements) lives in Postgres, never in Redis alone.

## Future limitations
- Not a durable system of record.
- Exactly-once semantics or long-retention queues will outgrow it (Postgres-as-queue or SQS/NATS would be next).

## Migration cost if revisited
Swapping Redis for KeyDB/Dragonfly: trivial. Swapping the queue abstraction: medium, depends on ADR-004 discipline.

## Scaling implications
A small Redis handles tens of thousands of jobs/hour. Postgres limits hit before Redis sharding becomes necessary.

## Operational complexity
Managed on Railway. The discipline is "never put durable state in Redis" — a code-review rule.

## Constraints this ADR imposes
- Durable state goes in Postgres only.
- Cache TTLs visible in code; never set via Redis CLI ad-hoc.

## See also
- ARCHITECTURE-LOCK §1, §4
- ADR-002 (Postgres is source of truth)
- ADR-004 (arq workers)
- ADR-012 (external_cache layer)
