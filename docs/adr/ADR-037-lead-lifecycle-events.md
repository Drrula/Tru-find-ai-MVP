# ADR-037 — Lead lifecycle states and event-driven evolution

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Canonical entities · Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Leads carry an explicit `lifecycle_state` with a fixed 8-state taxonomy:

`cold | warm | engaged | qualified | opportunity | customer | dormant | unsubscribed`

State transitions are event-driven. `lead_event` (append-only) is the system of record for all state changes; transitions are written as events with `category='lifecycle'` and `event_type='lifecycle_transition'`.

Allowed transitions:
- `cold ↔ warm ↔ engaged ↔ qualified ↔ opportunity → customer`
- Any active state → `dormant` (inactivity threshold; configurable).
- Any state → `unsubscribed` (terminal-for-outbound; entity persists for compliance evidence).
- `dormant → warm` or appropriate prior active state (re-engagement).
- `unsubscribed` is terminal-for-outbound; inbound interactions still recorded as events.

## Why
Cold and warm leads are the same entity at different stages — modeling them separately would fork the system. Event-driven state changes preserve auditability and reproducibility (the `lead_event` row is the change record). Fixed state list keeps the pipeline understandable; transitions are code-enforced because lifecycle is structural to the product.

## Tradeoffs
- State list is fixed in v1; per-account customization requires schema work.
- All transitions go through events; direct state mutation is forbidden.

## Future limitations
- Sub-states (e.g., distinguishing `qualified-bant` vs `qualified-fit`) not supported in v1.
- Multi-stage opportunity pipelines (typical CRM "stages") would require an extension table.

## Migration cost if revisited
Adding states is additive (one CHECK update). Removing states requires data migration. Switching to a fully data-driven state model is medium effort.

## Scaling implications
None. State is one column; transitions are one append-only row.

## Operational complexity
Low. The discipline: no `UPDATE lead SET lifecycle_state = ...` without writing a corresponding `lead_event` in the same transaction.

## Constraints this ADR imposes
- `lead.lifecycle_state` constrained to the 8 values via CHECK.
- All transitions fire `lead_event(category='lifecycle', event_type='lifecycle_transition')` with `payload = {from, to, reason}`.
- `dormant` reachable from any active state via inactivity threshold (config).
- `unsubscribed` reachable from any state; entity persists for compliance evidence (audit_log retains the unsubscribe event indefinitely).
- Re-engagement from `dormant` returns to appropriate prior active state via event.
- Lifecycle resolver consumes events keyed by **category + payload predicates** (per ADR-040), not specific event_types — so new event types in existing categories trigger existing transitions automatically.

## See also
- ARCHITECTURE-LOCK §3.1 (matches `analysis_run` state machine pattern)
- ADR-035 (subsystem framing)
- ADR-040 (event taxonomy — lifecycle is one category; resolution by category)
- ADR-038 (warm-outbound depends on lifecycle state for reachability)
