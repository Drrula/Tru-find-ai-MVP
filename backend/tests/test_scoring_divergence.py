"""B.6A.3 unit tests for the divergence comparator.

Pure unit tests. No DB, no fixtures, no async. Per
docs/phase-b6a-plan.md §8.1 + the explainability-first directive.

Covers:
  - Mapping: per-signal join by signal_name
  - Math: delta, within_tolerance, contribution_delta
  - Edge cases: legacy-only signal, canonical-only signal,
    unobserved canonical signal (weight exists, no observation),
    empty canonical contributions / weights
  - Dataclass contract: both frozen; optional fields default None
  - Explain renderer: contains signal names + totals; multi-line;
    tolerance status text
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.db.models import VerticalLeadSignalWeight
from app.domain.leads.scoring import ComputedLeadScore
from unittest.mock import MagicMock

from app.domain.scoring_divergence import (
    BRIDGE_DIVERGENCE_EVENT,
    BRIDGE_DIVERGENCE_TOLERANCE,
    ScoreDivergence,
    SignalContributionDiff,
    compute_divergence,
    explain_divergence,
    log_divergence,
)
from app.domain.signals import SignalResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _legacy(
    name: str = "reviews",
    score: float = 0.6,
    weight: float = 0.2,
) -> SignalResult:
    return SignalResult(name=name, score=score, weight=weight, gap=None)


def _canonical_contrib(
    signal_name: str,
    value: str,
    weight: str,
    dimension: str = "lead_quality",
) -> dict[str, object]:
    return {
        "signal_name": signal_name,
        "dimension": dimension,
        "value": value,
        "weight": weight,
        "contribution": str(Decimal(value) * Decimal(weight)),
    }


def _canonical_weight(
    vertical_id: UUID,
    signal_name: str,
    weight: str = "0.300",
) -> VerticalLeadSignalWeight:
    return VerticalLeadSignalWeight(
        id=uuid4(),
        vertical_id=vertical_id,
        signal_name=signal_name,
        dimension="lead_quality",
        weight=Decimal(weight),
        enabled=True,
        effective_from=datetime(2026, 5, 11, tzinfo=timezone.utc),
    )


def _computed(
    score: str,
    contributions: list[dict[str, object]] | None = None,
    *,
    weight_version_at: datetime | None = None,
) -> ComputedLeadScore:
    if weight_version_at is None:
        weight_version_at = datetime(2026, 5, 11, tzinfo=timezone.utc)
    return ComputedLeadScore(
        score=Decimal(score),
        breakdown={
            "vertical_id": "test",
            "weight_version_at": weight_version_at.isoformat(),
            "signal_contributions": contributions or [],
            "dimensions": {},
            "unobserved": [],
            "total_weight": "1.000",
            "weighted_sum": str(Decimal(score) / Decimal("100")),
            "score": score,
        },
        inputs={"signals": {}},
    )


# ---------------------------------------------------------------------------
# Mapping: per-signal join
# ---------------------------------------------------------------------------


def test_diff_has_one_row_per_signal_name_across_both_sides() -> None:
    vertical_id = uuid4()
    legacy = [
        _legacy(name="website_presence", score=0.9, weight=0.3),
        _legacy(name="reviews", score=0.6, weight=0.2),
    ]
    canonical_weights = [
        _canonical_weight(vertical_id, "website_presence", "0.300"),
        _canonical_weight(vertical_id, "reviews", "0.200"),
    ]
    contributions = [
        _canonical_contrib("website_presence", "0.9", "0.300"),
        _canonical_contrib("reviews", "0.6", "0.200"),
    ]
    div = compute_divergence(
        legacy_score=60,
        legacy_results=legacy,
        canonical_computed=_computed("60.00", contributions),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    names = [d.signal_name for d in div.signal_breakdown]
    assert names == ["reviews", "website_presence"]  # sorted


def test_diff_rows_are_sorted_by_signal_name() -> None:
    """Deterministic ordering for inspectability."""
    vertical_id = uuid4()
    legacy = [_legacy(name="zzz", score=0.5, weight=0.5)]
    canonical_weights = [_canonical_weight(vertical_id, "aaa", "0.500")]
    div = compute_divergence(
        legacy_score=50,
        legacy_results=legacy,
        canonical_computed=_computed("50.00"),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    assert [d.signal_name for d in div.signal_breakdown] == ["aaa", "zzz"]


# ---------------------------------------------------------------------------
# Math: delta + within_tolerance
# ---------------------------------------------------------------------------


def test_delta_is_legacy_minus_int_canonical() -> None:
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.49"),
        canonical_weights=[],
    )
    # int(Decimal("60.49")) = 60
    assert div.delta == 0


def test_delta_when_legacy_higher() -> None:
    div = compute_divergence(
        legacy_score=61,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    assert div.delta == 1


def test_delta_when_canonical_higher() -> None:
    div = compute_divergence(
        legacy_score=58,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    assert div.delta == -2


def test_within_tolerance_true_when_delta_zero() -> None:
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    assert div.within_tolerance is True


def test_within_tolerance_true_at_boundary_plus_one() -> None:
    div = compute_divergence(
        legacy_score=61,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    assert abs(div.delta) == BRIDGE_DIVERGENCE_TOLERANCE
    assert div.within_tolerance is True


def test_within_tolerance_true_at_boundary_minus_one() -> None:
    div = compute_divergence(
        legacy_score=59,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    assert div.delta == -1
    assert div.within_tolerance is True


def test_within_tolerance_false_when_delta_exceeds() -> None:
    div = compute_divergence(
        legacy_score=62,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    assert div.delta == 2
    assert div.within_tolerance is False


def test_tolerance_constant_is_one_in_mirror_phase() -> None:
    """Locked at 1 for B.6A; tightens to 0 in B.6B."""
    assert BRIDGE_DIVERGENCE_TOLERANCE == 1


# ---------------------------------------------------------------------------
# Math: contribution_delta
# ---------------------------------------------------------------------------


def test_contribution_delta_is_canonical_minus_legacy() -> None:
    """Per dataclass docstring: positive delta means canonical
    weighted the signal MORE than legacy did."""
    vertical_id = uuid4()
    legacy = [_legacy(name="x", score=0.5, weight=0.2)]
    contributions = [
        _canonical_contrib("x", "0.5", "0.300"),  # bigger weight
    ]
    canonical_weights = [_canonical_weight(vertical_id, "x", "0.300")]
    div = compute_divergence(
        legacy_score=50,
        legacy_results=legacy,
        canonical_computed=_computed("50.00", contributions),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    row = div.signal_breakdown[0]
    assert row.legacy_contribution == Decimal("0.10")  # 0.5 * 0.2
    assert row.canonical_contribution == Decimal("0.1500")  # 0.5 * 0.300
    assert row.contribution_delta == Decimal("0.0500")


def test_contribution_delta_negative_when_canonical_weighs_less() -> None:
    vertical_id = uuid4()
    legacy = [_legacy(name="x", score=0.8, weight=0.5)]
    contributions = [_canonical_contrib("x", "0.8", "0.200")]
    canonical_weights = [_canonical_weight(vertical_id, "x", "0.200")]
    div = compute_divergence(
        legacy_score=80,
        legacy_results=legacy,
        canonical_computed=_computed("80.00", contributions),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    row = div.signal_breakdown[0]
    assert row.contribution_delta < 0


# ---------------------------------------------------------------------------
# Edge cases: missing-on-either-side + unobserved
# ---------------------------------------------------------------------------


def test_legacy_only_signal_canonical_fields_are_zero() -> None:
    """Signal in legacy, no canonical weight active: canonical
    side fills with Decimal('0')."""
    legacy = [_legacy(name="orphan", score=0.7, weight=0.5)]
    div = compute_divergence(
        legacy_score=70,
        legacy_results=legacy,
        canonical_computed=_computed("0.00"),
        canonical_weights=[],
    )
    row = next(
        d for d in div.signal_breakdown if d.signal_name == "orphan"
    )
    assert row.legacy_score == Decimal("0.7")
    assert row.canonical_score == Decimal("0")
    assert row.canonical_weight == Decimal("0")
    assert row.canonical_contribution == Decimal("0")


def test_canonical_only_signal_legacy_fields_are_zero() -> None:
    """Signal has a canonical weight active but no legacy result:
    legacy side fills with Decimal('0')."""
    vertical_id = uuid4()
    canonical_weights = [_canonical_weight(vertical_id, "newcomer", "0.250")]
    contributions = [_canonical_contrib("newcomer", "0.6", "0.250")]
    div = compute_divergence(
        legacy_score=0,
        legacy_results=[],
        canonical_computed=_computed("15.00", contributions),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    row = next(
        d for d in div.signal_breakdown if d.signal_name == "newcomer"
    )
    assert row.legacy_score == Decimal("0")
    assert row.legacy_weight == Decimal("0")
    assert row.legacy_contribution == Decimal("0")
    assert row.canonical_score == Decimal("0.6")
    assert row.canonical_weight == Decimal("0.250")


def test_unobserved_canonical_signal_shows_weight_but_zero_score() -> None:
    """Signal has a canonical weight but compute_lead_score excluded
    it (no observation): canonical_score = 0, canonical_weight =
    the weight row's weight, canonical_contribution = 0."""
    vertical_id = uuid4()
    legacy = [_legacy(name="ghost", score=0.4, weight=0.300)]
    canonical_weights = [
        _canonical_weight(vertical_id, "ghost", "0.300"),
    ]
    # Empty signal_contributions -- canonical_weights present but
    # compute_lead_score excluded the signal.
    div = compute_divergence(
        legacy_score=40,
        legacy_results=legacy,
        canonical_computed=_computed("0.00"),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    row = next(
        d for d in div.signal_breakdown if d.signal_name == "ghost"
    )
    assert row.canonical_score == Decimal("0")
    assert row.canonical_weight == Decimal("0.300")
    assert row.canonical_contribution == Decimal("0")


def test_empty_inputs_produce_empty_breakdown() -> None:
    div = compute_divergence(
        legacy_score=0,
        legacy_results=[],
        canonical_computed=_computed("0.00"),
        canonical_weights=[],
    )
    assert div.signal_breakdown == []
    assert div.delta == 0
    assert div.within_tolerance is True


# ---------------------------------------------------------------------------
# Dataclass contract
# ---------------------------------------------------------------------------


def test_signal_contribution_diff_is_frozen() -> None:
    diff = SignalContributionDiff(
        signal_name="x",
        legacy_score=Decimal("0.5"),
        canonical_score=Decimal("0.5"),
        legacy_weight=Decimal("0.2"),
        canonical_weight=Decimal("0.2"),
        legacy_contribution=Decimal("0.10"),
        canonical_contribution=Decimal("0.10"),
        contribution_delta=Decimal("0"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        diff.signal_name = "y"  # type: ignore[misc]


def test_score_divergence_is_frozen() -> None:
    div = ScoreDivergence(
        legacy_score=60,
        canonical_score=Decimal("60.00"),
        delta=0,
        within_tolerance=True,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        div.legacy_score = 99  # type: ignore[misc]


def test_canonical_score_field_is_decimal() -> None:
    """Per option A locked 2026-05-11: canonical_score is Decimal,
    not int -- preserves 2dp precision for diagnostic rendering."""
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.49"),
        canonical_weights=[],
    )
    assert isinstance(div.canonical_score, Decimal)
    assert div.canonical_score == Decimal("60.49")


def test_optional_ids_default_none() -> None:
    div = compute_divergence(
        legacy_score=0,
        legacy_results=[],
        canonical_computed=_computed("0.00"),
        canonical_weights=[],
    )
    assert div.lead_id is None
    assert div.snapshot_id is None


def test_lead_id_and_snapshot_id_pass_through() -> None:
    lead_id = uuid4()
    snapshot_id = uuid4()
    div = compute_divergence(
        legacy_score=0,
        legacy_results=[],
        canonical_computed=_computed("0.00"),
        canonical_weights=[],
        lead_id=lead_id,
        snapshot_id=snapshot_id,
    )
    assert div.lead_id == lead_id
    assert div.snapshot_id == snapshot_id


def test_weight_version_at_and_vertical_id_pass_through() -> None:
    v_id = uuid4()
    wv_at = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    div = compute_divergence(
        legacy_score=0,
        legacy_results=[],
        canonical_computed=_computed("0.00"),
        canonical_weights=[],
        vertical_id=v_id,
        weight_version_at=wv_at,
    )
    assert div.vertical_id == v_id
    assert div.weight_version_at == wv_at


# ---------------------------------------------------------------------------
# explain_divergence
# ---------------------------------------------------------------------------


def test_explain_is_multiline_string() -> None:
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    rendered = explain_divergence(div)
    assert isinstance(rendered, str)
    assert "\n" in rendered


def test_explain_contains_legacy_canonical_delta_and_tolerance_status() -> None:
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    rendered = explain_divergence(div)
    assert "legacy=60" in rendered
    assert "canonical=60.00" in rendered
    assert "delta=" in rendered
    assert "within tolerance" in rendered


def test_explain_marks_outside_tolerance_loudly() -> None:
    div = compute_divergence(
        legacy_score=70,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    rendered = explain_divergence(div)
    # Uppercase form per the renderer -- loud signal in logs.
    assert "OUTSIDE tolerance" in rendered


def test_explain_renders_each_signal_name_on_its_own_line() -> None:
    vertical_id = uuid4()
    legacy = [
        _legacy(name="website_presence", score=0.9, weight=0.300),
        _legacy(name="google_business_presence", score=0.7, weight=0.300),
        _legacy(name="content_signals", score=0.5, weight=0.200),
        _legacy(name="reviews", score=0.3, weight=0.200),
    ]
    canonical_weights = [
        _canonical_weight(vertical_id, n, w)
        for n, w in [
            ("website_presence", "0.300"),
            ("google_business_presence", "0.300"),
            ("content_signals", "0.200"),
            ("reviews", "0.200"),
        ]
    ]
    contributions = [
        _canonical_contrib("website_presence", "0.9", "0.300"),
        _canonical_contrib("google_business_presence", "0.7", "0.300"),
        _canonical_contrib("content_signals", "0.5", "0.200"),
        _canonical_contrib("reviews", "0.3", "0.200"),
    ]
    div = compute_divergence(
        legacy_score=58,
        legacy_results=legacy,
        canonical_computed=_computed("58.00", contributions),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    rendered = explain_divergence(div)
    for name in (
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    ):
        assert name in rendered


def test_explain_includes_optional_lead_and_snapshot_ids_when_set() -> None:
    lead_id = uuid4()
    snapshot_id = uuid4()
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
        lead_id=lead_id,
        snapshot_id=snapshot_id,
    )
    rendered = explain_divergence(div)
    assert str(lead_id) in rendered
    assert str(snapshot_id) in rendered


def test_explain_omits_optional_ids_when_none() -> None:
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )
    rendered = explain_divergence(div)
    assert "lead_id" not in rendered
    assert "snapshot_id" not in rendered


# ---------------------------------------------------------------------------
# log_divergence (B.6A.4)
# ---------------------------------------------------------------------------


def _div_at_delta(delta: int) -> ScoreDivergence:
    """Build a minimal ScoreDivergence with the requested delta."""
    return compute_divergence(
        legacy_score=60 + delta,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
    )


def test_log_divergence_emits_debug_when_delta_zero() -> None:
    logger = MagicMock()
    div = _div_at_delta(0)
    log_divergence(div, logger)
    logger.debug.assert_called_once()
    logger.info.assert_not_called()
    logger.error.assert_not_called()


def test_log_divergence_emits_info_at_tolerance_boundary_plus_one() -> None:
    logger = MagicMock()
    div = _div_at_delta(1)
    log_divergence(div, logger)
    logger.info.assert_called_once()
    logger.debug.assert_not_called()
    logger.error.assert_not_called()


def test_log_divergence_emits_info_at_tolerance_boundary_minus_one() -> None:
    logger = MagicMock()
    div = _div_at_delta(-1)
    log_divergence(div, logger)
    logger.info.assert_called_once()
    logger.debug.assert_not_called()
    logger.error.assert_not_called()


def test_log_divergence_emits_error_when_outside_tolerance() -> None:
    logger = MagicMock()
    div = _div_at_delta(5)
    log_divergence(div, logger)
    logger.error.assert_called_once()
    logger.debug.assert_not_called()
    logger.info.assert_not_called()


def test_log_divergence_uses_canonical_event_name() -> None:
    """Every bridge log line carries the same `event` name so a single
    grep finds all divergence emissions across deployments."""
    logger = MagicMock()
    log_divergence(_div_at_delta(0), logger)
    args, _kwargs = logger.debug.call_args
    assert args[0] == BRIDGE_DIVERGENCE_EVENT
    assert BRIDGE_DIVERGENCE_EVENT == "bridge.score_comparison"


def test_log_divergence_payload_has_required_keys() -> None:
    logger = MagicMock()
    div = _div_at_delta(0)
    log_divergence(div, logger)
    _args, kwargs = logger.debug.call_args
    required = {
        "legacy_score",
        "canonical_score",
        "delta",
        "within_tolerance",
        "tolerance",
        "signal_breakdown",
    }
    assert required.issubset(kwargs.keys())


def test_log_divergence_payload_serializes_decimals_as_strings() -> None:
    """JSONB-safety: canonical_score and per-signal Decimals must be
    string-typed in the payload so structlog's JSON renderer cannot
    silently coerce them."""
    logger = MagicMock()
    vertical_id = uuid4()
    legacy = [SignalResult(name="x", score=0.5, weight=0.2, gap=None)]
    canonical_weights = [_canonical_weight(vertical_id, "x", "0.200")]
    contributions = [_canonical_contrib("x", "0.5", "0.200")]
    div = compute_divergence(
        legacy_score=50,
        legacy_results=legacy,
        canonical_computed=_computed("50.00", contributions),
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
    )
    log_divergence(div, logger)
    _args, kwargs = logger.debug.call_args
    assert isinstance(kwargs["canonical_score"], str)
    assert kwargs["canonical_score"] == "50.00"
    for entry in kwargs["signal_breakdown"]:
        for k in (
            "legacy_score",
            "canonical_score",
            "legacy_weight",
            "canonical_weight",
            "legacy_contribution",
            "canonical_contribution",
            "contribution_delta",
        ):
            assert isinstance(entry[k], str), f"{k!r} should be str-typed"


def test_log_divergence_payload_serializes_uuids_and_datetimes() -> None:
    logger = MagicMock()
    vertical_id = uuid4()
    lead_id = uuid4()
    snapshot_id = uuid4()
    wv_at = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    div = compute_divergence(
        legacy_score=60,
        legacy_results=[],
        canonical_computed=_computed("60.00"),
        canonical_weights=[],
        vertical_id=vertical_id,
        weight_version_at=wv_at,
        lead_id=lead_id,
        snapshot_id=snapshot_id,
    )
    log_divergence(div, logger)
    _args, kwargs = logger.debug.call_args
    assert kwargs["vertical_id"] == str(vertical_id)
    assert kwargs["lead_id"] == str(lead_id)
    assert kwargs["snapshot_id"] == str(snapshot_id)
    assert kwargs["weight_version_at"] == wv_at.isoformat()


def test_log_divergence_omits_optional_fields_when_none() -> None:
    logger = MagicMock()
    div = _div_at_delta(0)  # no optional ids set
    log_divergence(div, logger)
    _args, kwargs = logger.debug.call_args
    # These optional fields must NOT appear when their source was None.
    assert "vertical_id" not in kwargs
    assert "weight_version_at" not in kwargs
    assert "lead_id" not in kwargs
    assert "snapshot_id" not in kwargs


def test_log_divergence_no_module_default_logger() -> None:
    """The function MUST require an explicit logger param. A test
    that omits it should fail at call time, not silently emit to
    some module-level default."""
    div = _div_at_delta(0)
    with pytest.raises(TypeError):
        log_divergence(div)  # type: ignore[call-arg]
