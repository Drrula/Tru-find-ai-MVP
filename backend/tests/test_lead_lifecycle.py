"""B.4.4 behavior tests for `app.domain.leads.lifecycle.transition`.

Mock-only. Uses the `recording_publisher` fixture from conftest.py
to capture canonical envelope emits. Mocks the three repos so the
test focuses on transition() control flow + correct repo-method
invocation.

Covers:
- LIFECYCLE_STATES contains exactly the 8 spec states.
- Invalid state raises ValueError.
- Missing lead (repo returns False) raises ValueError.
- Missing event-definition catalog row raises ValueError.
- Happy path: update_lifecycle_state called + event written + canonical
  envelope published + lead.lifecycle_state updated in-Python.
- Same-state transition is allowed (no hidden short-circuit; event
  is still recorded).
- now_fn is used consistently for occurred_at + recorded_at.
- Payload contains from_state + to_state.
- Canonical envelope carries account_id + target_kind=lead + target_id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.events import RecordingEventPublisher
from app.db.models import Lead, LeadEvent, LeadEventDefinition
from app.domain.leads.lifecycle import (
    LIFECYCLE_STATES,
    LIFECYCLE_TRANSITION_EVENT_TYPE,
    transition,
)


# --- Helpers


def _make_lead(*, lifecycle_state: str = "cold") -> Lead:
    return Lead(
        id=uuid4(),
        account_id=uuid4(),
        source="test",
        lifecycle_state=lifecycle_state,
    )


def _make_definition() -> LeadEventDefinition:
    return LeadEventDefinition(
        id=uuid4(),
        event_type=LIFECYCLE_TRANSITION_EVENT_TYPE,
        version=1,
        status="active",
        category="lifecycle",
        source="domain",
        default_weight=0.5,
        freshness_ttl_seconds=3600,
        payload_schema={"type": "object"},
        lenient=False,
    )


def _make_repos(
    *,
    update_succeeds: bool = True,
    definition: LeadEventDefinition | None = None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Build the three repos + a returned LeadEvent mock for create()."""
    lead_repo = AsyncMock()
    lead_repo.update_lifecycle_state = AsyncMock(return_value=update_succeeds)

    event_def_repo = AsyncMock()
    event_def_repo.find_active_by_event_type = AsyncMock(
        return_value=definition or _make_definition()
    )

    event_repo = AsyncMock()
    fake_event = LeadEvent(
        id=uuid4(),
        account_id=uuid4(),
        lead_id=uuid4(),
        event_type=LIFECYCLE_TRANSITION_EVENT_TYPE,
        event_definition_id=uuid4(),
        payload={},
        actor_kind="system",
        occurred_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
    )
    event_repo.create = AsyncMock(return_value=fake_event)
    return lead_repo, event_def_repo, event_repo, fake_event


# --- LIFECYCLE_STATES enum


def test_lifecycle_states_match_db_check_constraint() -> None:
    """The frozenset must mirror the DB CHECK enum exactly so any
    drift surfaces here, not as a flush-time DB error."""
    assert LIFECYCLE_STATES == frozenset(
        {
            "cold",
            "warm",
            "engaged",
            "qualified",
            "opportunity",
            "customer",
            "dormant",
            "unsubscribed",
        }
    )


def test_lifecycle_states_is_frozenset() -> None:
    """Frozen so callers can't mutate the canonical enum at runtime."""
    assert isinstance(LIFECYCLE_STATES, frozenset)


def test_lifecycle_transition_event_type_constant() -> None:
    """Matches the registered EventTypeDefinition in events.py."""
    assert LIFECYCLE_TRANSITION_EVENT_TYPE == "lead.lifecycle.transition"


# --- Validation: invalid state


