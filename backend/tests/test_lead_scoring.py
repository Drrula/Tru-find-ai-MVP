"""B.5.2 behavior tests for `app.domain.leads.scoring.compute_lead_score`.

Mock-only. Mocks `LeadSignalRepository.find_current` +
`VerticalLeadSignalWeightRepository.find_all_active_for_vertical`
so each test specifies exactly the weights + observations the
compute logic sees.

Covers:
- ComputedLeadScore shape (frozen dataclass, three fields).
- No weights configured -> (0, no_weights_configured, {}).
- Single weight + observation -> correct weighted score.
- Multiple weights all observed -> correct weighted average.
- Missing observation excluded from weighted sum (does NOT drag
  the score down).
- All weights have missing observations -> (0, all_signals_unobserved).
- Missing 'score' key in observation value -> ValueError.
- weight_version_at defaults to now_fn(); passes through to repo.
- weight_version_at explicit -> historical-replay path.
- Decimal precision preserved (2dp quantize to match numeric(5,2)).
- Per-dimension contributions captured in breakdown.
- Numerics in breakdown serialized as strings (replay-safe JSONB).
- ComputedLeadScore is frozen (callers can't mutate).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.db.models import Lead, LeadSignal, VerticalLeadSignalWeight
from app.domain.leads.scoring import ComputedLeadScore, compute_lead_score


# --- Helpers


def _make_lead(account_id: UUID | None = None) -> Lead:
    return Lead(
        id=uuid4(),
        account_id=account_id or uuid4(),
        source="test",
        lifecycle_state="cold",
    )


def _make_weight(
    vertical_id: UUID,
    *,
    signal_name: str,
    dimension: str = "lead_quality",
    weight: str = "0.5",
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> VerticalLeadSignalWeight:
    return VerticalLeadSignalWeight(
        id=uuid4(),
        vertical_id=vertical_id,
        signal_name=signal_name,
        dimension=dimension,
        weight=Decimal(weight),
        enabled=True,
        effective_from=effective_from or datetime.now(timezone.utc),
        effective_to=effective_to,
    )


def _make_signal(
    lead: Lead,
    *,
    signal_name: str,
    score: float | str | Decimal,
    source: str = "test",
    extra_keys: dict | None = None,
) -> LeadSignal:
    """Build a LeadSignal whose value has the convention 'score' key."""
    now = datetime.now(timezone.utc)
    value: dict = {"score": score}
    if extra_keys:
        value.update(extra_keys)
    return LeadSignal(
        id=uuid4(),
        account_id=lead.account_id,
        lead_id=lead.id,
        signal_name=signal_name,
        value=value,
        source=source,
        observed_at=now,
        recorded_at=now,
    )


def _repos(
    *,
    weights: list[VerticalLeadSignalWeight],
    observations_by_signal_name: dict[str, LeadSignal | None],
) -> tuple[AsyncMock, AsyncMock]:
    """Build the two mock repos with the supplied data."""
    weight_repo = AsyncMock()
    weight_repo.find_all_active_for_vertical = AsyncMock(return_value=weights)

    lead_signal_repo = AsyncMock()

    async def _find_current(lead_id: UUID, signal_name: str) -> LeadSignal | None:
        return observations_by_signal_name.get(signal_name)

    lead_signal_repo.find_current = AsyncMock(side_effect=_find_current)
    return lead_signal_repo, weight_repo


# --- ComputedLeadScore shape


def test_computed_lead_score_is_frozen_dataclass() -> None:
    result = ComputedLeadScore(
        score=Decimal("0.00"), breakdown={}, inputs={}
    )
    with pytest.raises(FrozenInstanceError):
        result.score = Decimal("99.99")  # type: ignore[misc]


def test_computed_lead_score_has_three_fields() -> None:
    result = ComputedLeadScore(
        score=Decimal("42.00"),
        breakdown={"key": "value"},
        inputs={"signals": {}},
    )
    assert result.score == Decimal("42.00")
    assert result.breakdown == {"key": "value"}
    assert result.inputs == {"signals": {}}


# --- No weights configured (plan §2 #5)


async def test_no_weights_returns_zero_with_documented_reason() -> None:
    lead = _make_lead()
    lead_signal_repo, weight_repo = _repos(
        weights=[], observations_by_signal_name={}
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=uuid4(),
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    assert result.score == Decimal("0.00")
    assert result.breakdown["reason"] == "no_weights_configured"
    assert result.breakdown["signal_contributions"] == []
    assert result.breakdown["unobserved"] == []
    assert result.inputs == {"signals": {}}
    # `lead_signal_repo.find_current` is never called when there are
    # no weights -- short-circuit.
    lead_signal_repo.find_current.assert_not_called()


# --- Happy paths


async def test_single_weight_single_observation_produces_correct_score() -> None:
    """One weight at 0.5 with observation score 0.6 -> blended score:
    (0.5 * 0.6) / 0.5 * 100 = 60.00.
    """
    vertical_id = uuid4()
    lead = _make_lead()
    weight = _make_weight(vertical_id, signal_name="s1", weight="0.5")
    obs = _make_signal(lead, signal_name="s1", score=0.6)

    lead_signal_repo, weight_repo = _repos(
        weights=[weight], observations_by_signal_name={"s1": obs}
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    assert result.score == Decimal("60.00")
    contribs = result.breakdown["signal_contributions"]
    assert len(contribs) == 1
    assert contribs[0]["signal_name"] == "s1"
    assert contribs[0]["value"] == "0.6"
    # Test fixture builds Decimal("0.5") -> str is "0.5". When the
    # weight is loaded from a real numeric(4,3) column it would
    # round-trip as "0.500"; this test bypasses the DB so the raw
    # Decimal precision is what str() reflects.
    assert contribs[0]["weight"] == "0.5"
    # Numerics in breakdown are strings (replay-safe JSONB).
    assert isinstance(contribs[0]["contribution"], str)


async def test_multiple_weights_all_observed_produces_weighted_average() -> None:
    """Two weights (0.3, 0.7) with observations (1.0, 0.0):
    (0.3*1.0 + 0.7*0.0) / 1.0 * 100 = 30.00.
    """
    vertical_id = uuid4()
    lead = _make_lead()
    weights = [
        _make_weight(vertical_id, signal_name="s1", weight="0.3"),
        _make_weight(vertical_id, signal_name="s2", weight="0.7"),
    ]
    obs_map = {
        "s1": _make_signal(lead, signal_name="s1", score=1.0),
        "s2": _make_signal(lead, signal_name="s2", score=0.0),
    }
    lead_signal_repo, weight_repo = _repos(
        weights=weights, observations_by_signal_name=obs_map
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    assert result.score == Decimal("30.00")
    assert len(result.breakdown["signal_contributions"]) == 2
    assert result.breakdown["unobserved"] == []


# --- Missing observations (plan §2 #6)


async def test_missing_observation_excluded_from_weighted_sum_not_dragging_score() -> None:
    """Two weights (0.3, 0.7) but only s1 has an observation (score 1.0):
    (0.3*1.0) / 0.3 * 100 = 100.00 -- the missing s2 doesn't pull
    the score down to (0.3*1.0)/1.0*100 = 30.00.
    """
    vertical_id = uuid4()
    lead = _make_lead()
    weights = [
        _make_weight(vertical_id, signal_name="s1", weight="0.3"),
        _make_weight(vertical_id, signal_name="s2", weight="0.7"),
    ]
    obs_map = {
        "s1": _make_signal(lead, signal_name="s1", score=1.0),
        "s2": None,
    }
    lead_signal_repo, weight_repo = _repos(
        weights=weights, observations_by_signal_name=obs_map
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    assert result.score == Decimal("100.00")
    # s2 lands in unobserved, NOT signal_contributions.
    assert len(result.breakdown["signal_contributions"]) == 1
    assert result.breakdown["signal_contributions"][0]["signal_name"] == "s1"
    unobs = result.breakdown["unobserved"]
    assert len(unobs) == 1
    assert unobs[0]["signal_name"] == "s2"
    assert unobs[0]["weight"] == "0.7"


async def test_all_observations_missing_returns_zero_with_documented_reason() -> None:
    """Plan §2 #6 follow-up: if every weight had no observation,
    total_weight is 0 -- explicit all_signals_unobserved outcome,
    no division-by-zero exception."""
    vertical_id = uuid4()
    lead = _make_lead()
    weights = [
        _make_weight(vertical_id, signal_name="s1", weight="0.3"),
        _make_weight(vertical_id, signal_name="s2", weight="0.7"),
    ]
    lead_signal_repo, weight_repo = _repos(
        weights=weights,
        observations_by_signal_name={"s1": None, "s2": None},
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    assert result.score == Decimal("0.00")
    assert result.breakdown["reason"] == "all_signals_unobserved"
    assert len(result.breakdown["unobserved"]) == 2
    assert result.inputs == {"signals": {}}


# --- Missing 'score' key (plan §2 #4)


async def test_missing_score_key_raises_value_error() -> None:
    """No silent fallback when lead_signal.value lacks the required
    'score' key. Convention is explicit; deviation surfaces loudly."""
    vertical_id = uuid4()
    lead = _make_lead()
    weight = _make_weight(vertical_id, signal_name="s1", weight="0.5")

    # Build a LeadSignal whose value DOESN'T have a 'score' key.
    bad_obs = LeadSignal(
        id=uuid4(),
        account_id=lead.account_id,
        lead_id=lead.id,
        signal_name="s1",
        value={"not_a_score": 0.7},
        source="test",
        observed_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
    )

    lead_signal_repo, weight_repo = _repos(
        weights=[weight], observations_by_signal_name={"s1": bad_obs}
    )

    with pytest.raises(ValueError, match="missing required 'score' key"):
        await compute_lead_score(
            lead=lead,
            vertical_id=vertical_id,
            lead_signal_repo=lead_signal_repo,
            weight_repo=weight_repo,
        )


# --- weight_version_at semantics


async def test_weight_version_at_defaults_to_now_fn() -> None:
    """When weight_version_at is None, now_fn() supplies the timestamp
    passed to find_all_active_for_vertical."""
    vertical_id = uuid4()
    lead = _make_lead()
    fixed_now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    lead_signal_repo, weight_repo = _repos(
        weights=[], observations_by_signal_name={}
    )

    await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
        now_fn=lambda: fixed_now,
    )

    weight_repo.find_all_active_for_vertical.assert_awaited_once_with(
        vertical_id, at_time=fixed_now
    )


async def test_explicit_weight_version_at_passes_through_for_replay() -> None:
    """Replay path: caller supplies historical weight_version_at;
    it's the timestamp used to resolve active weights AND recorded
    on the breakdown for future audit."""
    vertical_id = uuid4()
    lead = _make_lead()
    historical = datetime(2026, 4, 1, tzinfo=timezone.utc)
    now = datetime(2026, 5, 11, tzinfo=timezone.utc)

    lead_signal_repo, weight_repo = _repos(
        weights=[], observations_by_signal_name={}
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
        weight_version_at=historical,
        now_fn=lambda: now,
    )

    # Active weights query uses the historical timestamp.
    weight_repo.find_all_active_for_vertical.assert_awaited_once_with(
        vertical_id, at_time=historical
    )
    # breakdown.weight_version_at records the historical timestamp,
    # not now_fn(), so the snapshot is replay-faithful.
    assert result.breakdown["weight_version_at"] == historical.isoformat()


# --- Decimal precision + JSONB serialization


async def test_score_is_quantized_to_two_decimal_places() -> None:
    """numeric(5,2) target column requires 2dp; compute quantizes
    the raw Decimal so the score round-trips through the DB intact."""
    vertical_id = uuid4()
    lead = _make_lead()
    # Use a case where raw arithmetic creates more precision than 2dp.
    weight = _make_weight(vertical_id, signal_name="s1", weight="0.333")
    obs = _make_signal(lead, signal_name="s1", score=Decimal("0.123456"))
    lead_signal_repo, weight_repo = _repos(
        weights=[weight], observations_by_signal_name={"s1": obs}
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    # score has exactly 2 fractional digits.
    assert result.score.as_tuple().exponent == -2


async def test_breakdown_numerics_are_strings_for_jsonb_round_trip() -> None:
    """Decimal -> str in breakdown so JSONB serialization preserves
    precision (vs JSON's float which loses precision on round-trip)."""
    vertical_id = uuid4()
    lead = _make_lead()
    weight = _make_weight(vertical_id, signal_name="s1", weight="0.5")
    obs = _make_signal(lead, signal_name="s1", score=0.7)
    lead_signal_repo, weight_repo = _repos(
        weights=[weight], observations_by_signal_name={"s1": obs}
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    b = result.breakdown
    assert isinstance(b["total_weight"], str)
    assert isinstance(b["weighted_sum"], str)
    assert isinstance(b["score"], str)
    for c in b["signal_contributions"]:
        assert isinstance(c["value"], str)
        assert isinstance(c["weight"], str)
        assert isinstance(c["contribution"], str)


async def test_breakdown_captures_per_dimension_aggregates() -> None:
    """Plan §2 #7: single overall score, but per-dimension contributions
    captured in breakdown for future analysis without re-running compute."""
    vertical_id = uuid4()
    lead = _make_lead()
    weights = [
        _make_weight(
            vertical_id,
            signal_name="s1",
            dimension="lead_quality",
            weight="0.3",
        ),
        _make_weight(
            vertical_id,
            signal_name="s2",
            dimension="engagement",
            weight="0.5",
        ),
    ]
    obs_map = {
        "s1": _make_signal(lead, signal_name="s1", score=0.8),
        "s2": _make_signal(lead, signal_name="s2", score=0.4),
    }
    lead_signal_repo, weight_repo = _repos(
        weights=weights, observations_by_signal_name=obs_map
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    dims = result.breakdown["dimensions"]
    assert set(dims.keys()) == {"lead_quality", "engagement"}
    assert isinstance(dims["lead_quality"]["weighted_sum"], str)
    assert isinstance(dims["lead_quality"]["total_weight"], str)


async def test_inputs_preserves_full_observation_value_payload() -> None:
    """inputs payload is the FROZEN copy used at scoring time --
    preserves the full lead_signal.value (with provenance keys beyond
    'score') so the snapshot is replay-safe."""
    vertical_id = uuid4()
    lead = _make_lead()
    weight = _make_weight(vertical_id, signal_name="s1", weight="0.5")
    obs = _make_signal(
        lead,
        signal_name="s1",
        score=0.7,
        extra_keys={"provider": "google", "raw_count": 42},
        source="webhook",
    )
    lead_signal_repo, weight_repo = _repos(
        weights=[weight], observations_by_signal_name={"s1": obs}
    )

    result = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
    )

    s1_input = result.inputs["signals"]["s1"]
    assert s1_input["value"] == {
        "score": 0.7,
        "provider": "google",
        "raw_count": 42,
    }
    assert s1_input["source"] == "webhook"
    assert "observed_at" in s1_input  # ISO-format string


# --- Public surface re-export


def test_compute_lead_score_exposed_via_app_domain_leads() -> None:
    """Per phase-b5-plan.md §3 + inspectability discipline."""
    import app.domain.leads as leads_pkg

    assert "compute_lead_score" in leads_pkg.__all__
    assert "ComputedLeadScore" in leads_pkg.__all__
    assert callable(leads_pkg.compute_lead_score)
