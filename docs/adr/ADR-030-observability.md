# ADR-030 — Sentry + structured JSON logs + Railway metrics

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Operations |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
Sentry for exceptions on backend and frontend. Structured JSON logs (`structlog`) shipped to Railway's log aggregation (or Logtail/Axiom if needed). Per-request `request_id` propagated through the API and into worker job records. Basic dashboards: error rate, queue depth, p95 latency, AI cost per day.

## Why
Three-tier observability (errors, logs, metrics) is the minimum to operate a system you take payments through. Without it, every incident is archaeology. With it, most incidents are 5-minute fixes.

## Tradeoffs
- Sentry costs money at scale.
- Structured logging is one extra import per module.
- Dashboards are an ongoing maintenance task.

## Future limitations
- Full distributed tracing (OpenTelemetry across api → worker → external API) is the next tier when service count grows. Now is too early.

## Migration cost if revisited
Adding Sentry to a system in production is a one-day task. Adding structured logging to scattered logs is a multi-week refactor. Adding `request_id` propagation after the fact is also multi-week. Logging discipline is best baked in early.

## Scaling implications
Log volume scales linearly; sample at high volumes. Sentry has per-event cost — set limits.

## Operational complexity
Medium. Someone owns dashboards, alert thresholds, Sentry triage. With one engineer, page on revenue-affecting symptoms only.

## Constraints this ADR imposes
- `core/observability.py` initializes Sentry on app start.
- `core/logging.py` configures `structlog` JSON output.
- Request middleware mints `request_id`, exposes `X-Request-ID`, binds to log context.
- Worker `job_run` rows record `request_id` of enqueuer.
- Logger redacts known PII fields per ADR-013.

## See also
- ADR-013 (PII redaction)
- ADR-015 (audit_log uses request_id)
