"""Mirror-phase bridge between the legacy analyzer and the canonical
persistence stack.

Per docs/phase-b6a-plan.md §4.2 (B.6A.2 -- adapter only). Future
sub-phases extend this module:
  - B.6A.4 adds the `analyze_and_persist` orchestrator.

B.6A.2 surface is intentionally narrow: ONE pure function and ONE
frozen transport dataclass. No DB, no I/O, no runtime integration,
no public-API exposure. The adapter is dark code -- nothing in
production calls it yet.

Mirror-first discipline (per
`feedback_staged_convergence_mirror_first.md`):
  - The legacy `analyze()` in `app/domain/scoring.py` is NOT
    modified.
  - The legacy `SIGNALS` registry in `app/domain/signals.py` is NOT
    modified.
  - No HTTP route is wired to this module.

Value-dict shape (locked 2026-05-11, option 2 per
phase-b6a-plan.md §4.2 + the explainability-first directive in
`feedback_explainability_first_for_bridges.md`):

    {
        "score":           float in [0.0, 1.0],   # required (per
                                                  # phase-b5-plan.md
                                                  # §2 #4 -- compute_
                                                  # lead_score reads
                                                  # this key)
        "gap":             str | None,            # legacy gap copy
                                                  # at probe time
        "weight_at_probe": float,                 # legacy pack
                                                  # weight at probe
                                                  # time (NOT the
                                                  # canonical weight)
    }

Persisting `gap` and `weight_at_probe` makes each `lead_signal` row
self-describing for replay + divergence diagnostics: a future
operator (or the B.6A.3 comparator) can reconstruct the legacy
probe state from the persisted observation alone.

The persisted `weight_at_probe` is provenance, NOT a weight the
canonical compute path reads -- canonical reads its weights from
`vertical_lead_signal_weight`. Keeping both pinned to the same
observation makes weight-drift diagnoses trivial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.signals import SignalResult

#: Source identifier stamped on every observation produced by this
#: adapter. Versioned (`:v1`) so a future adapter variant can be
#: distinguished in the lead_signal.source column without renaming.
LEGACY_ANALYZER_SOURCE: str = "legacy_analyzer:v1"


@dataclass(frozen=True)
class SignalObservation:
    """Transport shape: a single legacy SignalResult translated into
    the `(signal_name, value, source)` triple that
    `record_lead_signal` consumes.

    NOT persisted. NOT a public API. Frozen so callers cannot mutate
    after construction; the `value` dict itself is technically still
    mutable (dataclass frozen only prevents attribute reassignment),
    but callers must treat it as immutable. The B.6A.4 orchestrator
    constructs a fresh dict per call and passes it directly to
    `record_lead_signal`.
    """

    signal_name: str
    value: dict[str, Any]
    source: str


def signal_results_to_observations(
    results: list[SignalResult],
) -> list[SignalObservation]:
    """Translate legacy `SignalResult` instances into observation
    triples.

    Pure function: no DB, no I/O, no side effects, no clock reads.
    Order is preserved (output[i] corresponds to input[i]). Empty
    input returns empty output without error.

    Each observation's `value` dict carries the score (required by
    `compute_lead_score._extract_score_value`), the legacy gap copy,
    and the legacy weight at probe time -- see module docstring for
    the locked shape and rationale.

    Raises:
        ValueError: if any `SignalResult.score` is outside [0.0,
            1.0]. Matches the contract `compute_lead_score` expects
            of the persisted `value['score']` per phase-b5-plan.md
            §2 #4. Fail-loud, no silent clamping.
    """
    observations: list[SignalObservation] = []
    for r in results:
        if not (0.0 <= r.score <= 1.0):
            raise ValueError(
                f"SignalResult[{r.name!r}].score = {r.score!r} is "
                f"outside [0.0, 1.0]"
            )
        observations.append(
            SignalObservation(
                signal_name=r.name,
                value={
                    "score": r.score,
                    "gap": r.gap,
                    "weight_at_probe": r.weight,
                },
                source=LEGACY_ANALYZER_SOURCE,
            )
        )
    return observations
