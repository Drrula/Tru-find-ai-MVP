"""VerticalLeadSignalWeightRepository — per-vertical weight history.

Per ADR-031 + ADR-011 + ADR-036 + ADR-047 (platform-owned: no
`account_id` → tenancy filter inert; no `deleted_at` → soft-delete
filter inert).

Per feedback_inspectability_over_abstraction: explicit named
methods. `close_active` is the ONLY mutator across all three B.4.3
repos — deliberate, because the column exists per spec and the
alternative is operators running raw SQL.

The "active" weight for `(vertical_id, signal_name, dimension)` is
the row with:
- the latest `effective_from` AND
- `effective_to IS NULL`
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import select, update

from app.core.ids import new_id
from app.db.models import VerticalLeadSignalWeight
from app.db.repositories.base import BaseRepository


class VerticalLeadSignalWeightRepository(
    BaseRepository[VerticalLeadSignalWeight]
):
    model_class = VerticalLeadSignalWeight

    async def create(
        self,
        *,
        vertical_id: UUID,
        signal_name: str,
        dimension: str,
        weight: Decimal | float,
        effective_from: datetime,
        enabled: bool = True,
    ) -> VerticalLeadSignalWeight:
        """Stage a new weight row for `(vertical_id, signal_name,
        dimension)`.

        Mints UUIDv7 explicitly. `weight` is normalized to Decimal
        via str() (matches the pattern from B.3.3
        VerticalSignalWeightRepository).

        Callers retire the prior active row separately via
        `close_active(...)` — `create` does NOT auto-close prior
        weights. Two-step pattern keeps the operation inspectable.
        """
        row = VerticalLeadSignalWeight(
            id=new_id(),
            vertical_id=vertical_id,
            signal_name=signal_name,
            dimension=dimension,
            weight=Decimal(str(weight)),
            enabled=enabled,
            effective_from=effective_from,
        )
        self.add(row)
        return row

    async def find_active(
        self,
        vertical_id: UUID,
        signal_name: str,
        dimension: str,
    ) -> VerticalLeadSignalWeight | None:
        """Return the current active weight for
        `(vertical_id, signal_name, dimension)`, or None.

        Active = `effective_to IS NULL`, sorted by `effective_from
        DESC` so the most recently opened row wins if more than one
        is unclosed (which is a discipline violation — exactly one
        active per tuple — but tolerated at query time).
        """
        stmt = (
            select(VerticalLeadSignalWeight)
            .where(VerticalLeadSignalWeight.vertical_id == vertical_id)
            .where(VerticalLeadSignalWeight.signal_name == signal_name)
            .where(VerticalLeadSignalWeight.dimension == dimension)
            .where(VerticalLeadSignalWeight.effective_to.is_(None))
            .order_by(VerticalLeadSignalWeight.effective_from.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_all_active_for_vertical(
        self,
        vertical_id: UUID,
        *,
        at_time: datetime | None = None,
    ) -> list[VerticalLeadSignalWeight]:
        """Return all active weight rows for `vertical_id`.

        Default mode (`at_time=None`): rows currently active --
        `effective_to IS NULL`. This is the dominant operational
        query ("what are the live weights for this vertical right
        now?").

        Replay mode (`at_time=<timestamp>`): rows active at that
        moment -- `effective_from <= at_time` AND
        `(effective_to IS NULL OR effective_to > at_time)`. Used by
        `compute_lead_score` (B.5.2) for ADR-010 replay semantics
        against historical weight versions.

        Returns rows sorted by (signal_name, dimension) for
        deterministic ordering. If multiple rows share a
        (signal_name, dimension) tuple in active state (a discipline
        violation -- exactly one active per tuple), all are returned;
        caller decides how to handle.
        """
        stmt = select(VerticalLeadSignalWeight).where(
            VerticalLeadSignalWeight.vertical_id == vertical_id
        )
        if at_time is None:
            stmt = stmt.where(
                VerticalLeadSignalWeight.effective_to.is_(None)
            )
        else:
            stmt = stmt.where(
                VerticalLeadSignalWeight.effective_from <= at_time
            ).where(
                (VerticalLeadSignalWeight.effective_to.is_(None))
                | (VerticalLeadSignalWeight.effective_to > at_time)
            )
        stmt = stmt.order_by(
            VerticalLeadSignalWeight.signal_name,
            VerticalLeadSignalWeight.dimension,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def close_active(
        self,
        vertical_id: UUID,
        signal_name: str,
        dimension: str,
        effective_to: datetime,
    ) -> bool:
        """Set `effective_to` on the active row for
        `(vertical_id, signal_name, dimension)`.

        Returns True if a row was updated. The ONLY mutator across
        the three B.4.3 repos -- the column exists per spec, and
        the alternative is operators running raw SQL which is worse
        for inspectability. One explicit UPDATE.

        Targets ONLY rows with `effective_to IS NULL` so re-running
        close_active is a no-op (returns False).
        """
        stmt = (
            update(VerticalLeadSignalWeight)
            .where(VerticalLeadSignalWeight.vertical_id == vertical_id)
            .where(VerticalLeadSignalWeight.signal_name == signal_name)
            .where(VerticalLeadSignalWeight.dimension == dimension)
            .where(VerticalLeadSignalWeight.effective_to.is_(None))
            .values(effective_to=effective_to)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0
