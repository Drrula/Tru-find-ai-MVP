"""Pure-function tests for the mock signals.

Each signal in `app/domain/signals.py` is
`(business_name, location) -> SignalResult`. These tests pin the
contract: shape, determinism, registry size, weight normalization. The
signal interface is consumed by the scoring orchestrator
(`app/domain/scoring.py`); breaking it silently would cascade into
incorrect scores. Per the strategic direction, scoring stays deterministic
and these tests guard that.
"""

from __future__ import annotations

import pytest

from app.domain.signals import (
    SIGNALS,
    SignalResult,
    content_signals,
    google_business_presence,
    reviews,
    website_presence,
)

ALL_SIGNALS = [website_presence, google_business_presence, content_signals, reviews]


@pytest.mark.parametrize("signal", ALL_SIGNALS, ids=lambda s: s.__name__)
def test_signal_returns_valid_signal_result(signal) -> None:
    result = signal("Joe Pizza", "Brooklyn, NY")
    assert isinstance(result, SignalResult)
    assert isinstance(result.name, str) and result.name
    assert 0.0 <= result.score <= 1.0
    assert 0.0 < result.weight <= 1.0
    assert result.gap is None or isinstance(result.gap, str)


@pytest.mark.parametrize("signal", ALL_SIGNALS, ids=lambda s: s.__name__)
def test_signal_is_deterministic(signal) -> None:
    """Same input must yield the same SignalResult across calls. The mock
    signals are deterministic by design (md5-based) so the scoring engine
    is reproducible — this guards regressions that would break that."""
    a = signal("Joe Pizza", "Brooklyn, NY")
    b = signal("Joe Pizza", "Brooklyn, NY")
    assert a == b


def test_signal_registry_size_pinned() -> None:
    """`SIGNALS` list is the registry consumed by the orchestrator.
    Adding/removing a signal should be a deliberate change picked up here."""
    assert len(SIGNALS) == 4


def test_signal_weights_sum_to_one() -> None:
    """The blended score divides by total weight; sum=1 keeps the math simple
    and matches the conventional probability-distribution interpretation."""
    total = sum(s("Joe Pizza", "Brooklyn, NY").weight for s in SIGNALS)
    assert total == pytest.approx(1.0)


def test_signal_names_are_unique() -> None:
    """Signal names are used as registry keys (and downstream as
    `signal_definition.name` in Phase B). Duplicate names would silently
    overwrite earlier entries."""
    names = [s("Joe Pizza", "Brooklyn, NY").name for s in SIGNALS]
    assert len(names) == len(set(names))


def test_signals_resolve_via_domain_path() -> None:
    """Locked layout per ADR-007: signals live under app.domain."""
    from app.domain import signals as _signals  # noqa: F401


def test_known_baseline_score_inputs() -> None:
    """Joe Pizza / Brooklyn, NY produces the deterministic baseline used
    across the smoke suite. If this changes, A.3-A.12 baseline-preservation
    assertions all fail simultaneously — pinning here surfaces the regression
    at the signal level instead of the integration level."""
    from app.domain.scoring import analyze

    response = analyze("Joe Pizza", "Brooklyn, NY")
    assert response.score == 60
