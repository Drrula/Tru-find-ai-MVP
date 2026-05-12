"""B.6A.4 mock-heavy tests for the mirror-phase orchestrator.

Per docs/phase-b6a-plan.md §8.2. Real DB integration is deferred
to B.6A.5 (corpus + replay tests).

Monkeypatches at the orchestrator's import surface so the legacy
analyze() + SIGNALS run + compute_lead_score + record_lead_signal
+ compute_divergence + log_divergence are all controllable from
the test.

Covers:
  - Happy path: 1 Lead + 4 LeadSignals + 1 LeadScoreSnapshot in
    order; BridgeResult populated; divergence within tolerance;
    log emitted (DEBUG or INFO)
  - Outside-tolerance divergence: log emitted at ERROR
  - All-or-nothing atomicity: record_lead_signal raising on
    the 3rd call aborts before record_lead_score; snapshot not
    staged
  - BridgeResult shape: response is the legacy AnalyzeResponse;
    snapshot is the staged LeadScoreSnapshot; divergence has the
    expected lead_id + snapshot_id
  - BridgeResult is frozen
  - now_fn injection: same `now` value used for observed_at,
    weight_version_at, computed_at
  - Lead source = "bridge:legacy_analyzer:v1"
  - log_divergence called exactly once
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import dataclasses
import pytest

from app.db.models import Lead, LeadScoreSnapshot
from app.domain.leads.scoring import ComputedLeadScore
from app.domain.scoring_persistence import (
    BRIDGE_LEAD_SOURCE,
    BridgeResult,
    analyze_and_persist,
)
from app.domain.signals import SignalResult
from app.schemas import AnalyzeResponse, CategoryScores, Competitor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_response(score: int = 60) -> AnalyzeResponse:
    return AnalyzeResponse(
        score=score,
        gaps=["fake gap"],
        summary="fake summary",
        category_scores=CategoryScores(
            ai_presence=50,
            seo_strength=60,
            authority=70,
            performance=40,
        ),
        competitors=[Competitor(name="comp", score=75)],
        trade=None,
    )


def _fake_signals(scores: list[float] | None = None) -> list:
    """Build 4 fake SIGNAL callables that return controlled scores."""
    if scores is None:
        scores = [0.9, 0.7, 0.5, 0.3]
    names = [
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    ]
    weights = [0.30, 0.30, 0.20, 0.20]
    return [
        (lambda name=n, score=s, weight=w:
            (lambda _bn, _loc: SignalResult(
                name=name, score=score, weight=weight, gap=None
            )))()
        for n, s, w in zip(names, scores, weights)
    ]


def _fake_computed(score: str = "60.00") -> ComputedLeadScore:
    return ComputedLeadScore(
        score=Decimal(score),
        breakdown={
            "vertical_id": "test",
            "weight_version_at": "2026-05-11T12:00:00+00:00",
            "signal_contributions": [
                {
                    "signal_name": n,
                    "dimension": "lead_quality",
                    "value": str(s),
                    "weight": str(w),
                    "contribution": str(Decimal(str(s)) * Decimal(str(w))),
                }
                for n, s, w in (
                    ("website_presence", "0.9", "0.300"),
                    ("google_business_presence", "0.7", "0.300"),
                    ("content_signals", "0.5", "0.200"),
                    ("reviews", "0.3", "0.200"),
                )
            ],
            "dimensions": {},
            "unobserved": [],
            "total_weight": "1.000",
            "weighted_sum": str(Decimal(score) / Decimal("100")),
            "score": score,
        },
        inputs={"signals": {}},
    )


def _make_lead(account_id: UUID, vertical_id: UUID) -> Lead:
    return Lead(
        id=uuid4(),
        account_id=account_id,
        vertical_id=vertical_id,
        source=BRIDGE_LEAD_SOURCE,
        lifecycle_state="cold",
    )


def _make_snapshot(
    lead: Lead, vertical_id: UUID, score: str = "60.00"
) -> LeadScoreSnapshot:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    return LeadScoreSnapshot(
        id=uuid4(),
        account_id=lead.account_id,
        lead_id=lead.id,
        vertical_id=vertical_id,
        score=Decimal(score),
        score_breakdown={"score": score},
        inputs={"signals": {}},
        weight_version_at=now,
        computed_at=now,
    )


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def vertical_id() -> UUID:
    return uuid4()


@pytest.fixture
def repos(
    account_id: UUID,
    vertical_id: UUID,
):
    """Construct 5 AsyncMock repos with sensible default returns."""
    lead = _make_lead(account_id, vertical_id)
    snapshot = _make_snapshot(lead, vertical_id)

    lead_repo = AsyncMock()
    lead_repo.create = AsyncMock(return_value=lead)

    lead_signal_repo = AsyncMock()

    signal_definition_repo = AsyncMock()

    weight_repo = AsyncMock()
    weight_repo.find_all_active_for_vertical = AsyncMock(return_value=[])

    score_repo = AsyncMock()
    score_repo.create = AsyncMock(return_value=snapshot)

    return {
        "lead": lead,
        "snapshot": snapshot,
        "lead_repo": lead_repo,
        "lead_signal_repo": lead_signal_repo,
        "signal_definition_repo": signal_definition_repo,
        "weight_repo": weight_repo,
        "score_repo": score_repo,
    }


@pytest.fixture
def patch_orchestrator_deps(monkeypatch):
    """Patch analyze(), SIGNALS, compute_lead_score, and
    record_lead_signal at the orchestrator's import path so the
    orchestrator gets controlled inputs."""

    def _apply(
        *,
        analyze_response: AnalyzeResponse,
        signal_scores: list[float] | None = None,
        computed: ComputedLeadScore | None = None,
        record_signal_side_effect=None,
    ):
        monkeypatch.setattr(
            "app.domain.scoring_persistence.analyze",
            lambda bn, loc, trade=None: analyze_response,
        )
        monkeypatch.setattr(
            "app.domain.scoring_persistence.SIGNALS",
            _fake_signals(signal_scores),
        )
        if computed is None:
            computed = _fake_computed("60.00")
        monkeypatch.setattr(
            "app.domain.scoring_persistence.compute_lead_score",
            AsyncMock(return_value=computed),
        )
        record_mock = AsyncMock(
            side_effect=record_signal_side_effect
            if record_signal_side_effect is not None
            else None
        )
        monkeypatch.setattr(
            "app.domain.scoring_persistence.record_lead_signal",
            record_mock,
        )
        return record_mock

    return _apply


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_persists_lead_signals_snapshot_in_order(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    record_mock = patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
    )
    logger = MagicMock()

    result = await analyze_and_persist(
        business_name="Joe Pizza",
        location="Brooklyn, NY",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    # Lead created with bridge source.
    repos["lead_repo"].create.assert_awaited_once()
    create_kwargs = repos["lead_repo"].create.await_args.kwargs
    assert create_kwargs["account_id"] == account_id
    assert create_kwargs["vertical_id"] == vertical_id
    assert create_kwargs["source"] == BRIDGE_LEAD_SOURCE

    # 4 lead_signal records, one per legacy signal.
    assert record_mock.await_count == 4

    # Snapshot staged exactly once.
    repos["score_repo"].create.assert_awaited_once()
    score_kwargs = repos["score_repo"].create.await_args.kwargs
    assert score_kwargs["lead"] is repos["lead"]
    assert score_kwargs["vertical_id"] == vertical_id
    assert score_kwargs["score"] == Decimal("60.00")
    assert score_kwargs["computed_at"] == fixed_now
    assert score_kwargs["weight_version_at"] == fixed_now

    # BridgeResult populated.
    assert isinstance(result, BridgeResult)
    assert result.response.score == 60
    assert result.snapshot is repos["snapshot"]
    assert result.divergence.legacy_score == 60
    assert result.divergence.delta == 0
    assert result.divergence.within_tolerance is True


async def test_happy_path_emits_debug_log_when_delta_zero(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
    )
    logger = MagicMock()

    await analyze_and_persist(
        business_name="x",
        location="y",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    logger.debug.assert_called_once()
    args, _ = logger.debug.call_args
    assert args[0] == "bridge.score_comparison"


async def test_happy_path_each_observation_passes_correct_value_dict(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    record_mock = patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
        signal_scores=[0.9, 0.7, 0.5, 0.3],
    )
    logger = MagicMock()

    await analyze_and_persist(
        business_name="x",
        location="y",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    # The first lead_signal call should be website_presence with
    # score=0.9, weight_at_probe=0.30, source=legacy_analyzer:v1.
    first_call_kwargs = record_mock.await_args_list[0].kwargs
    assert first_call_kwargs["signal_name"] == "website_presence"
    assert first_call_kwargs["value"]["score"] == 0.9
    assert first_call_kwargs["value"]["weight_at_probe"] == 0.30
    assert first_call_kwargs["source"] == "legacy_analyzer:v1"


# ---------------------------------------------------------------------------
# Divergence severity
# ---------------------------------------------------------------------------


async def test_emits_info_when_within_tolerance_but_nonzero_delta(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    """legacy=60, canonical=59 -> delta=1 (within tolerance)."""
    patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("59.00"),
    )
    logger = MagicMock()

    result = await analyze_and_persist(
        business_name="x",
        location="y",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    assert result.divergence.delta == 1
    assert result.divergence.within_tolerance is True
    logger.info.assert_called_once()
    logger.debug.assert_not_called()
    logger.error.assert_not_called()


async def test_emits_error_when_outside_tolerance(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    """legacy=60, canonical=55 -> delta=5 (outside tolerance)."""
    patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("55.00"),
    )
    logger = MagicMock()

    result = await analyze_and_persist(
        business_name="x",
        location="y",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    assert result.divergence.delta == 5
    assert result.divergence.within_tolerance is False
    logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# All-or-nothing atomicity
# ---------------------------------------------------------------------------


async def test_third_signal_failure_aborts_before_snapshot(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    """record_lead_signal raises on the 3rd call. The orchestrator
    must NOT call record_lead_score / score_repo.create. The
    exception propagates so the caller's session rolls back."""
    # Side effects: first 2 succeed, 3rd raises ValueError
    # (e.g. simulated catalog miss).
    call_count = {"n": 0}

    async def flaky_record(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise ValueError("simulated catalog miss for signal #3")
        return MagicMock()

    record_mock = patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
        record_signal_side_effect=flaky_record,
    )
    logger = MagicMock()

    with pytest.raises(ValueError, match="catalog miss"):
        await analyze_and_persist(
            business_name="x",
            location="y",
            trade=None,
            account_id=account_id,
            vertical_id=vertical_id,
            lead_repo=repos["lead_repo"],
            lead_signal_repo=repos["lead_signal_repo"],
            signal_definition_repo=repos["signal_definition_repo"],
            weight_repo=repos["weight_repo"],
            score_repo=repos["score_repo"],
            logger=logger,
            now_fn=lambda: fixed_now,
        )

    # First 2 record_lead_signal calls happened (staged); 3rd raised.
    assert record_mock.await_count == 3
    # Snapshot stage MUST NOT have been called.
    repos["score_repo"].create.assert_not_called()
    # Divergence emission also skipped (orchestrator aborted before
    # reaching the log).
    logger.debug.assert_not_called()
    logger.info.assert_not_called()
    logger.error.assert_not_called()


