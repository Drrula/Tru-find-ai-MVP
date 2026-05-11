"""Lead recording helpers — thin catalog-validation + write wrappers.

Per docs/phase-b4-plan.md §5 + §9 + docs/phase-b5-plan.md §4 +
ADR-036 + ADR-040 + ADR-010.

Each helper does TWO things and ONLY those two things:

  1. Validate inputs (catalog row exists, or in the case of
     `record_lead_score`, delegate the validation to
     `compute_lead_score`).
  2. Stage a row via the appropriate repository, stamping
     `recorded_at = now_fn()` (or `computed_at = now_fn()` for the
     score variant).

NO publish_event call. NO orchestration. NO event-bus dispatch. NO
hidden parallel writes. Callers who want a structured-log canonical
envelope emit it themselves:

    event = await record_lead_event(...)
    publish_event("lead.event.recorded", payload=..., ...)

Two explicit lines, both readable from the call site -- preserves
the trace test from feedback_inspectability_over_abstraction
(lead -> signals -> lifecycle -> events -> scores readable from
tables + repo methods alone).

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

from app.db.models import Lead, LeadEvent, LeadScoreSnapshot, LeadSignal
from app.db.repositories.lead_event_definition_repo import (
    LeadEventDefinitionRepository,
)
from app.db.repositories.lead_event_repo import LeadEventRepository
from app.db.repositories.lead_score_snapshot_repo import (
    LeadScoreSnapshotRepository,
)
from app.db.repositories.lead_signal_definition_repo import (
    LeadSignalDefinitionRepository,
)
from app.db.repositories.lead_signal_repo import LeadSignalRepository
from app.db.repositories.vertical_lead_signal_weight_repo import (
    VerticalLeadSignalWeightRepository,
)
from app.domain.leads.scoring import compute_lead_score

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


async def record_lead_score(
    *,
    lead: Lead,
    vertical_id: UUID,
    lead_signal_repo: LeadSignalRepository,
    weight_repo: VerticalLeadSignalWeightRepository,
    score_repo: LeadScoreSnapshotRepository,
    weight_version_at: datetime | None = None,
    now_fn: Callable[[], datetime] = _default_now,
) -> LeadScoreSnapshot:
    """Compute + persist a lead's score as a `lead_score_snapshot` row.

    Thin wrapper: calls `compute_lead_score` (B.5.2) and stages the
    result via `LeadScoreSnapshotRepository.create`. Mirrors the
    record_lead_event / record_lead_signal shape from B.4.5 -- ONE
    DB write, NO publish_event. Callers who want a canonical
    envelope emit it themselves.

    `weight_version_at` defaults to `now_fn()`, matching the
    "score the lead against current weights" path. Pass explicitly
    to reproduce a past score against historical weight rows
    (ADR-010 replay semantics) -- the resolved value lands BOTH on
    the compute call AND on the snapshot row so the stored
    `weight_version_at` and the breakdown's `weight_version_at` agree.

    `computed_at` on the snapshot is `now_fn()` at entry -- the
    moment the compute ran.

    Returns the newly-staged LeadScoreSnapshot (UUIDv7 id minted by
    the repo; no flush yet -- caller controls the transaction).

    Args:
        lead: The lead this score is about. Used for FK +
            denormalized account_id (per LeadScoreSnapshotRepository).
        vertical_id: The vertical whose weights govern the score.
            The same lead can score differently across verticals.
        lead_signal_repo: customer-owned repo for reading current
            observations (constructed with lead.account_id).
        weight_repo: platform-owned repo for reading active weights
            (constructed with account_id=None).
        score_repo: customer-owned repo for staging the snapshot.
        weight_version_at: Optional historical timestamp for replay.
            Defaults to now_fn().
        now_fn: Injectable clock for deterministic tests.

    Raises:
        ValueError: propagated from `compute_lead_score` if any
            observation's `value` dict is missing its required
            `'score'` key (per docs/phase-b5-plan.md §2 #4).
    """
    now = now_fn()
    resolved_weight_at = (
        weight_version_at if weight_version_at is not None else now
    )

    computed = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
        weight_version_at=resolved_weight_at,
        now_fn=now_fn,
    )

    return await score_repo.create(
        lead=lead,
        vertical_id=vertical_id,
        score=computed.score,
        score_breakdown=computed.breakdown,
        inputs=computed.inputs,
        weight_version_at=resolved_weight_at,
        computed_at=now,
    )
