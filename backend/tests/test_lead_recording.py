"""B.4.5 behavior tests for the lead recording helpers.

Mock-only. Mocks the four repos so the tests focus on helper
control flow:

  1. Catalog lookup (find_active_by_event_type / find_by_name).
  2. Raise ValueError if catalog row missing.
  3. Repo create() with the resolved definition + the right
     occurred_at / observed_at + recorded_at.

Neither helper publishes a canonical envelope (the helper does ONE
thing: record-with-catalog-validation). Tests verify that no
events appear in the `recording_publisher` capture for these calls,
guarding against accidental publish_event creep.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.events import RecordingEventPublisher
from app.db.models import (
    Lead,
    LeadEvent,
    LeadEventDefinition,
    LeadScoreSnapshot,
    LeadSignal,
    LeadSignalDefinition,
)
from app.domain.leads.recording import (
    record_lead_event,
    record_lead_score,
    record_lead_signal,
)
from app.domain.leads.scoring import ComputedLeadScore


# --- Helpers


def _make_lead() -> Lead:
    return Lead(
        id=uuid4(),
        account_id=uuid4(),
        source="test",
        lifecycle_state="cold",
    )


def _make_event_definition(
    event_type: str = "lead.event.recorded",
) -> LeadEventDefinition:
    return LeadEventDefinition(
        id=uuid4(),
        event_type=event_type,
        version=1,
        status="active",
        category="engagement",
        source="domain",
        default_weight=Decimal("0.5"),
        freshness_ttl_seconds=3600,
        payload_schema={"type": "object"},
        lenient=False,
    )


def _make_signal_definition(
    name: str = "review_count",
) -> LeadSignalDefinition:
    return LeadSignalDefinition(
        name=name,
        description="Review count for the lead's business.",
        contributes_to=["lead_quality"],
        freshness_ttl_seconds=86400,
        source_kind="computed",
        default_weight=Decimal("0.3"),
        default_enabled=True,
    )


def _make_lead_event(lead: Lead, definition: LeadEventDefinition) -> LeadEvent:
    return LeadEvent(
        id=uuid4(),
        account_id=lead.account_id,
        lead_id=lead.id,
        event_type=definition.event_type,
        event_definition_id=definition.id,
        payload={},
        actor_kind="system",
        occurred_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
    )


def _make_lead_signal(
    lead: Lead, signal_name: str = "review_count"
) -> LeadSignal:
    now = datetime.now(timezone.utc)
    return LeadSignal(
        id=uuid4(),
        account_id=lead.account_id,
        lead_id=lead.id,
        signal_name=signal_name,
        value={},
        source="test",
        observed_at=now,
        recorded_at=now,
    )


# ============================================================================
# record_lead_event
# ============================================================================


async def test_record_event_raises_when_definition_missing(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    event_def_repo = AsyncMock()
    event_def_repo.find_active_by_event_type = AsyncMock(return_value=None)
    event_repo = AsyncMock()

    with pytest.raises(
        ValueError, match="No active lead_event_definition"
    ):
        await record_lead_event(
            lead=lead,
            event_type="not.in.catalog",
            payload={"x": 1},
            actor_kind="system",
            actor_user_id=None,
            lead_event_repo=event_repo,
            event_definition_repo=event_def_repo,
        )

    event_def_repo.find_active_by_event_type.assert_awaited_once_with(
        "not.in.catalog"
    )
    # Write side-effect must NOT have fired.
    event_repo.create.assert_not_called()
    # Helper does NOT publish a canonical envelope (caller's job).
    assert recording_publisher.events == []


async def test_record_event_happy_path(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    definition = _make_event_definition("lead.event.recorded")
    event_def_repo = AsyncMock()
    event_def_repo.find_active_by_event_type = AsyncMock(
        return_value=definition
    )
    fake_row = _make_lead_event(lead, definition)
    event_repo = AsyncMock()
    event_repo.create = AsyncMock(return_value=fake_row)

    fixed_now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    user_id = uuid4()

    result = await record_lead_event(
        lead=lead,
        event_type="lead.event.recorded",
        payload={"note": "manual entry"},
        actor_kind="user",
        actor_user_id=user_id,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
        now_fn=lambda: fixed_now,
    )

    assert result is fake_row

    # Catalog was checked.
    event_def_repo.find_active_by_event_type.assert_awaited_once_with(
        "lead.event.recorded"
    )

    # create() invoked with the resolved definition + correct kwargs.
    event_repo.create.assert_awaited_once()
    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["lead"] is lead
    assert create_kwargs["event_type"] == "lead.event.recorded"
    assert create_kwargs["event_definition_id"] == definition.id
    assert create_kwargs["payload"] == {"note": "manual entry"}
    assert create_kwargs["actor_kind"] == "user"
    assert create_kwargs["actor_user_id"] == user_id
    # Default occurred_at == now_fn() for real-time events.
    assert create_kwargs["occurred_at"] == fixed_now
    assert create_kwargs["recorded_at"] == fixed_now

    # Helper deliberately does NOT publish a canonical envelope --
    # caller emits publish_event separately if they want a log line.
    assert recording_publisher.events == []


async def test_record_event_accepts_explicit_occurred_at_backfill(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Backfilled events carry an occurred_at in the past; recorded_at
    stays at now_fn() (when the system became aware)."""
    lead = _make_lead()
    definition = _make_event_definition("lead.event.recorded")
    event_def_repo = AsyncMock()
    event_def_repo.find_active_by_event_type = AsyncMock(
        return_value=definition
    )
    event_repo = AsyncMock()
    event_repo.create = AsyncMock(return_value=_make_lead_event(lead, definition))

    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    past = now - timedelta(days=3)

    await record_lead_event(
        lead=lead,
        event_type="lead.event.recorded",
        payload={},
        actor_kind="system",
        actor_user_id=None,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
        now_fn=lambda: now,
        occurred_at=past,
    )

    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["occurred_at"] == past
    assert create_kwargs["recorded_at"] == now


