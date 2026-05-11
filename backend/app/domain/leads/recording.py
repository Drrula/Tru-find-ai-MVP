"""Lead recording helpers — thin catalog-validation + write wrappers.

Per docs/phase-b4-plan.md §5 + §9 + ADR-036 + ADR-040.

Each helper does TWO things and ONLY those two things:

  1. Validate that the supplied `event_type` or `signal_name` exists
     in the corresponding DB catalog (lead_event_definition or
     lead_signal_definition). Raise ValueError if missing.
  2. Stage a row via the appropriate repository, stamping
     `recorded_at = now_fn()`.

NO publish_event call. NO orchestration. NO event-bus dispatch. NO
hidden parallel writes. Callers who want a structured-log canonical
envelope emit it themselves:

    event = await record_lead_event(...)
    publish_event("lead.event.recorded", payload=..., ...)

Two explicit lines, both readable from the call site -- preserves
the trace test from feedback_inspectability_over_abstraction
(lead -> signals -> lifecycle -> events readable from tables +
repo methods alone).

(Note: B.4.4's `lifecycle.transition` does both -- the DB write AND
the canonical envelope publish -- because lifecycle transitions are
infrequent and important enough to always log. The recording
helpers here are deliberately thinner; lifecycle.transition may be
refactored to use record_lead_event in a future small commit,
flagged at B.4.4.)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import UUID

from app.db.models import Lead, LeadEvent, LeadSignal
from app.db.repositories.lead_event_definition_repo import (
    LeadEventDefinitionRepository,
)
from app.db.repositories.lead_event_repo import LeadEventRepository
from app.db.repositories.lead_signal_definition_repo import (
    LeadSignalDefinitionRepository,
)
from app.db.repositories.lead_signal_repo import LeadSignalRepository

ActorKind = Literal["user", "system", "webhook", "job", "ai"]


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


async def record_lead_event(
    *,
    lead: Lead,
    event_type: str,
    payload: dict[str, Any],
    actor_kind: ActorKind,
    actor_user_id: UUID | None,
    lead_event_repo: LeadEventRepository,
    event_definition_repo: LeadEventDefinitionRepository,
    now_fn: Callable[[], datetime] = _default_now,
    occurred_at: datetime | None = None,
) -> LeadEvent:
    """Stage a lead_event timeline row, after validating the event_type
    against the DB catalog.

    Returns the newly-staged LeadEvent (UUIDv7 id minted by the repo;
    no flush yet — caller controls the transaction).

    Args:
        lead: The lead this event is about. Used for FK +
            denormalized account_id.
        event_type: Canonical event-type string. Must have an active
            row in `lead_event_definition` (one is resolved on every
            call).
        payload: JSONB body for the event. Caller supplies the shape;
            the schema is documented in the catalog row's
            `payload_schema`.
        actor_kind: Closed enum per ADR-044 ('user', 'system',
            'webhook', 'job', 'ai').
        actor_user_id: User-initiated events carry this; system /
            webhook / job / ai pass None.
        lead_event_repo: customer-owned repo, constructed with the
            lead's account_id.
        event_definition_repo: platform-owned repo, constructed with
            account_id=None.
        now_fn: Injectable clock for deterministic tests; production
            omits and gets datetime.now(timezone.utc).
        occurred_at: When the event actually happened. Defaults to
            now_fn() for real-time events; pass explicitly for
            backfill imports.

    Raises:
        ValueError: if no active lead_event_definition exists for
            `event_type`. Operator must seed the catalog row before
            calling.
    """
    definition = await event_definition_repo.find_active_by_event_type(
        event_type
    )
    if definition is None:
        raise ValueError(
            f"No active lead_event_definition for {event_type!r} -- "
            "operator must seed the catalog row before recording "
            "events of this type."
        )

    now = now_fn()
    actual_occurred_at = occurred_at if occurred_at is not None else now

    return await lead_event_repo.create(
        lead=lead,
        event_type=event_type,
        event_definition_id=definition.id,
        payload=payload,
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        occurred_at=actual_occurred_at,
        recorded_at=now,
    )


async def record_lead_signal(
    *,
    lead: Lead,
    signal_name: str,
    value: dict[str, Any],
    source: str,
    lead_signal_repo: LeadSignalRepository,
    signal_definition_repo: LeadSignalDefinitionRepository,
    now_fn: Callable[[], datetime] = _default_now,
    observed_at: datetime | None = None,
    source_ref_id: UUID | None = None,
) -> LeadSignal:
    """Stage a lead_signal observation row, after validating the
    signal_name against the DB catalog.

    Returns the newly-staged LeadSignal (UUIDv7 id minted by the
    repo; no flush yet — caller controls the transaction).

    Args:
        lead: The lead this observation is about. Used for FK +
            denormalized account_id.
        signal_name: Catalog signal name. Must have a row in
            `lead_signal_definition` (PK is the name itself).
        value: JSONB body of the observation. Schema is signal-
            specific; the catalog row documents the expected shape.
        source: Free-text source identifier (e.g. "google_business",
            "webhook:typeform", "import_batch_007").
        lead_signal_repo: customer-owned repo, constructed with the
            lead's account_id.
        signal_definition_repo: platform-owned repo, constructed
            with account_id=None.
        now_fn: Injectable clock for deterministic tests.
        observed_at: When the observation actually happened. Defaults
            to now_fn() for real-time signals; pass explicitly for
            backfill imports.
        source_ref_id: Optional opaque reference to the upstream row
            (e.g. webhook_event.id) that produced this observation.

    Raises:
        ValueError: if no lead_signal_definition exists for
            `signal_name`. Operator must seed the catalog row before
            calling.
    """
    definition = await signal_definition_repo.find_by_name(signal_name)
    if definition is None:
        raise ValueError(
            f"No lead_signal_definition for {signal_name!r} -- "
            "operator must seed the catalog row before recording "
            "observations of this signal."
        )

    now = now_fn()
    actual_observed_at = observed_at if observed_at is not None else now

    return await lead_signal_repo.create(
        lead=lead,
        signal_name=signal_name,
        value=value,
        source=source,
        observed_at=actual_observed_at,
        recorded_at=now,
        source_ref_id=source_ref_id,
    )
