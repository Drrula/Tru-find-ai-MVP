"""Lead lifecycle state machine — explicit, deterministic transitions.

Per ARCHITECTURE-LOCK §2.5.1 + ADR-037 (lead lifecycle states +
event-driven evolution) + phase-b4-plan.md §5 + §2 #3 + #4.

The 8 lifecycle states match the DB CHECK constraint on
`lead.lifecycle_state` exactly. The Python-side `LIFECYCLE_STATES`
frozenset mirrors that closed enum so callers can validate before
hitting the DB.

B.4 ships transitions OPEN (per plan §2 #4): any target state in
`LIFECYCLE_STATES` is allowed from any starting state. A from→to
matrix lands when business workflows demand it — the seam is here.

`transition()` is the ONLY public function in this module and the
ONLY way lead.lifecycle_state should be mutated. It does three
explicit things, in order:

  1. Validate `new_state` is in LIFECYCLE_STATES.
  2. Update lead.lifecycle_state via LeadRepository.update_lifecycle_state.
  3. Record a `lead.lifecycle.transition` event on the timeline:
     - resolve event_definition_id via
       LeadEventDefinitionRepository.find_active_by_event_type
     - write the lead_event row directly via LeadEventRepository.create
     - publish the canonical envelope via app.core.events.publish_event
       so the LoggingEventPublisher emits a structured log line.

The DB row + the canonical envelope are two parallel writes (per
phase-b4-plan.md §6 — DatabaseEventPublisher / MultiPublisher
deferred to Phase C+ when async workers land). Per the
inspectability discipline, the parallel writes are explicit here
rather than hidden behind a generic publisher dispatch.

`now_fn` is injectable for deterministic testing; production callers
omit it and get `datetime.now(timezone.utc)`.

No orchestration, no event bus, no hidden short-circuits. A
same-state "transition" is allowed (write succeeds; event is
recorded) — callers can guard if they want; the function does NOT
silently no-op.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal
from uuid import UUID

from app.core.events import publish_event
from app.db.models import Lead
from app.db.repositories.lead_event_definition_repo import (
    LeadEventDefinitionRepository,
)
from app.db.repositories.lead_event_repo import LeadEventRepository
from app.db.repositories.lead_repo import LeadRepository

#: Closed enum of lifecycle states. Mirrors the lead_lifecycle_state_check
#: CHECK constraint at the DB exactly. Adding a new state requires a
#: matching migration + ADR-037 supersede.
LIFECYCLE_STATES: frozenset[str] = frozenset(
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


#: The canonical event_type string used when transition() records the
#: timeline event. Matches the registered EventTypeDefinition in
#: app.domain.leads.events (LEAD_LIFECYCLE_TRANSITION).
LIFECYCLE_TRANSITION_EVENT_TYPE = "lead.lifecycle.transition"


ActorKind = Literal["user", "system", "webhook", "job", "ai"]


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


async def transition(
    lead: Lead,
    *,
    new_state: str,
    actor_kind: ActorKind,
    actor_user_id: UUID | None,
    lead_repo: LeadRepository,
    lead_event_repo: LeadEventRepository,
    event_definition_repo: LeadEventDefinitionRepository,
    now_fn: Callable[[], datetime] = _default_now,
) -> Lead:
    """Apply a lifecycle transition and record the timeline event.

    Returns the supplied lead with `.lifecycle_state` updated to
    `new_state`. The DB row is updated; the in-Python attribute is
    set on the supplied instance so the caller's reference stays
    in sync.

    Raises:
        ValueError: if `new_state` is not in LIFECYCLE_STATES;
            or if the lead can't be updated (soft-deleted or
            cross-tenant — the underlying repo returned False);
            or if the catalog has no active definition for
            `lead.lifecycle.transition` (operator must seed the
            row before transitions can be recorded).
    """
    if new_state not in LIFECYCLE_STATES:
        raise ValueError(
            f"Invalid lifecycle state {new_state!r}; allowed: "
            f"{sorted(LIFECYCLE_STATES)}"
        )

    from_state = lead.lifecycle_state
    now = now_fn()

    # 1. Update the lead row via the repo. The repo's UPDATE includes
    # tenancy + soft-delete WHERE clauses; a False return means the
    # lead doesn't exist, is soft-deleted, or belongs to a different
    # tenant. Raise rather than silently no-op (inspectability).
    updated = await lead_repo.update_lifecycle_state(lead.id, new_state)
    if not updated:
        raise ValueError(
            f"Could not update lifecycle_state on lead {lead.id} -- "
            "lead is missing, soft-deleted, or belongs to a different tenant."
        )

    # 2. Resolve the event definition from the catalog. The FK on
    # lead_event requires this row to exist before any lead_event
    # row referencing this event_type can be written.
    definition = await event_definition_repo.find_active_by_event_type(
        LIFECYCLE_TRANSITION_EVENT_TYPE
    )
    if definition is None:
        raise ValueError(
            "No active lead_event_definition for "
            f"{LIFECYCLE_TRANSITION_EVENT_TYPE!r} -- operator must seed "
            "the catalog row before lifecycle transitions can be recorded."
        )

    # 3. Write the lead_event timeline row (direct repo write per
    # phase-b4-plan.md §6 -- publisher-based projection deferred to
    # Phase C+).
    await lead_event_repo.create(
        lead=lead,
        event_type=LIFECYCLE_TRANSITION_EVENT_TYPE,
        event_definition_id=definition.id,
        payload={"from_state": from_state, "to_state": new_state},
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        occurred_at=now,
        recorded_at=now,
    )

    # 4. Publish the canonical envelope -> LoggingEventPublisher
    # emits the structured log line. Per ADR-044 this is in addition
    # to the DB row; the two writes are parallel until MultiPublisher
    # lands in Phase C+.
    publish_event(
        LIFECYCLE_TRANSITION_EVENT_TYPE,
        payload={"from_state": from_state, "to_state": new_state},
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        account_id=lead.account_id,
        target_kind="lead",
        target_id=lead.id,
        occurred_at=now,
    )

    # 5. Mirror the new state on the supplied Lead instance so the
    # caller's reference stays in sync. Session is autoflush=False
    # (app.db.session) so this in-Python mutation does NOT trigger
    # a duplicate UPDATE.
    lead.lifecycle_state = new_state

    return lead
