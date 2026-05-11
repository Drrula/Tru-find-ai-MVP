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
    LeadSignal,
    LeadSignalDefinition,
)
from app.domain.leads.recording import record_lead_event, record_lead_signal


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
# Public surface re-export
# ============================================================================


def test_helpers_exposed_via_app_domain_leads_public_surface() -> None:
    """Per phase-b4-plan.md §3 + inspectability discipline: both
    helpers are part of the public surface of app.domain.leads."""
    import app.domain.leads as leads_pkg

    assert "record_lead_event" in leads_pkg.__all__
    assert "record_lead_signal" in leads_pkg.__all__
    assert callable(leads_pkg.record_lead_event)
    assert callable(leads_pkg.record_lead_signal)
