# ADR-040 — Definition-driven event taxonomy

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Canonical entities · AI mutation behavior · Cross-vertical extensibility |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
`lead_event` types are fully data-driven via three definition tables:

- `lead_event_category` — taxonomy of categories.
  Seed: `engagement | intent | enrichment | ai | attribution | communication | lifecycle`. Reserved as `status='draft'`: `orchestration`.
- `lead_event_source` — taxonomy of sources.
  Seed: `web | sms | email | crm | enrichment_provider | ai_probe | manual | system | import`. Reserved as `status='draft'`: `sara_orchestration`.
- `lead_event_definition` — versioned definitions per `(event_type, version)`. Carries category, source, default_weight, freshness_ttl_seconds, payload_schema (JSON Schema).

`lead_event` rows pin to `event_definition_id`. Reads always resolve via the pinned definition; emits refused for retired definitions. Payload validation is **insert-time strict** (with optional `lenient` flag per definition for known-noisy upstream sources).

Definitions are global (no `account_id`). Tenancy lives on observations and signals, not on the taxonomy.

## Why
"if event_type == X" branches in code are the canonical anti-pattern for multi-vertical, multi-source platforms. Driving from data lets new event types arrive via migration only — no code changes for receive-and-record. Versioning preserves reproducibility (lifecycle rules at the time of an event remain derivable). Strict insert-time validation catches malformed events at the boundary.

## Tradeoffs
- One indirection per event handling.
- Definition rows must be migrated, not hot-edited (matches ADR-020 prompt versioning).
- Strict validation can drop legitimately-shaped-but-buggy upstream events; mitigated by per-definition `lenient` flag.

## Future limitations
- Per-account custom event types not supported in v1 (would fragment the taxonomy).
- Highly bespoke vertical events still require fitting an existing category.

## Migration cost if revisited
**High** if reversed. Once Sara/Charlie or other emitters depend on the taxonomy, removing it forces every emit path to be rewritten with constants.

## Scaling implications
Definition tables small (<1k rows); cached in process. Event volume scaled by partitioning of `lead_event` (partition key `(account_id, occurred_at)`).

## Operational complexity
Low to medium. The discipline: no Python enums for event types; no `if event_type == X` in domain code; lifecycle rules and warm-outbound rules key off **category**, not specific types.

## Constraints this ADR imposes
- `lead_event.event_type` is denormalized for query speed; `event_definition_id` is the authoritative version pin.
- New event type = INSERT in `lead_event_definition` + per-vertical weights as needed.
- Retired definitions: emits refused; reads still resolve.
- Payload validated at insert against `payload_schema` (strict by default).
- Lifecycle resolver (ADR-037) and warm-outbound resolver (ADR-038) key off category, not specific event_types.
- `orchestration` category and `sara_orchestration` source reserved as `status='draft'` from day one (forward-compat).

## See also
- ARCHITECTURE-LOCK §2.3
- ADR-009 / ADR-011 / ADR-020 (same definition-driven pattern in business signals, verticals, prompts)
- ADR-037 (lifecycle consumes event categories)
- ADR-038 (warm-outbound consumes event categories)
