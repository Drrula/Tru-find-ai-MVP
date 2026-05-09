# ADR-035 — Lead intelligence as a first-class subsystem

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Canonical entities · Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Lead intelligence is a first-class subsystem with its own canonical entity (`lead`), parallel to business scoring. Cold and warm leads share the same entity model, distinguished by `lifecycle_state` (ADR-037). Seven independent dimensions are never collapsed into a single composite score:

`lead_quality | engagement | ai_confidence | qualification | conversion_probability | communication_readiness | buying_window_intensity`

## Why
Differentiated lead handling drives revenue. A composite "lead score" loses the distinction between "interested but unqualified" and "qualified but unreachable" — both critical for sales action. Multi-dimensional, explainable scoring also accommodates future ML/AI enrichment without rewiring downstream consumers. Treating lead intelligence as a UI enhancement (rather than an architectural layer) defers compounding rework.

## Tradeoffs
- More schema complexity than a single lead row with score columns.
- Consumers must understand which dimension to use for which purpose.
- Aggregator logic is more nuanced (per-dimension weights).

## Future limitations
- Custom per-account dimensions are not supported in v1; would require extending the framework.
- Dimensions list is fixed at 7; adding a new dimension requires schema migration on the CHECK constraint.

## Migration cost if revisited
**High.** Once sales workflows, dashboards, and AI prompts assume the 7-dimension model, collapsing to a single score forces a re-architecture across the consumer surface.

## Scaling implications
Per-dimension storage scales linearly with lead × event volume. Aggregator pure-function design scales horizontally with workers.

## Operational complexity
Higher than single-score model. The discipline: no UI or API surface presents a synthetic "lead score" single number.

## Constraints this ADR imposes
- 7 dimensions enforced via CHECK constraint on `lead_dimension.dimension`.
- Same `lead` entity for cold and warm; distinguished by `lifecycle_state` (ADR-037).
- Cross-account contacts → separate `lead` rows; signal histories isolated. `phone_record` is the only globally-shared artifact (ADR-041).
- Lead verification pipeline parallels business verification (ARCHITECTURE-LOCK §3.4); phone classification (ADR-041) is the first verification module.
- All dimensions explainable via `inputs jsonb` on `lead_dimension` rows (ADR-036).
- No code path may compute or display "the lead score" as a single number.

## See also
- ARCHITECTURE-LOCK §2, §3
- ADR-036 (signals/dimensions storage)
- ADR-037 (lifecycle states)
- ADR-040 (event taxonomy)
- ADR-041 (phone intelligence)
- ADR-042 (compliance policy)
- LOCK-SUMMARY.md