async def test_record_event_passes_actor_user_id_none_for_system(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    definition = _make_event_definition()
    event_def_repo = AsyncMock()
    event_def_repo.find_active_by_event_type = AsyncMock(
        return_value=definition
    )
    event_repo = AsyncMock()
    event_repo.create = AsyncMock(return_value=_make_lead_event(lead, definition))

    await record_lead_event(
        lead=lead,
        event_type="lead.event.recorded",
        payload={},
        actor_kind="system",
        actor_user_id=None,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
    )

    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["actor_kind"] == "system"
    assert create_kwargs["actor_user_id"] is None


# ============================================================================
# record_lead_signal
# ============================================================================


async def test_record_signal_raises_when_definition_missing(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    signal_def_repo = AsyncMock()
    signal_def_repo.find_by_name = AsyncMock(return_value=None)
    signal_repo = AsyncMock()

    with pytest.raises(
        ValueError, match="No lead_signal_definition"
    ):
        await record_lead_signal(
            lead=lead,
            signal_name="not_in_catalog",
            value={"x": 1},
            source="test",
            lead_signal_repo=signal_repo,
            signal_definition_repo=signal_def_repo,
        )

    signal_def_repo.find_by_name.assert_awaited_once_with("not_in_catalog")
    signal_repo.create.assert_not_called()
    assert recording_publisher.events == []


async def test_record_signal_happy_path(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    definition = _make_signal_definition("review_count")
    signal_def_repo = AsyncMock()
    signal_def_repo.find_by_name = AsyncMock(return_value=definition)
    fake_row = _make_lead_signal(lead, "review_count")
    signal_repo = AsyncMock()
    signal_repo.create = AsyncMock(return_value=fake_row)

    fixed_now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)

    result = await record_lead_signal(
        lead=lead,
        signal_name="review_count",
        value={"count": 42},
        source="google_business",
        lead_signal_repo=signal_repo,
        signal_definition_repo=signal_def_repo,
        now_fn=lambda: fixed_now,
    )

    assert result is fake_row

    # Catalog was checked.
    signal_def_repo.find_by_name.assert_awaited_once_with("review_count")

    # create() invoked with correct kwargs.
    signal_repo.create.assert_awaited_once()
    create_kwargs = signal_repo.create.await_args.kwargs
    assert create_kwargs["lead"] is lead
    assert create_kwargs["signal_name"] == "review_count"
    assert create_kwargs["value"] == {"count": 42}
    assert create_kwargs["source"] == "google_business"
    # Default observed_at == now_fn().
    assert create_kwargs["observed_at"] == fixed_now
    assert create_kwargs["recorded_at"] == fixed_now
    assert create_kwargs["source_ref_id"] is None

    # No publish_event side-effect (helper is the thin write only).
    assert recording_publisher.events == []


async def test_record_signal_accepts_explicit_observed_at_backfill(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    definition = _make_signal_definition()
    signal_def_repo = AsyncMock()
    signal_def_repo.find_by_name = AsyncMock(return_value=definition)
    signal_repo = AsyncMock()
    signal_repo.create = AsyncMock(return_value=_make_lead_signal(lead))

    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    past = now - timedelta(hours=6)

    await record_lead_signal(
        lead=lead,
        signal_name="review_count",
        value={"count": 7},
        source="webhook",
        lead_signal_repo=signal_repo,
        signal_definition_repo=signal_def_repo,
        now_fn=lambda: now,
        observed_at=past,
    )

    create_kwargs = signal_repo.create.await_args.kwargs
    assert create_kwargs["observed_at"] == past
    # recorded_at is always now_fn() (when system became aware).
    assert create_kwargs["recorded_at"] == now


async def test_record_signal_accepts_source_ref_id(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    definition = _make_signal_definition()
    signal_def_repo = AsyncMock()
    signal_def_repo.find_by_name = AsyncMock(return_value=definition)
    signal_repo = AsyncMock()
    signal_repo.create = AsyncMock(return_value=_make_lead_signal(lead))

    ref_id = uuid4()
    await record_lead_signal(
        lead=lead,
        signal_name="review_count",
        value={"count": 42},
        source="webhook",
        lead_signal_repo=signal_repo,
        signal_definition_repo=signal_def_repo,
        source_ref_id=ref_id,
    )

    create_kwargs = signal_repo.create.await_args.kwargs
    assert create_kwargs["source_ref_id"] == ref_id


async def test_record_signal_returns_the_created_row(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    definition = _make_signal_definition()
    signal_def_repo = AsyncMock()
    signal_def_repo.find_by_name = AsyncMock(return_value=definition)
    fake_row = _make_lead_signal(lead)
    signal_repo = AsyncMock()
    signal_repo.create = AsyncMock(return_value=fake_row)

    result = await record_lead_signal(
        lead=lead,
        signal_name="review_count",
        value={"count": 1},
        source="test",
        lead_signal_repo=signal_repo,
        signal_definition_repo=signal_def_repo,
    )

    assert result is fake_row


# ============================================================================
# record_lead_score (B.5.3)
# ============================================================================


def _make_lead_score_snapshot(
    lead: Lead, vertical_id: UUID, score: Decimal = Decimal("60.00")
) -> LeadScoreSnapshot:
    now = datetime.now(timezone.utc)
    return LeadScoreSnapshot(
        id=uuid4(),
        account_id=lead.account_id,
        lead_id=lead.id,
        vertical_id=vertical_id,
        score=score,
        score_breakdown={"score": str(score)},
        inputs={"signals": {}},
        weight_version_at=now,
        computed_at=now,
    )


async def test_record_score_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Wires compute → repo.create. Verifies the snapshot is staged
    with score, breakdown, inputs from compute and computed_at /
    weight_version_at from now_fn()."""
    lead = _make_lead()
    vertical_id = uuid4()
    fixed_now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)

    fake_computed = ComputedLeadScore(
        score=Decimal("72.50"),
        breakdown={
            "vertical_id": str(vertical_id),
            "weight_version_at": fixed_now.isoformat(),
            "score": "72.50",
        },
        inputs={"signals": {"review_count": {"value": {"score": 0.8}}}},
    )

    compute_mock = AsyncMock(return_value=fake_computed)
    monkeypatch.setattr(
        "app.domain.leads.recording.compute_lead_score", compute_mock
    )

    lead_signal_repo = AsyncMock()
    weight_repo = AsyncMock()
    score_repo = AsyncMock()
    fake_snapshot = _make_lead_score_snapshot(
        lead, vertical_id, Decimal("72.50")
    )
    score_repo.create = AsyncMock(return_value=fake_snapshot)

    result = await record_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
        score_repo=score_repo,
        now_fn=lambda: fixed_now,
    )

    assert result is fake_snapshot

    # compute_lead_score was called with the resolved weight_version_at
    # (== now_fn() when not supplied).
    compute_mock.assert_awaited_once()
    compute_kwargs = compute_mock.await_args.kwargs
    assert compute_kwargs["lead"] is lead
    assert compute_kwargs["vertical_id"] == vertical_id
    assert compute_kwargs["lead_signal_repo"] is lead_signal_repo
    assert compute_kwargs["weight_repo"] is weight_repo
    assert compute_kwargs["weight_version_at"] == fixed_now

    # score_repo.create received the compute result + the SAME
    # weight_version_at (must agree with the breakdown).
    score_repo.create.assert_awaited_once()
    create_kwargs = score_repo.create.await_args.kwargs
    assert create_kwargs["lead"] is lead
    assert create_kwargs["vertical_id"] == vertical_id
    assert create_kwargs["score"] == Decimal("72.50")
    assert create_kwargs["score_breakdown"] is fake_computed.breakdown
    assert create_kwargs["inputs"] is fake_computed.inputs
    assert create_kwargs["weight_version_at"] == fixed_now
    assert create_kwargs["computed_at"] == fixed_now

    # No publish_event side-effect (helper is the thin compute+write only).
    assert recording_publisher.events == []


async def test_record_score_with_explicit_weight_version_at_replays(
    monkeypatch: pytest.MonkeyPatch,
    recording_publisher: RecordingEventPublisher,
) -> None:
    """ADR-010 replay: pass a historical timestamp, and BOTH the
    compute call and the snapshot row use it. computed_at remains
    now_fn() (when the replay actually ran)."""
    lead = _make_lead()
    vertical_id = uuid4()
    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    past = now - timedelta(days=30)

    fake_computed = ComputedLeadScore(
        score=Decimal("48.00"),
        breakdown={"weight_version_at": past.isoformat(), "score": "48.00"},
        inputs={"signals": {}},
    )

    compute_mock = AsyncMock(return_value=fake_computed)
    monkeypatch.setattr(
        "app.domain.leads.recording.compute_lead_score", compute_mock
    )

    score_repo = AsyncMock()
    score_repo.create = AsyncMock(
        return_value=_make_lead_score_snapshot(lead, vertical_id)
    )

    await record_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=AsyncMock(),
        weight_repo=AsyncMock(),
        score_repo=score_repo,
        weight_version_at=past,
        now_fn=lambda: now,
    )

    # Replay: compute saw `past`, not `now`.
    assert compute_mock.await_args.kwargs["weight_version_at"] == past

    # Snapshot: weight_version_at = past (history), computed_at = now
    # (when the replay ran).
    create_kwargs = score_repo.create.await_args.kwargs
    assert create_kwargs["weight_version_at"] == past
    assert create_kwargs["computed_at"] == now


async def test_record_score_zero_score_branch_still_persists(
    monkeypatch: pytest.MonkeyPatch,
    recording_publisher: RecordingEventPublisher,
) -> None:
    """The `no_weights_configured` / `all_signals_unobserved` branches
    return score=0 from compute. The helper must still persist a
    snapshot -- the zero IS observable history, not a no-op."""
    lead = _make_lead()
    vertical_id = uuid4()
    fixed_now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)

    fake_computed = ComputedLeadScore(
        score=Decimal("0.00"),
        breakdown={
            "reason": "no_weights_configured",
            "vertical_id": str(vertical_id),
            "weight_version_at": fixed_now.isoformat(),
            "score": "0.00",
        },
        inputs={"signals": {}},
    )

    monkeypatch.setattr(
        "app.domain.leads.recording.compute_lead_score",
        AsyncMock(return_value=fake_computed),
    )

    score_repo = AsyncMock()
    score_repo.create = AsyncMock(
        return_value=_make_lead_score_snapshot(
            lead, vertical_id, Decimal("0.00")
        )
    )

    await record_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=AsyncMock(),
        weight_repo=AsyncMock(),
        score_repo=score_repo,
        now_fn=lambda: fixed_now,
    )

    score_repo.create.assert_awaited_once()
    create_kwargs = score_repo.create.await_args.kwargs
    assert create_kwargs["score"] == Decimal("0.00")
    assert create_kwargs["score_breakdown"]["reason"] == "no_weights_configured"


async def test_record_score_propagates_compute_value_error(
    monkeypatch: pytest.MonkeyPatch,
    recording_publisher: RecordingEventPublisher,
) -> None:
    """If compute raises (e.g. missing 'score' key in a signal value
    per plan §2 #4), the helper does NOT swallow the error and does
    NOT call score_repo.create. The write side-effect must not fire."""
    lead = _make_lead()
    vertical_id = uuid4()

    compute_mock = AsyncMock(
        side_effect=ValueError("lead_signal['review_count'].value missing")
    )
    monkeypatch.setattr(
        "app.domain.leads.recording.compute_lead_score", compute_mock
    )

    score_repo = AsyncMock()

    with pytest.raises(ValueError, match="missing"):
        await record_lead_score(
            lead=lead,
            vertical_id=vertical_id,
            lead_signal_repo=AsyncMock(),
            weight_repo=AsyncMock(),
            score_repo=score_repo,
        )

    score_repo.create.assert_not_called()
    assert recording_publisher.events == []


async def test_record_score_returns_the_created_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    vertical_id = uuid4()

    monkeypatch.setattr(
        "app.domain.leads.recording.compute_lead_score",
        AsyncMock(
            return_value=ComputedLeadScore(
                score=Decimal("60.00"),
                breakdown={"score": "60.00"},
                inputs={"signals": {}},
            )
        ),
    )

    fake_snapshot = _make_lead_score_snapshot(lead, vertical_id)
    score_repo = AsyncMock()
    score_repo.create = AsyncMock(return_value=fake_snapshot)

    result = await record_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=AsyncMock(),
        weight_repo=AsyncMock(),
        score_repo=score_repo,
    )

    assert result is fake_snapshot


async def test_record_score_passes_repos_through_to_compute(
    monkeypatch: pytest.MonkeyPatch,
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Helper is a thin wrapper -- the repos given to it must be the
    SAME objects handed to compute_lead_score. No proxying, no
    rewrapping."""
    lead = _make_lead()
    vertical_id = uuid4()

    compute_mock = AsyncMock(
        return_value=ComputedLeadScore(
            score=Decimal("50.00"),
            breakdown={"score": "50.00"},
            inputs={"signals": {}},
        )
    )
    monkeypatch.setattr(
        "app.domain.leads.recording.compute_lead_score", compute_mock
    )

    lead_signal_repo = AsyncMock()
    weight_repo = AsyncMock()
    score_repo = AsyncMock()
    score_repo.create = AsyncMock(
        return_value=_make_lead_score_snapshot(lead, vertical_id)
    )

    await record_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
        score_repo=score_repo,
    )

    kwargs = compute_mock.await_args.kwargs
    assert kwargs["lead_signal_repo"] is lead_signal_repo
    assert kwargs["weight_repo"] is weight_repo


# ============================================================================
# Public surface re-export
# ============================================================================


def test_helpers_exposed_via_app_domain_leads_public_surface() -> None:
    """Per phase-b4-plan.md §3 + phase-b5-plan.md §4 + inspectability
    discipline: all three recording helpers are part of the public
    surface of app.domain.leads."""
    import app.domain.leads as leads_pkg

    assert "record_lead_event" in leads_pkg.__all__
    assert "record_lead_signal" in leads_pkg.__all__
    assert "record_lead_score" in leads_pkg.__all__
    assert callable(leads_pkg.record_lead_event)
    assert callable(leads_pkg.record_lead_signal)
    assert callable(leads_pkg.record_lead_score)