async def test_lead_signal_failure_does_not_swallow_exception(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    """The orchestrator MUST NOT catch + swallow record_lead_signal
    exceptions. Caller controls rollback; silent failure would
    leak partial state on commit."""
    patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
        record_signal_side_effect=ValueError("boom"),
    )
    logger = MagicMock()

    with pytest.raises(ValueError, match="boom"):
        await analyze_and_persist(
            business_name="x",
            location="y",
            trade=None,
            account_id=account_id,
            vertical_id=vertical_id,
            lead_repo=repos["lead_repo"],
            lead_signal_repo=repos["lead_signal_repo"],
            signal_definition_repo=repos["signal_definition_repo"],
            weight_repo=repos["weight_repo"],
            score_repo=repos["score_repo"],
            logger=logger,
            now_fn=lambda: fixed_now,
        )


# ---------------------------------------------------------------------------
# BridgeResult contract
# ---------------------------------------------------------------------------


async def test_bridge_result_carries_legacy_response_unchanged(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    response = _fake_response(60)
    patch_orchestrator_deps(
        analyze_response=response,
        computed=_fake_computed("60.00"),
    )
    logger = MagicMock()

    result = await analyze_and_persist(
        business_name="x",
        location="y",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    # response is the SAME object the legacy analyze() returned.
    assert result.response is response


async def test_bridge_result_divergence_includes_lead_and_snapshot_ids(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
    )
    logger = MagicMock()

    result = await analyze_and_persist(
        business_name="x",
        location="y",
        trade=None,
        account_id=account_id,
        vertical_id=vertical_id,
        lead_repo=repos["lead_repo"],
        lead_signal_repo=repos["lead_signal_repo"],
        signal_definition_repo=repos["signal_definition_repo"],
        weight_repo=repos["weight_repo"],
        score_repo=repos["score_repo"],
        logger=logger,
        now_fn=lambda: fixed_now,
    )

    assert result.divergence.lead_id == repos["lead"].id
    assert result.divergence.snapshot_id == repos["snapshot"].id
    assert result.divergence.vertical_id == vertical_id


def test_bridge_result_is_frozen() -> None:
    br = BridgeResult(
        response=_fake_response(),
        snapshot=_make_snapshot(_make_lead(uuid4(), uuid4()), uuid4()),
        divergence=MagicMock(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        br.response = _fake_response()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# now_fn injection + clock consistency
# ---------------------------------------------------------------------------


async def test_now_fn_threaded_through_to_snapshot_and_compute(
    repos, account_id, vertical_id, fixed_now, patch_orchestrator_deps
) -> None:
    """Same `now` value lands on weight_version_at AND computed_at;
    compute_lead_score receives the same weight_version_at."""
    patch_orchestrator_deps(
        analyze_response=_fake_response(60),
        computed=_fake_computed("60.00"),
    )
    logger = MagicMock()

    # Spy on compute_lead_score to inspect its kwargs.
    import app.domain.scoring_persistence as sp_module

    with patch.object(
        sp_module,
        "compute_lead_score",
        wraps=sp_module.compute_lead_score,
    ) as spy:
        await analyze_and_persist(
            business_name="x",
            location="y",
            trade=None,
            account_id=account_id,
            vertical_id=vertical_id,
            lead_repo=repos["lead_repo"],
            lead_signal_repo=repos["lead_signal_repo"],
            signal_definition_repo=repos["signal_definition_repo"],
            weight_repo=repos["weight_repo"],
            score_repo=repos["score_repo"],
            logger=logger,
            now_fn=lambda: fixed_now,
        )

        compute_kwargs = spy.await_args.kwargs
        assert compute_kwargs["weight_version_at"] == fixed_now

    score_kwargs = repos["score_repo"].create.await_args.kwargs
    assert score_kwargs["computed_at"] == fixed_now
    assert score_kwargs["weight_version_at"] == fixed_now


# ---------------------------------------------------------------------------
# Bridge source constant
# ---------------------------------------------------------------------------


def test_bridge_lead_source_constant_is_versioned() -> None:
    """The lead.source string is the grep target for finding
    bridge-originated rows in the DB. Must be stable + versioned."""
    assert BRIDGE_LEAD_SOURCE == "bridge:legacy_analyzer:v1"
