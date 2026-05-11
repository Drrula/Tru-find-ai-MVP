"""LeadEventDefinitionRepository — catalog of lead event types.

Per ADR-031 + ADR-040 + ADR-047 (platform-owned: no `account_id` →
BaseRepository tenancy filter is naturally inert). No `deleted_at`
either; definitions retire via `status='retired'`.

Per feedback_inspectability_over_abstraction: explicit named
methods. `find_active_by_event_type` is the dominant lookup that
the B.4.5 recording helpers will use to resolve the FK before
writing lead_event rows.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select

from app.core.ids import new_id
from app.db.models import LeadEventDefinition
from app.db.repositories.base import BaseRepository

DefinitionStatus = Literal["draft", "active", "retired"]


class LeadEventDefinitionRepository(BaseRepository[LeadEventDefinition]):
    model_class = LeadEventDefinition

    async def create(
        self,
        *,
        event_type: str,
        version: int,
        status: DefinitionStatus,
        category: str,
        source: str,
        default_weight: Decimal | float,
        freshness_ttl_seconds: int,
        payload_schema: dict[str, Any],
        description: str | None = None,
        lenient: bool = False,
    ) -> LeadEventDefinition:
        """Stage a new catalog entry.

        Mints UUIDv7 explicitly so callers can read `.id` immediately
        (lead_event writes need the definition's id to satisfy the
        FK).

        `default_weight` is normalized to Decimal — the column is
        `numeric(4,3)` so a float input is converted via str() to
        avoid float-precision noise.
        """
        row = LeadEventDefinition(
            id=new_id(),
            event_type=event_type,
            version=version,
            status=status,
            category=category,
            source=source,
            default_weight=Decimal(str(default_weight)),
            freshness_ttl_seconds=freshness_ttl_seconds,
            payload_schema=payload_schema,
            description=description,
            lenient=lenient,
        )
        self.add(row)
        return row

    async def find_active_by_event_type(
        self, event_type: str
    ) -> LeadEventDefinition | None:
        """Return the active definition for `event_type`, or None.

        Used by the B.4.5 recording helpers to resolve
        `event_definition_id` before writing a lead_event row.
        Issues a single SELECT against `lead_event_definition` with
        `event_type = :t AND status = 'active'` — backed by the
        partial index `ix_lead_event_definition_active`.

        If multiple active versions exist (shouldn't happen — domain
        discipline keeps exactly one active per event_type, but the
        DB doesn't enforce it), returns the highest version.
        """
        stmt = (
            select(LeadEventDefinition)
            .where(LeadEventDefinition.event_type == event_type)
            .where(LeadEventDefinition.status == "active")
            .order_by(LeadEventDefinition.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
