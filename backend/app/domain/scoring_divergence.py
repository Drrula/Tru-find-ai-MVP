"""Mirror-phase divergence comparator (pure logic).

Per docs/phase-b6a-plan.md §4.3 + §7 + the explainability-first
directive (`feedback_explainability_first_for_bridges.md`).

The comparator is the EXPLAINABILITY surface of B.6A. Its job is to
answer "WHY do the legacy and canonical scores agree or disagree?"
with row-by-row signal- and weight-provenance attribution. The
highest-value B.6A outcome is NOT "the bridge exists"; it is
"we can confidently explain the bridge's behavior."

B.6A.3 SCOPE (narrowest safe):
  - Two frozen dataclasses: SignalContributionDiff, ScoreDivergence
  - One tolerance constant: BRIDGE_DIVERGENCE_TOLERANCE
  - Two pure functions: compute_divergence, explain_divergence

DEFERRED TO B.6A.4 (alongside the orchestrator that calls them):
  - log_divergence -- structured-log emitter (structlog wiring
    decision lives at the call site, not here)
  - to_log_dict -- JSON-serializable rendering (deferred until
    log_divergence needs it)
  - Any caller / integration / public-API exposure

PURE. No DB, no I/O, no clock, no globals mutated. No async. The
comparator can be unit-tested in isolation against handcrafted
fixtures; it does not require a database or a running app.

Mirror-first discipline intact:
  - Does NOT import from app.domain.scoring (legacy compute path)
  - Does NOT modify any existing file
  - Does NOT register with any public surface
  - Is dark code -- no production caller yet (B.6A.4 will be the
    first caller, inside analyze_and_persist)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.db.models import VerticalLeadSignalWeight
from app.domain.leads.scoring import ComputedLeadScore
from app.domain.signals import SignalResult


#: Mirror-phase tolerance for legacy-vs-canonical integer-score
#: divergence. Set to 1 so banker's-rounding-vs-quantize boundary
#: cases (e.g. true score = 60.50: legacy rounds to 60, canonical
#: quantizes to 60.50) do not register as drift.
#:
#: Tightens to 0 in B.6B once legacy is retired and there is a
#: single source of truth.
BRIDGE_DIVERGENCE_TOLERANCE: int = 1


@dataclass(frozen=True)
class SignalContributionDiff:
    """One row of the per-signal divergence table.

    Numerics are Decimal so the comparator preserves precision from
    both sides exactly:
      - legacy_score / legacy_weight from SignalResult floats,
        converted via Decimal(str(...)) to round-trip cleanly
      - canonical_score / canonical_weight from
        compute_lead_score's breakdown dict (numerics already
        serialized as Decimal-safe strings)

    `contribution_delta = canonical_contribution - legacy_contribution`
    so a positive delta means the canonical side weighted the
    signal MORE than legacy did, and vice versa. Negative deltas
    pull the canonical aggregate DOWN relative to legacy.
    """

    signal_name: str
    legacy_score: Decimal
    canonical_score: Decimal
    legacy_weight: Decimal
    canonical_weight: Decimal
    legacy_contribution: Decimal
    canonical_contribution: Decimal
    contribution_delta: Decimal


@dataclass(frozen=True)
class ScoreDivergence:
    """Per-call divergence report.

    `legacy_score` is int because legacy `_blended_score` returns
    int (`round(...)`). `canonical_score` is Decimal because
    `compute_lead_score` produces `Decimal(5,2)` precision. `delta`
    is computed as `legacy_score - int(canonical_score)` -- the
    integer comparison surface; the Decimal precision is preserved
    in the per-signal breakdown for diagnostics (option A locked
    2026-05-11 per phase-b6a-plan.md §4.3).

    `lead_id` and `snapshot_id` are optional; the comparator can be
    called in test contexts before any persistence. The orchestrator
    (B.6A.4) populates them post-write.
    """

    legacy_score: int
    canonical_score: Decimal
    delta: int
    within_tolerance: bool
    signal_breakdown: list[SignalContributionDiff] = field(default_factory=list)
    weight_version_at: datetime | None = None
    vertical_id: UUID | None = None
    lead_id: UUID | None = None
    snapshot_id: UUID | None = None


# ---------------------------------------------------------------------------
# compute_divergence
# ---------------------------------------------------------------------------


def _zero_diff(signal_name: str, *, legacy: SignalResult | None,
               canonical_weight: Decimal) -> SignalContributionDiff:
    """Build a per-signal diff row when one side has nothing for it.

    Helper for the legacy-only and canonical-only / unobserved cases:
    the absent side is filled with Decimal('0').
    """
    if legacy is not None:
        leg_score = Decimal(str(legacy.score))
        leg_weight = Decimal(str(legacy.weight))
        leg_contrib = leg_score * leg_weight
    else:
        leg_score = Decimal("0")
        leg_weight = Decimal("0")
        leg_contrib = Decimal("0")
    can_score = Decimal("0")
    can_weight = canonical_weight
    can_contrib = Decimal("0")
    return SignalContributionDiff(
        signal_name=signal_name,
        legacy_score=leg_score,
        canonical_score=can_score,
        legacy_weight=leg_weight,
        canonical_weight=can_weight,
        legacy_contribution=leg_contrib,
        canonical_contribution=can_contrib,
        contribution_delta=can_contrib - leg_contrib,
    )


def compute_divergence(
    *,
    legacy_score: int,
    legacy_results: list[SignalResult],
    canonical_computed: ComputedLeadScore,
    canonical_weights: list[VerticalLeadSignalWeight],
    vertical_id: UUID | None = None,
    weight_version_at: datetime | None = None,
    lead_id: UUID | None = None,
    snapshot_id: UUID | None = None,
) -> ScoreDivergence:
    """Pure comparator. Joins legacy and canonical views by
    `signal_name` and produces a fully-populated ScoreDivergence.

    `legacy_score` is passed in (caller computed via
    `_blended_score(legacy_results)`) so this function does NOT
    duplicate the legacy aggregator -- single source of truth for
    the legacy formula stays in `app/domain/scoring.py`.

    Per-signal join rules:
      - Signal in legacy AND canonical (observed): use
        canonical_computed.breakdown['signal_contributions'][i]
        for canonical scoring; SignalResult.score/weight for legacy.
      - Signal in canonical_weights only (active weight but
        unobserved -- compute_lead_score excluded it from the sum
        per phase-b5-plan.md §2 #6): canonical_score = 0,
        canonical_weight = the weight row's weight, canonical_contribution = 0.
      - Signal in legacy only (no canonical weight active): canonical
        fields = 0.
      - Signal in canonical only (weight active but no legacy
        result): legacy fields = 0.

    Returns a ScoreDivergence with breakdown sorted by signal_name
    for deterministic test output and operator-friendly rendering.
    """
    legacy_by_name = {r.name: r for r in legacy_results}

    # Observed canonical signals -- carried in
    # compute_lead_score's breakdown['signal_contributions'] with
    # all numerics serialized as Decimal-safe strings.
    canonical_contribs_by_name: dict[str, dict[str, Any]] = {
        c["signal_name"]: c
        for c in canonical_computed.breakdown.get("signal_contributions", [])
    }

    # ALL active canonical weights (observed or not). Catches the
    # unobserved-signal case explicitly.
    canonical_weights_by_name = {w.signal_name: w for w in canonical_weights}

    all_names = sorted(
        set(legacy_by_name.keys()) | set(canonical_weights_by_name.keys())
    )

    breakdown: list[SignalContributionDiff] = []
    for name in all_names:
        legacy = legacy_by_name.get(name)
        canonical_contrib = canonical_contribs_by_name.get(name)
        canonical_weight_row = canonical_weights_by_name.get(name)

        # Legacy side
        if legacy is not None:
            leg_score = Decimal(str(legacy.score))
            leg_weight = Decimal(str(legacy.weight))
            leg_contrib = leg_score * leg_weight
        else:
            leg_score = Decimal("0")
            leg_weight = Decimal("0")
            leg_contrib = Decimal("0")

        # Canonical side
        if canonical_contrib is not None:
            can_score = Decimal(canonical_contrib["value"])
            can_weight = Decimal(canonical_contrib["weight"])
            can_contrib = Decimal(canonical_contrib["contribution"])
        elif canonical_weight_row is not None:
            # Weight exists but signal was unobserved.
            can_score = Decimal("0")
            can_weight = canonical_weight_row.weight
            can_contrib = Decimal("0")
        else:
            # Signal in legacy only.
            can_score = Decimal("0")
            can_weight = Decimal("0")
            can_contrib = Decimal("0")

        breakdown.append(
            SignalContributionDiff(
                signal_name=name,
                legacy_score=leg_score,
                canonical_score=can_score,
                legacy_weight=leg_weight,
                canonical_weight=can_weight,
                legacy_contribution=leg_contrib,
                canonical_contribution=can_contrib,
                contribution_delta=can_contrib - leg_contrib,
            )
        )

    delta = legacy_score - int(canonical_computed.score)
    within = abs(delta) <= BRIDGE_DIVERGENCE_TOLERANCE

    return ScoreDivergence(
        legacy_score=legacy_score,
        canonical_score=canonical_computed.score,
        delta=delta,
        within_tolerance=within,
        signal_breakdown=breakdown,
        weight_version_at=weight_version_at,
        vertical_id=vertical_id,
        lead_id=lead_id,
        snapshot_id=snapshot_id,
    )


# ---------------------------------------------------------------------------
# explain_divergence
# ---------------------------------------------------------------------------


def _sign(d: Decimal) -> str:
    return "+" if d >= 0 else ""


def explain_divergence(divergence: ScoreDivergence) -> str:
    """Human-readable multi-line render. Used in test failure
    output AND (future) operator-facing logs.

    Layout:
      header: legacy / canonical / delta / tolerance status
      identity: vertical_id, weight_version_at, optional lead/snapshot
      per-signal breakdown table (one line per signal)

    Pure; no side effects. Returns a single str with embedded
    newlines.
    """
    status = (
        "within tolerance"
        if divergence.within_tolerance
        else "OUTSIDE tolerance"
    )
    sign = "+" if divergence.delta >= 0 else ""
    lines: list[str] = [
        f"Score divergence: "
        f"legacy={divergence.legacy_score} "
        f"canonical={divergence.canonical_score} "
        f"delta={sign}{divergence.delta} "
        f"({status} +/-{BRIDGE_DIVERGENCE_TOLERANCE})",
    ]
    if divergence.vertical_id is not None:
        lines.append(f"  vertical_id={divergence.vertical_id}")
    if divergence.weight_version_at is not None:
        lines.append(
            f"  weight_version_at={divergence.weight_version_at.isoformat()}"
        )
    if divergence.lead_id is not None:
        lines.append(f"  lead_id={divergence.lead_id}")
    if divergence.snapshot_id is not None:
        lines.append(f"  snapshot_id={divergence.snapshot_id}")
    lines.append("  per-signal breakdown:")
    for d in divergence.signal_breakdown:
        delta_str = f"{_sign(d.contribution_delta)}{d.contribution_delta}"
        lines.append(
            f"    {d.signal_name}: "
            f"legacy={d.legacy_score}*{d.legacy_weight}={d.legacy_contribution} "
            f"canonical={d.canonical_score}*{d.canonical_weight}="
            f"{d.canonical_contribution} "
            f"delta={delta_str}"
        )
    return "\n".join(lines)
