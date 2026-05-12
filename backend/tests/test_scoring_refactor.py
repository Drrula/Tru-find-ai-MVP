"""B.6B.1 parity tests for the scoring.py refactor.

Per docs/phase-b6b-plan.md §11 tests 1-5. Validates that the
refactor introducing `run_legacy_scoring()` + `LegacyScoringResult`
+ `_compute_blended_score` + `_blended_score` shim is BYTE-
IDENTICAL to the pre-B.6B behavior of `analyze()`.

The corpus inputs here mirror test_bridge_corpus.py's 10-input
corpus so the parity surface is the same shape as the B.6A.6
mirror-parity tests.

Mock-only -- no DB, no real I/O. The legacy scoring path is pure
deterministic (fetch_google_business is md5-based per B.6A
verification).
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from app.domain.scoring import (
    LegacyScoringResult,
    _blended_score,
    _compute_blended_score,
    analyze,
    run_legacy_scoring,
)
from app.domain.signals import SignalResult
from app.schemas import AnalyzeResponse


_CORPUS: list[tuple[str, str]] = [
    ("Joe Pizza", "Brooklyn, NY"),
    ("Acme Plumbing", "Austin, TX"),
    ("Sunset Yoga", "Portland, OR"),
    ("Mike's Auto Repair", "Chicago, IL"),
    ("Green Leaf Cafe", "Seattle, WA"),
    ("Riverside Dental", "Denver, CO"),
    ("Bright Smile Bakery", "Miami, FL"),
    ("Stone Path Landscaping", "Boston, MA"),
    ("Blue Wave Surf Shop", "San Diego, CA"),
    ("Polar Bear Plumbing", "Anchorage, AK"),
]


# ---------------------------------------------------------------------------
# Test 1: run_legacy_scoring returns LegacyScoringResult(response, signal_results)
# ---------------------------------------------------------------------------


def test_run_legacy_scoring_returns_correct_shape() -> None:
    result = run_legacy_scoring("Joe Pizza", "Brooklyn, NY")
    assert isinstance(result, LegacyScoringResult)
    assert isinstance(result.response, AnalyzeResponse)
    assert isinstance(result.signal_results, list)
    assert all(
        isinstance(r, SignalResult) for r in result.signal_results
    )


def test_run_legacy_scoring_signal_results_match_registry_size() -> None:
    """SIGNALS has 4 entries (website_presence,
    google_business_presence, content_signals, reviews). Helper
    must return exactly 4 results."""
    result = run_legacy_scoring("Joe Pizza", "Brooklyn, NY")
    assert len(result.signal_results) == 4
    names = {r.name for r in result.signal_results}
    assert names == {
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    }


# ---------------------------------------------------------------------------
# Test 2: byte-identical AnalyzeResponse across corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("business_name,location", _CORPUS)
def test_analyze_equals_run_legacy_scoring_response(
    business_name: str, location: str
) -> None:
    """`analyze()` is now a thin wrapper -- it MUST return exactly
    the same AnalyzeResponse as `run_legacy_scoring(...).response`
    for any input. This is the byte-identical contract."""
    direct = run_legacy_scoring(business_name, location).response
    wrapped = analyze(business_name, location)
    assert wrapped == direct
    assert wrapped.score == direct.score
    assert wrapped.gaps == direct.gaps
    assert wrapped.summary == direct.summary
    assert wrapped.category_scores == direct.category_scores
    assert wrapped.competitors == direct.competitors
    assert wrapped.trade == direct.trade


def test_baseline_joe_pizza_brooklyn_score_60_preserved() -> None:
    """The canonical regression guard. legacy `analyze('Joe Pizza',
    'Brooklyn, NY').score == 60` has held across every phase since
    B.5. The B.6B.1 refactor must not change this."""
    assert analyze("Joe Pizza", "Brooklyn, NY").score == 60


def test_trade_parameter_passes_through() -> None:
    """`analyze(..., trade=...)` populates AnalyzeResponse.trade
    via run_legacy_scoring -- shouldn't get lost in the refactor."""
    direct = run_legacy_scoring(
        "Joe Pizza", "Brooklyn, NY", trade="pizza"
    ).response
    wrapped = analyze("Joe Pizza", "Brooklyn, NY", trade="pizza")
    assert direct.trade == "pizza"
    assert wrapped.trade == "pizza"


