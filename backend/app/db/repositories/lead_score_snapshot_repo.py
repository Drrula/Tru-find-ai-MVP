"""LeadScoreSnapshotRepository — append-only score time-series.

Per ADR-031 + ADR-010 + ADR-036 + ADR-047 (customer-owned: tenancy
filter active; no soft-delete column — snapshots are immutable).

APPEND-ONLY discipline: this repo exposes `create` + named query
methods. NO `update_*`, NO mutators. Inherited
`BaseRepository.soft_delete` naturally refuses (no deleted_at column
on LeadScoreSnapshot).

Per feedback_inspectability_over_abstraction: every read path has
an explicit named method, mirroring B.4.2 LeadEventRepository's shape.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.ids import new_id
from app.db.models import Lead, LeadScoreSnapshot
from app.db.repositories.base import BaseRepository


class LeadScoreSnapshotRepository(BaseRepository[LeadScoreSnapshot]):
    model_class = LeadScoreSnapshot

    async def create(
        self,
        *,
        lead: Lead,
        vertical_id: UUID,
        score: Decimal | float,
        score_breakdown: dict[str, Any],
        inputs: dict[str, Any],
        weight_version_at: datetime,
        computed_at: datetime,
    ) -> LeadScoreSnapshot:
        """Stage a new lead_score_snapshot row.

        Denormalizes `account_id` from `lead.account_id` so the
        account-scoped index works without joining `lead`. Mints
        UUIDv7 explicitly. `score` is normalized to Decimal via
        str() to preserve precision on the numeric(5,2) column
        (same pattern as B.4.3 weights).

        Append-only -- no updated_at, no deleted_at on the underlying
        row. Re-running with the same inputs simply produces a new
        snapshot row (not an UPDATE).
        """
        row = LeadScoreSnapshot(
            id=new_id(),
            account_id=lead.account_id,
            lead_id=lead.id,
            vertical_id=vertical_id,
            score=Decimal(str(score)),
            score_breakdown=score_breakdown,
            inputs=inputs,
            weight_version_at=weight_version_at,
            computed_at=computed_at,
        )
        self.add(row)
        return row

    async def find_current_for_lead(
        self, lead_id: UUID
    ) -> LeadScoreSnapshot | None:
        """Return the LATEST snapshot for `lead_id` within this repo's
        tenancy scope, or None if no snapshot has been recorded.

        ORDER BY computed_at DESC, id DESC LIMIT 1 -- tie-break on
        UUIDv7 id (time-sortable per ADR-033) for deterministic
        ordering when two snapshots land in the same microsecond.

        Account-scoped via BaseRepository tenancy filter. Backed by
        `ix_lead_score_snapshot_lead_computed`.
        """
        stmt = (
            self._base_select()
            .where(LeadScoreSnapshot.lead_id == lead_id)
            .order_by(
                LeadScoreSnapshot.computed_at.desc(),
                LeadScoreSnapshot.id.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_history_for_lead(
        self, lead_id: UUID
    ) -> list[LeadScoreSnapshot]:
        """Return ALL snapshots for `lead_id`, newest first.

        Account-scoped. Backed by `ix_lead_score_snapshot_lead_computed`.
        """
        stmt = (
            self._base_select()
            .where(LeadScoreSnapshot.lead_id == lead_id)
            .order_by(
                LeadScoreSnapshot.computed_at.desc(),
                LeadScoreSnapshot.id.desc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_for_account_vertical(
        self, vertical_id: UUID
    ) -> list[LeadScoreSnapshot]:
        """Return ALL snapshots in this account scoped to `vertical_id`,
        newest first.

        Operational query for "show me every recent lead score in this
        vertical." Account-scoped via the repo's tenancy filter.
        Backed by `ix_lead_score_snapshot_account_vertical_computed`.
        """
        stmt = (
            self._base_select()
            .where(LeadScoreSnapshot.vertical_id == vertical_id)
            .order_by(
                LeadScoreSnapshot.computed_at.desc(),
                LeadScoreSnapshot.id.desc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
