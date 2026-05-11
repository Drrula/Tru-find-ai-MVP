"""LeadEventRepository — append-only event timeline writes + queries.

Per ADR-031 + ADR-035 + ADR-040 + ADR-044 + ADR-047
(customer-owned: tenancy filter active, no soft-delete column —
the timeline is immutable).

APPEND-ONLY discipline: this repo exposes `create` + named query
methods, but NO `update_*` and NO `revoke` / `mark_*` methods.
Inherited `BaseRepository.soft_delete` naturally refuses (no
deleted_at column on LeadEvent).

Per feedback_inspectability_over_abstraction: every read path has
a named method. The two indexes on lead_event are designed for
exactly two access patterns:
- `find_by_lead_id(...)` — timeline for one lead (uses
  `ix_lead_event_lead_occurred`).
- `find_by_event_type(...)` — events of one type in this account
  (uses `ix_lead_event_account_type_occurred`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select

from app.core.ids import new_id
from app.db.models import Lead, LeadEvent
from app.db.repositories.base import BaseRepository

ActorKind = Literal["user", "system", "webhook", "job", "ai"]


class LeadEventRepository(BaseRepository[LeadEvent]):
    model_class = LeadEvent

    async def create(
        self,
        *,
        lead: Lead,
        event_type: str,
        event_definition_id: UUID,
        payload: dict[str, Any],
        actor_kind: ActorKind,
        occurred_at: datetime,
        recorded_at: datetime,
        actor_user_id: UUID | None = None,
    ) -> LeadEvent:
        """Stage a new lead_event row.

        Denormalizes `account_id` from `lead.account_id` so the
        timeline query (`ix_lead_event_account_type_occurred`) doesn't
        need to join lead. Mints UUIDv7 explicitly so callers can read
        `.id` immediately.

        `actor_kind` is validated by the DB CHECK constraint at flush.
        `event_definition_id` is the FK to lead_event_definition —
        callers (typically the B.4.5 recording helper) resolve it via
        `LeadEventDefinitionRepository.find_active_by_event_type`
        before calling this method.
        """
        row = LeadEvent(
            id=new_id(),
            account_id=lead.account_id,
            lead_id=lead.id,
            event_type=event_type,
            event_definition_id=event_definition_id,
            payload=payload,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
        )
        self.add(row)
        return row

    async def find_by_lead_id(self, lead_id: UUID) -> list[LeadEvent]:
        """Return the full timeline for `lead_id`, newest first.

        Account-scoped via BaseRepository's tenancy filter. Backed by
        `ix_lead_event_lead_occurred`.
        """
        stmt = (
            self._base_select()
            .where(LeadEvent.lead_id == lead_id)
            .order_by(LeadEvent.occurred_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_event_type(self, event_type: str) -> list[LeadEvent]:
        """Return all events of `event_type` in this account, newest
        first.

        Operational query for "show me all `lead.signal.observed`
        events". Account-scoped. Backed by
        `ix_lead_event_account_type_occurred`.
        """
        stmt = (
            self._base_select()
            .where(LeadEvent.event_type == event_type)
            .order_by(LeadEvent.occurred_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
