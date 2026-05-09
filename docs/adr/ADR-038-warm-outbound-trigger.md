# ADR-038 — Warm-outbound positive-trigger requirement

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Communication systems · Security/compliance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Outbound communication (SMS, voice, email) is denied unless a qualifying positive trigger event exists for the recipient lead within a freshness window. Opt-out absence is necessary but **not sufficient**.

Qualifying trigger categories: `engagement | intent | communication`. Categories `ai`, `enrichment`, `attribution`, `lifecycle` do not qualify (system-derived, not consent-equivalent).

Freshness windows (per-vertical override allowed):
- `engagement`: **14 days**
- `intent`: **3 days**
- `communication`: **24 hours**

## Why
"No opt-out" is a permission model only valid in jurisdictions that allow inferred consent — most do not. Positive-trigger requires the lead to have demonstrated active interest within a recent window. Fresher windows for higher-intent categories reflect the time-sensitivity of acting on those signals (a "thanks for reaching out" reply 5 days late is worse than no reply).

## Tradeoffs
- Cold outreach is impossible by design.
- Operational cost: every send checks `lead_event` history.
- Trade is the value: this is the principal compliance gate beyond `opt_out`.

## Future limitations
- Per-recipient (not per-lead) trigger semantics not supported (would require cross-lead trigger inheritance).
- Custom per-vertical category-to-trigger mapping not supported in v1.

## Migration cost if revisited
Loosening (allowing system-derived categories as triggers) is a config change. Tightening further is also a config change. Swapping to a fully data-driven trigger rule engine: medium.

## Scaling implications
One indexed lookup on `lead_event(lead_id, occurred_at, event_type)` per send. Negligible.

## Operational complexity
Medium. The discipline: every send path goes through `domain.notifications.has_warm_trigger(lead_id, channel)`. Bypass requires explicit admin action with `audit_log` entry.

## Constraints this ADR imposes
- Send gate check #4 in the 8-check structure (ARCHITECTURE-LOCK §3.7 + ADR-042).
- Trigger qualification keyed off `lead_event_category` (ADR-040), not specific event_types — new event types in qualifying categories trigger automatically.
- Per-vertical overrides via per-vertical configuration (sibling of `vertical_lead_event_weight`).
- Refusals record reason code `no_warm_trigger` plus the consulted window in `audit_log`.
- ADR-042 compliance policy may further constrain triggers per jurisdiction.

## See also
- ARCHITECTURE-LOCK §3.7
- ADR-014 (opt_out is necessary but not sufficient)
- ADR-037 (lead_event is the trigger source)
- ADR-040 (event taxonomy defines categories)
- ADR-042 (compliance policy may further constrain triggers per jurisdiction)