async def test_transition_raises_on_invalid_state(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead()
    lead_repo, event_def_repo, event_repo, _ = _make_repos()

    with pytest.raises(ValueError, match="Invalid lifecycle state"):
        await transition(
            lead,
            new_state="not_a_real_state",
            actor_kind="user",
            actor_user_id=None,
            lead_repo=lead_repo,
            lead_event_repo=event_repo,
            event_definition_repo=event_def_repo,
        )

    # Nothing should have been called -- validation is the first step.
    lead_repo.update_lifecycle_state.assert_not_called()
    event_def_repo.find_active_by_event_type.assert_not_called()
    event_repo.create.assert_not_called()
    # No canonical envelope emitted.
    assert recording_publisher.events == []


# --- Validation: lead not updatable


async def test_transition_raises_when_lead_update_returns_false(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Soft-deleted lead / cross-tenant lead / missing lead all surface
    as update_lifecycle_state returning False -- transition raises
    instead of silently no-op-ing."""
    lead = _make_lead()
    lead_repo, event_def_repo, event_repo, _ = _make_repos(
        update_succeeds=False
    )

    with pytest.raises(ValueError, match="Could not update lifecycle_state"):
        await transition(
            lead,
            new_state="warm",
            actor_kind="user",
            actor_user_id=None,
            lead_repo=lead_repo,
            lead_event_repo=event_repo,
            event_definition_repo=event_def_repo,
        )

    # Update was attempted; event side-effects must NOT have fired.
    lead_repo.update_lifecycle_state.assert_awaited_once()
    event_def_repo.find_active_by_event_type.assert_not_called()
    event_repo.create.assert_not_called()
    assert recording_publisher.events == []


# --- Validation: catalog row missing


async def test_transition_raises_when_event_definition_missing(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Catalog row required for the FK -- if operator hasn't seeded
    the lead.lifecycle.transition definition, transition raises."""
    lead = _make_lead()
    lead_repo, event_def_repo, event_repo, _ = _make_repos(definition=None)
    event_def_repo.find_active_by_event_type = AsyncMock(return_value=None)

    with pytest.raises(
        ValueError, match="No active lead_event_definition"
    ):
        await transition(
            lead,
            new_state="warm",
            actor_kind="user",
            actor_user_id=None,
            lead_repo=lead_repo,
            lead_event_repo=event_repo,
            event_definition_repo=event_def_repo,
        )

    # update succeeded; event definition lookup failed -- so the
    # lead row IS updated but the event row is NOT. Caller is
    # expected to detect this and either backfill or roll back the
    # session.
    lead_repo.update_lifecycle_state.assert_awaited_once()
    event_def_repo.find_active_by_event_type.assert_awaited_once_with(
        LIFECYCLE_TRANSITION_EVENT_TYPE
    )
    event_repo.create.assert_not_called()


# --- Happy path


async def test_transition_happy_path_writes_event_and_publishes_envelope(
    recording_publisher: RecordingEventPublisher,
) -> None:
    lead = _make_lead(lifecycle_state="cold")
    user_id = uuid4()
    lead_repo, event_def_repo, event_repo, _ = _make_repos()
    definition = await event_def_repo.find_active_by_event_type()  # AsyncMock returns same

    result = await transition(
        lead,
        new_state="warm",
        actor_kind="user",
        actor_user_id=user_id,
        lead_repo=lead_repo,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
    )

    # Returns the supplied lead.
    assert result is lead

    # 1. lead row updated with new_state.
    lead_repo.update_lifecycle_state.assert_awaited_once_with(lead.id, "warm")

    # 2. event definition resolved with the canonical event_type.
    event_def_repo.find_active_by_event_type.assert_awaited_with(
        LIFECYCLE_TRANSITION_EVENT_TYPE
    )

    # 3. lead_event row written with from_state + to_state in payload.
    event_repo.create.assert_awaited_once()
    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["lead"] is lead
    assert create_kwargs["event_type"] == LIFECYCLE_TRANSITION_EVENT_TYPE
    assert create_kwargs["event_definition_id"] == definition.id
    assert create_kwargs["payload"] == {
        "from_state": "cold",
        "to_state": "warm",
    }
    assert create_kwargs["actor_kind"] == "user"
    assert create_kwargs["actor_user_id"] == user_id

    # 4. canonical envelope published.
    transition_events = [
        e
        for e in recording_publisher.events
        if e.event_type == LIFECYCLE_TRANSITION_EVENT_TYPE
    ]
    assert len(transition_events) == 1
    env = transition_events[0]
    assert env.payload == {"from_state": "cold", "to_state": "warm"}
    assert env.actor_kind == "user"
    assert env.actor_user_id == user_id
    assert env.account_id == lead.account_id
    assert env.target_kind == "lead"
    assert env.target_id == lead.id

    # 5. in-Python lead.lifecycle_state mirrors the new state.
    assert lead.lifecycle_state == "warm"


async def test_transition_same_state_is_allowed_and_records_event(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Same-state transition isn't silently no-op'd -- explicit
    inspectability over hidden short-circuit. Callers can guard if
    they want."""
    lead = _make_lead(lifecycle_state="cold")
    lead_repo, event_def_repo, event_repo, _ = _make_repos()

    await transition(
        lead,
        new_state="cold",
        actor_kind="system",
        actor_user_id=None,
        lead_repo=lead_repo,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
    )

    lead_repo.update_lifecycle_state.assert_awaited_once_with(lead.id, "cold")
    event_repo.create.assert_awaited_once()
    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["payload"] == {
        "from_state": "cold",
        "to_state": "cold",
    }
    assert lead.lifecycle_state == "cold"


# --- now_fn determinism


async def test_transition_uses_now_fn_for_both_timestamps(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """occurred_at == recorded_at == now_fn() for real-time transitions."""
    lead = _make_lead(lifecycle_state="warm")
    fixed_now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    lead_repo, event_def_repo, event_repo, _ = _make_repos()

    await transition(
        lead,
        new_state="engaged",
        actor_kind="system",
        actor_user_id=None,
        lead_repo=lead_repo,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
        now_fn=lambda: fixed_now,
    )

    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["occurred_at"] == fixed_now
    assert create_kwargs["recorded_at"] == fixed_now

    # Canonical envelope's occurred_at also matches.
    env = [
        e
        for e in recording_publisher.events
        if e.event_type == LIFECYCLE_TRANSITION_EVENT_TYPE
    ][0]
    assert env.occurred_at == fixed_now


# --- Actor kinds


async def test_transition_accepts_system_actor(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """System-initiated transitions carry actor_user_id=None."""
    lead = _make_lead()
    lead_repo, event_def_repo, event_repo, _ = _make_repos()

    await transition(
        lead,
        new_state="engaged",
        actor_kind="system",
        actor_user_id=None,
        lead_repo=lead_repo,
        lead_event_repo=event_repo,
        event_definition_repo=event_def_repo,
    )

    create_kwargs = event_repo.create.await_args.kwargs
    assert create_kwargs["actor_kind"] == "system"
    assert create_kwargs["actor_user_id"] is None

    env = [
        e
        for e in recording_publisher.events
        if e.event_type == LIFECYCLE_TRANSITION_EVENT_TYPE
    ][0]
    assert env.actor_kind == "system"
    assert env.actor_user_id is None
