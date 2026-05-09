# ADR-044 — Canonical event envelope and publisher abstraction

| Field | Value |
|---|---|
| Status | **Locked (placeholder until Phase B persistence)** |
| Class | Canonical entities · Irreversible schema decisions · Operations |
| Date locked | 2026-05-09 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision

A single in-process `Event` dataclass and `EventPublisher` protocol form the canonical producer-side API for every event in the system. Persistence shapes (`lead_event`, `audit_log`, `billing_event`, `compliance_policy_evaluation`) are projections of this envelope; producers do not write directly to those tables.

### Envelope shape (v1)

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUID | UUIDv7, application-side (ADR-033) |
| `event_type` | str | Resolved via registry; never hardcoded at emit site |
| `occurred_at` | datetime (UTC) | Moment the producing operation happened |
| `account_id` | UUID \| None | Nullable only for system-level events |
| `correlation_id` | UUID \| None | `request_id` from middleware (ADR-030) or `job_id` from worker |
| `actor_kind` | str | `user` \| `system` \| `webhook` \| `job` \| `ai` |
| `actor_user_id` | UUID \| None | |
| `target_kind` | str \| None | e.g. `lead`, `business`, `analysis_run`, `purchase` |
| `target_id` | UUID \| None | |
| `payload` | dict | JSON-serializable; validated against the registered event type's schema |
| `schema_version` | int | Envelope version itself; this ADR pins to `1` |

The `Event` dataclass is `frozen=True`. No mutation after construction.

### Publisher protocol

```python
class EventPublisher(Protocol):
    def publish(self, event: Event) -> None: ...
```

**Synchronous** in v1. Async support (`async def publish_async(...)`) is deferred to Phase C workers, where slow sinks are tolerable.

### Default implementations

- `LoggingEventPublisher` — Phase A. Emits the envelope as a single structured-JSON log line via structlog.
- `DatabaseEventPublisher` — Phase B+. Resolves `event_type` to a target projection table via the registry, then writes the row through the appropriate repository (per ADR-031).
- `MultiPublisher` — Phase D+. Fan-out wrapper composing multiple publishers (e.g. logs + DB + Sentry breadcrumb).

### Registry

- In-process for v1: `EventTypeDefinition` records keyed by `event_type`, holding `category`, `target_table`, `payload_schema`, `actor_kinds_allowed`.
- Producers call `lookup(event_type)`, never construct `event_type` strings inline.
- Promotes to DB-driven in Phase B via `lead_event_definition` (and analogous tables for audit/billing/compliance), per ADR-040.

## Why

The system already has four distinct event tables in the architecture (`lead_event`, `audit_log`, `billing_event`, `compliance_policy_evaluation`). Without a unified envelope, each producer codes against a different shape; adding a new event type or new sink (DB persistence, replay, Sentry breadcrumb) requires touching every producer. The envelope makes new sinks additive, not destructive.

This is also the cheapest moment to lock the producer interface: no domain modules emit yet. Once they do, changing the envelope shape forces a fan-out refactor across every emit site.

## Tradeoffs

- One indirection at every event emission site.
- Registry must stay in sync with persistence-table CHECK constraints (operational discipline).
- Forbidding direct projection-table writes from domain code is enforced by review, not by the type system.

## Future limitations

- Synchronous publish in v1 means a slow sink (DB outage) blocks the producing request. Phase C async publish decouples.
- In-process registry can't be edited without a deploy in v1; promotes to DB-driven in Phase B.
- No replay primitive in v1; Phase B's append-only projection tables enable replay later.
- No out-of-process brokers in v1 — explicitly out of scope per this ADR's "forbidden" list.

## Migration cost if revisited

**High.** Once domain modules emit through the publisher, structural change to the envelope forces updates across every producer. Locking the shape now is what averts that. Additive evolution (new optional fields, new sinks) is cheap; structural change is expensive and requires a superseding ADR.

## Scaling implications

Negligible at any realistic volume. Synchronous publish is bounded by sink latency: logging is microseconds, DB is milliseconds. Async publish (Phase C) handles slow sinks.

## Operational complexity

Low to medium. The discipline:
- No domain code writes directly to projection tables.
- No hardcoded `event_type` literals at emit sites — registry constants only.
- New event types arrive via registry update + (Phase B+) a corresponding `lead_event_definition` row, per ADR-040.

## Constraints this ADR imposes

### Code-side (Phase A — B.0.2)
- `backend/app/core/events.py` — `Event` dataclass, `EventPublisher` protocol, `LoggingEventPublisher`.
- `backend/app/core/event_registry.py` — in-process `EventTypeDefinition` table; `register()` and `lookup()` helpers.
- Domain modules call `publish_event(...)`; never import projection-table repositories for event writes.
- Tests: emit-site tests use a `RecordingEventPublisher` stub that captures emitted events.

### Schema-side (Phase B+)
- `lead_event`, `audit_log`, `billing_event`, `compliance_policy_evaluation` rows are projections of the envelope.
- A `(event_type, target_table)` mapping lives in the registry (v1: code; Phase B+: `lead_event_definition.target_table` column or analogous).
- `DatabaseEventPublisher` resolves `target_table` from registry, routes to the appropriate repo per ADR-031.

### Forbidden
- Direct `INSERT` into `lead_event` / `audit_log` / `billing_event` / `compliance_policy_evaluation` from domain code.
- Hardcoded `event_type` string literals at emit sites — must come from registry constants.
- `async def publish` in v1 — deferred to Phase C.
- Out-of-process brokers (Kafka, RabbitMQ, NATS, SQS, etc.) — explicitly out of scope. Re-introducing requires a superseding ADR.

## What this ADR makes possible

- New event types: register definition + emit; sinks pick up automatically.
- New sinks: implement `EventPublisher`; existing emit sites unchanged.
- Phase C async publish: extend protocol, swap publisher, no producer code changes.
- Replay (Phase B+): scan `lead_event` / `audit_log` rows back into envelope and re-publish.
- Sentry breadcrumbs (A.12+): a `SentryBreadcrumbPublisher` slots in via `MultiPublisher`.

## See also

- ARCHITECTURE-LOCK §2 (projection tables that the envelope produces)
- ADR-007 (core/ layout)
- ADR-008 (account_id on every owned/derived event)
- ADR-015 (audit_log projection)
- ADR-021 (schema-validated payloads)
- ADR-030 (request_id → correlation_id)
- ADR-031 (projection writes through repositories)
- ADR-033 (UUIDv7 for event_id)
- ADR-040 (definition-driven event taxonomy; registry is the v1 in-process placeholder)
- ADR-042 (compliance_policy_evaluation projection)
- ADR-043 (billing_event projection)
