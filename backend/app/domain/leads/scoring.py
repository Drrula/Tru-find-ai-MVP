"""Lead scoring -- pure deterministic compute primitive.

Per docs/phase-b5-plan.md §4 + §2 (decisions #4-#10) + ADR-010
replay semantics + ADR-036 (lead signals + dimensions).

`compute_lead_score` is a pure function: same `weight_version_at` +
same observed signals + same active weights at that version =
same score, deterministically. No I/O outside the supplied repos.
No `now()` calls except via the injected `now_fn`. No randomness.

Result shape: `ComputedLeadScore` (frozen dataclass) with three
fields:
  - score: Decimal in [0, 100], two-decimal precision
  - breakdown: dict mirroring phase-b5-plan.md §5 (per-signal
    contributions, per-dimension aggregates, unobserved list)
  - inputs: frozen dict of the signal observations consulted

Edge cases (per plan §2 #5 + #6):
  - No active weights for vertical → score=0, breakdown.reason =
    "no_weights_configured". No exception.
  - Weight exists but no observation → signal EXCLUDED from
    weighted sum (don't drag the score down); appears in
    breakdown.unobserved.
  - ALL weights have missing observations → score=0,
    breakdown.reason = "all_signals_unobserved".
  - `lead_signal.value` missing the top-level `'score'` key →
    ValueError. No silent fallback (plan §2 #4).

Numerics in breakdown + inputs are stored as STRINGS in the
JSONB-serializable dict so Decimal precision survives the round
trip (matches the pattern in vertical_template.config_json).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from app.db.models import Lead, LeadSignal, VerticalLeadSignalWeight
from app.db.repositories.lead_signal_repo import LeadSignalRepository
from app.db.repositories.vertical_lead_signal_weight_repo import (
    VerticalLeadSignalWeightRepository,
)


@dataclass(frozen=True)
class ComputedLeadScore:
    """Result of `compute_lead_score`. Frozen: callers cannot mutate.

    `score` is Decimal in [0.00, 100.00] (numeric(5,2) compatible).
    `breakdown` and `inputs` are JSONB-serializable dicts with
    Decimals already converted to strings.
    """

    score: Decimal
    breakdown: dict[str, Any]
    inputs: dict[str, Any]


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_score_value(signal_value: dict[str, Any], signal_name: str) -> Decimal:
    """Pull the 0..1 numeric component from a lead_signal value payload.

    Per phase-b5-plan.md §2 #4: every signal carries a top-level
    'score' key with a numeric in [0.0, 1.0]. Missing key raises --
    no silent fallback.
    """
    if "score" not in signal_value:
        raise ValueError(
            f"lead_signal[{signal_name!r}].value missing required 'score' "
            f"key; got keys: {sorted(signal_value.keys())}"
        )
    return Decimal(str(signal_value["score"]))


def _format_observation(signal: LeadSignal) -> dict[str, Any]:
    """Render one LeadSignal observation as a JSONB-serializable
    dict for the inputs payload. Preserves the full `value` (with
    'score' + any provenance keys) so the snapshot is replay-safe."""
    return {
        "value": signal.value,
        "observed_at": signal.observed_at.isoformat(),
        "source": signal.source,
    }


async def compute_lead_score(
    *,
    lead: Lead,
    vertical_id: UUID,
    lead_signal_repo: LeadSignalRepository,
    weight_repo: VerticalLeadSignalWeightRepository,
    weight_version_at: datetime | None = None,
    now_fn: Callable[[], datetime] = _default_now,
) -> ComputedLeadScore:
    """Compute a lead's score from stored observations + active weights.

    PURE function. Reads via the supplied repos; writes nothing.
    Caller decides whether to persist the result (`record_lead_score`
    in B.5.3 lands the helper that combines compute + write).

    `weight_version_at` defaults to now_fn() (current-state scoring).
    Pass explicitly to reproduce a past score against historical
    weight rows -- ADR-010 replay semantics.

    Returns a ComputedLeadScore with the score, full breakdown
    (per-signal + per-dimension), and a frozen copy of the
    observations consulted.
    """
    weight_at = weight_version_at if weight_version_at is not None else now_fn()

    weights: list[VerticalLeadSignalWeight] = (
        await weight_repo.find_all_active_for_vertical(
            vertical_id, at_time=weight_at
        )
    )

    if not weights:
        return ComputedLeadScore(
            score=Decimal("0.00"),
            breakdown={
                "reason": "no_weights_configured",
                "vertical_id": str(vertical_id),
                "weight_version_at": weight_at.isoformat(),
                "signal_contributions": [],
                "dimensions": {},
                "unobserved": [],
                "total_weight": "0",
                "weighted_sum": "0",
                "score": "0.00",
            },
            inputs={"signals": {}},
        )

    # Walk the active weights, collecting observed contributions and
    # unobserved entries explicitly.
    signal_contributions: list[dict[str, Any]] = []
    unobserved: list[dict[str, Any]] = []
    dimension_totals: dict[str, dict[str, Decimal]] = {}
    inputs_signals: dict[str, dict[str, Any]] = {}
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")

    for w in weights:
        observation: LeadSignal | None = await lead_signal_repo.find_current(
            lead.id, w.signal_name
        )

        if observation is None:
            # Per plan §2 #6: missing observations are EXCLUDED from
            # the weighted sum -- they do not drag the score down.
            unobserved.append(
                {
                    "signal_name": w.signal_name,
                    "dimension": w.dimension,
                    "weight": str(w.weight),
                }
            )
            continue

        # ValueError here propagates per plan §2 #4 -- no silent
        # fallback when the score key is missing.
        value = _extract_score_value(observation.value, w.signal_name)
        weight = w.weight  # already Decimal from numeric(4,3)
        contribution = weight * value

        signal_contributions.append(
            {
                "signal_name": w.signal_name,
                "dimension": w.dimension,
                "value": str(value),
                "weight": str(weight),
                "contribution": str(contribution),
            }
        )

        dim = dimension_totals.setdefault(
            w.dimension,
            {"weighted_sum": Decimal("0"), "total_weight": Decimal("0")},
        )
        dim["weighted_sum"] += contribution
        dim["total_weight"] += weight

        total_weight += weight
        weighted_sum += contribution

        # Snapshot the observation under signal_name for the inputs
        # payload. If multiple weight rows share a signal_name (multi-
        # dimension), the same observation appears once -- dict
        # assignment is idempotent.
        inputs_signals[w.signal_name] = _format_observation(observation)

    if total_weight == 0:
        # Per plan §2 #6 follow-up: if every weight had no
        # observation, total_weight is 0 -- avoid division by zero
        # with an explicit "all_signals_unobserved" outcome.
        return ComputedLeadScore(
            score=Decimal("0.00"),
            breakdown={
                "reason": "all_signals_unobserved",
                "vertical_id": str(vertical_id),
                "weight_version_at": weight_at.isoformat(),
                "signal_contributions": [],
                "dimensions": {},
                "unobserved": unobserved,
                "total_weight": "0",
                "weighted_sum": "0",
                "score": "0.00",
            },
            inputs={"signals": {}},
        )

    # Score formula per plan §2 #9.
    # Quantize to 2dp to match the numeric(5,2) target column.
    raw_score = (weighted_sum / total_weight) * Decimal("100")
    score = raw_score.quantize(Decimal("0.01"))

    return ComputedLeadScore(
        score=score,
        breakdown={
            "vertical_id": str(vertical_id),
            "weight_version_at": weight_at.isoformat(),
            "signal_contributions": signal_contributions,
            "dimensions": {
                name: {
                    "weighted_sum": str(d["weighted_sum"]),
                    "total_weight": str(d["total_weight"]),
                }
                for name, d in dimension_totals.items()
            },
            "unobserved": unobserved,
            "total_weight": str(total_weight),
            "weighted_sum": str(weighted_sum),
            "score": str(score),
        },
        inputs={"signals": inputs_signals},
    )
