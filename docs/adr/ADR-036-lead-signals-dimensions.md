# ADR-036 — Lead signals, dimensions, and explainability

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Canonical entities · Data · AI mutation behavior |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Signals are atomic facts; dimensions are computed values. Both are append-only and explainable.

- `lead_signal_definition` — catalog of signal types with `freshness_ttl_seconds` and `contributes_to text[]` (which dimensions).
- `vertical_lead_signal_weight` — per-vertical weights with `effective_from`/`effective_to` versioning. One signal can contribute to multiple dimensions with different weights.
- `lead_signal` — append-only observed events; `source_ref_id` points to the originating `ai_probe`, `sms_message`, `import_row`, etc.
- `lead_dimension` — append-only computed dimension values. Carries `inputs jsonb` (signals + weights used), `confidence numeric(4,3) NULL` per row, `weight_version_at` snapshot, and `computed_at`.

Recomputation is hybrid:
- Real-time on `engagement | intent | communication | lifecycle` category events.
- Scheduled (10-min cadence) for `ai`-derived dimensions.
- On-demand admin recompute supported via `audit_log`-recorded action.

`communication_readiness` is **derived live** (not stored as a `lead_dimension` row): function of `opt_out` × `lead.consent_*` × `phone_record.sms_eligible` × cooldown. Cached in Redis with 5-min TTL; exposed as a SQL view for joinability.

## Why
Append-only history makes every score reproducible and auditable. Per-row `confidence` lets consumers filter low-confidence values; the standalone `ai_confidence` dimension is distinct (it represents AI's overall self-confidence on a lead). Hybrid recomputation balances dashboard freshness with AI cost containment (ADR-022).

## Tradeoffs
- More writes than mutable-current-value model.
- Slight read complexity: "current value" requires `DISTINCT ON (lead_id, dimension) ORDER BY computed_at DESC` (or a denormalized current-value view).
- Mitigated by a `lead_dimension_current` materialized view if read pressure demands it.

## Future limitations
- Append-only growth requires partitioning at high volume (>1M leads); partition key `(lead_id, computed_at)` ready.
- Per-account dimension overrides not supported in v1.

## Migration cost if revisited
Medium. The append-only model is cheap to keep; removing it loses reproducibility.

## Scaling implications
Linear with signal × dimension × lead volume. Partitioning preserved by `lead_id` always present on derived rows.

## Operational complexity
Medium. Aggregator runs per recompute trigger; scheduled batch must respect AI cost cap (ADR-022).

## Constraints this ADR imposes
- One signal can contribute to multiple dimensions (different weights per dimension).
- Weight resolution: `vertical_lead_signal_weight` (active version) → `lead_signal_definition.default_weight` → 0.
- `lead_dimension.confidence` is per-row, distinct from the standalone `ai_confidence` dimension.
- `lead_dimension` is append-only; "current value" is a derived view.
- `lead_dimension.value_numeric` and `value_text` mutually exclusive via CHECK; numeric for scale-style dimensions, text for enum-style (qualification, communication_readiness).
- Multi-touch attribution (`lead_source_attribution`): all touches retained, no cap.
- Communication readiness derived live; never stored.

## See also
- ARCHITECTURE-LOCK §2.3, §3
- ADR-035 (subsystem framing)
- ADR-022 (AI cost cap; informs scheduled recompute cadence)
- ADR-040 (event taxonomy feeds dimensions)
- ADR-041 (phone classification feeds communication_readiness)