# ---------------------------------------------------------------------------
# Test 3: _blended_score shim still importable + same return
# ---------------------------------------------------------------------------


def test_blended_score_shim_still_importable() -> None:
    """Per phase-b6b-plan.md §2 decision #8 + §11 test #3: the
    `_blended_score` symbol must remain importable from
    `app.domain.scoring` until B.6C+ retires the shim. This test
    is the canary that catches accidental shim removal during
    cleanup commits in this phase."""
    from app.domain import scoring

    assert hasattr(scoring, "_blended_score")
    assert callable(scoring._blended_score)


def test_blended_score_shim_returns_same_as_compute() -> None:
    results = [
        SignalResult(name="a", score=0.9, weight=0.3, gap=None),
        SignalResult(name="b", score=0.7, weight=0.3, gap=None),
        SignalResult(name="c", score=0.5, weight=0.2, gap=None),
        SignalResult(name="d", score=0.3, weight=0.2, gap=None),
    ]
    assert _blended_score(results) == _compute_blended_score(results)


# ---------------------------------------------------------------------------
# Test 4: _compute_blended_score math parity
# ---------------------------------------------------------------------------


def test_compute_blended_score_math_handcrafted() -> None:
    """Handcrafted input with known math:
       (0.5*0.5 + 1.0*0.5) / (0.5 + 0.5) * 100
     = (0.25 + 0.5) / 1.0 * 100
     = 0.75 * 100
     = 75
    """
    results = [
        SignalResult(name="a", score=0.5, weight=0.5, gap=None),
        SignalResult(name="b", score=1.0, weight=0.5, gap=None),
    ]
    assert _compute_blended_score(results) == 75


def test_compute_blended_score_zero_weight_fallback() -> None:
    """Pre-B.6B `_blended_score` used `or 1.0` fallback when total
    weight was zero. The shim + new helper must preserve this
    branch byte-identically."""
    results = [
        SignalResult(name="a", score=0.5, weight=0.0, gap=None),
        SignalResult(name="b", score=1.0, weight=0.0, gap=None),
    ]
    # weighted = 0.5*0 + 1.0*0 = 0
    # total_weight = 0 -> falls back to 1.0
    # score = round(0 / 1.0 * 100) = 0
    assert _compute_blended_score(results) == 0


def test_compute_blended_score_empty_results() -> None:
    """sum() on empty is 0; total_weight `or 1.0` fallback -> 1.0;
    blended = 0/1.0*100 = 0. Edge case preserved from legacy."""
    assert _compute_blended_score([]) == 0


# ---------------------------------------------------------------------------
# Test 5: analyze() signature unchanged
# ---------------------------------------------------------------------------


def test_analyze_signature_unchanged() -> None:
    """Public API stability: `analyze(business_name, location,
    trade=None) -> AnalyzeResponse`. The B.6B.1 refactor must not
    change the signature -- callers (HTTP routes, tests) depend
    on this shape."""
    sig = inspect.signature(analyze)
    params = sig.parameters

    assert list(params.keys()) == ["business_name", "location", "trade"]
    assert params["business_name"].annotation is str
    assert params["location"].annotation is str
    assert params["trade"].default is None
    # Trade is `str | None` -- inspect renders this as the union;
    # we assert against the resolved type-hints view.
    hints = get_type_hints(analyze)
    assert hints["business_name"] is str
    assert hints["location"] is str
    assert hints["trade"] == (str | None)
    assert hints["return"] is AnalyzeResponse


def test_analyze_is_synchronous_not_async() -> None:
    """B.6B.1 must NOT accidentally convert analyze() to async --
    the HTTP route handlers call it synchronously."""
    assert not inspect.iscoroutinefunction(analyze)
    assert not inspect.iscoroutinefunction(run_legacy_scoring)


# ---------------------------------------------------------------------------
# LegacyScoringResult frozen contract
# ---------------------------------------------------------------------------


def test_legacy_scoring_result_is_frozen() -> None:
    import dataclasses

    result = run_legacy_scoring("Joe Pizza", "Brooklyn, NY")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.response = result.response  # type: ignore[misc]
