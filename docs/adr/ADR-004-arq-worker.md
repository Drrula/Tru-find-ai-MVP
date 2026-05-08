# ADR-004 — `arq` as the worker runtime

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
Use `arq` (asyncio Redis-backed task queue) for background work.

## Why
Native asyncio matches FastAPI; jobs that call `httpx`, `asyncpg`, or LLM SDKs avoid thread pools. Cron is built-in. Code surface is small enough to read in a sitting — important for one-person ops.

## Tradeoffs
- Smaller ecosystem than Celery (fewer answers, fewer exotic features).
- RQ is similarly small but synchronous, forcing thread pools on every external call.
- Celery is feature-complete but its complexity is disproportionate to current needs.

## Future limitations
- No native DAG-style workflows (chord/canvas).
- Long-running jobs (>15 min) are awkward.

## Migration cost if revisited
Medium. Job functions are thin shims over domain services (ADR-007), so swapping to Celery or Temporal is mostly worker entry-points and enqueue calls. Domain logic stays put.

## Scaling implications
Workers scale horizontally. Concurrency per worker tunable via asyncio. Bottleneck will be Postgres or upstream APIs (Places, LLM), not arq.

## Operational complexity
Low. One Redis, one worker process per queue group, arq's CLI for inspection.

## Constraints this ADR imposes
- Workers in `backend/app/workers/`; jobs are thin shims over `domain/*`.
- One queue per blast radius: `signals`, `ai`, `imports`, `notify`, `default`.
- Idempotency keys explicit on every job (ADR-032).

## See also
- ARCHITECTURE-LOCK §4
- ADR-003 (Redis)
- ADR-007 (domain layout)
- ADR-032 (idempotency)
