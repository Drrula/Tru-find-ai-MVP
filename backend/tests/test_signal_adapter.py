"""B.6A.2 unit tests for the SignalResult -> SignalObservation adapter.

Pure unit tests. No DB, no fixtures, no async. Per
docs/phase-b6a-plan.md §8.1.

Covers:
  - Mapping (name / score / source / gap / weight preserved into
    the right slots)
  - Boundary scores (0.0, 0.5, 1.0 all accepted)
  - Validation (score outside [0,1] raises ValueError)
  - Order preservation
  - Empty input
  - Frozen contract on SignalObservation
  - Value-dict shape matches the locked option-2 contract:
    {score, gap, weight_at_probe}
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.scoring_persistence import (
    LEGACY_ANALYZER_SOURCE,
    SignalObservation,
    signal_results_to_observations,
)
from app.domain.signals import SignalResult


def _make_signal_result(
    *,
    name: str = "reviews",
    score: float = 0.6,
    weight: float = 0.2,
    gap: str | None = None,
) -> SignalResult:
    return SignalResult(name=name, score=score, weight=weight, gap=gap)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def test_signal_name_preserved() -> None:
    obs = signal_results_to_observations(
        [_make_signal_result(name="website_presence")]
    )
    assert obs[0].signal_name == "website_presence"


def test_score_preserved_in_value_dict() -> None:
    obs = signal_results_to_observations(
        [_make_signal_result(score=0.6)]
    )
    assert obs[0].value["score"] == 0.6


def test_source_is_legacy_analyzer_v1() -> None:
    obs = signal_results_to_observations([_make_signal_result()])
    assert obs[0].source == LEGACY_ANALYZER_SOURCE
    assert obs[0].source == "legacy_analyzer:v1"


def test_gap_string_preserved_in_value_dict() -> None:
    obs = signal_results_to_observations(
        [_make_signal_result(gap="business has no website")]
    )
    assert obs[0].value["gap"] == "business has no website"


def test_gap_none_preserved_in_value_dict() -> None:
    """A None gap (signal looked healthy) must round-trip as None,
    not be coerced to the empty string or dropped."""
    obs = signal_results_to_observations(
        [_make_signal_result(gap=None)]
    )
    assert obs[0].value["gap"] is None


def test_weight_at_probe_preserved() -> None:
    """Legacy weight is persisted alongside score so divergence
    diagnostics can compare against the canonical weight without
    re-reading the legacy pack."""
    obs = signal_results_to_observations(
        [_make_signal_result(weight=0.3)]
    )
    assert obs[0].value["weight_at_probe"] == 0.3


# ---------------------------------------------------------------------------
# Boundary scores
# ---------------------------------------------------------------------------


def test_score_boundary_zero_accepted() -> None:
    obs = signal_results_to_observations(
        [_make_signal_result(score=0.0)]
    )
    assert obs[0].value["score"] == 0.0


def test_score_boundary_one_accepted() -> None:
    obs = signal_results_to_observations(
        [_make_signal_result(score=1.0)]
    )
    assert obs[0].value["score"] == 1.0


def test_score_midpoint_accepted() -> None:
    obs = signal_results_to_observations(
        [_make_signal_result(score=0.5)]
    )
    assert obs[0].value["score"] == 0.5


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_score_below_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"outside \[0\.0, 1\.0\]"):
        signal_results_to_observations(
            [_make_signal_result(score=-0.1)]
        )


def test_score_above_one_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"outside \[0\.0, 1\.0\]"):
        signal_results_to_observations(
            [_make_signal_result(score=1.1)]
        )


def test_value_error_includes_signal_name() -> None:
    """Operators reading a failure need to know WHICH signal misbehaved."""
    with pytest.raises(ValueError, match=r"reviews"):
        signal_results_to_observations(
            [_make_signal_result(name="reviews", score=2.0)]
        )


def test_invalid_score_aborts_before_partial_translation() -> None:
    """A ValueError on the SECOND signal must abort the whole
    translation -- the caller never sees a partial list. (Atomicity
    of the pure function; the orchestrator at B.6A.4 has its own
    transactional atomicity guarantee for the DB writes.)"""
    results = [
        _make_signal_result(name="ok", score=0.5),
        _make_signal_result(name="bad", score=1.5),
    ]
    with pytest.raises(ValueError):
        signal_results_to_observations(results)


# ---------------------------------------------------------------------------
# Order + empty input
# ---------------------------------------------------------------------------


def test_order_preserved() -> None:
    results = [
        _make_signal_result(name="website_presence", score=0.9),
        _make_signal_result(name="google_business_presence", score=0.7),
        _make_signal_result(name="content_signals", score=0.5),
        _make_signal_result(name="reviews", score=0.3),
    ]
    obs = signal_results_to_observations(results)
    assert [o.signal_name for o in obs] == [
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    ]


def test_empty_input_returns_empty_output() -> None:
    assert signal_results_to_observations([]) == []


# ---------------------------------------------------------------------------
# Frozen contract + value-dict shape
# ---------------------------------------------------------------------------


def test_signal_observation_is_frozen_on_signal_name() -> None:
    obs = signal_results_to_observations([_make_signal_result()])[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        obs.signal_name = "different"  # type: ignore[misc]


def test_signal_observation_is_frozen_on_source() -> None:
    obs = signal_results_to_observations([_make_signal_result()])[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        obs.source = "different"  # type: ignore[misc]


def test_value_dict_has_locked_option2_keys() -> None:
    """Per phase-b6a-plan.md §4.2 locked option 2:
    value dict carries exactly {score, gap, weight_at_probe}."""
    obs = signal_results_to_observations([_make_signal_result()])[0]
    assert set(obs.value.keys()) == {"score", "gap", "weight_at_probe"}
