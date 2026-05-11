"""VerticalSignalWeight repository.

Per ADR-031 + ADR-047 (platform-owned: no tenancy filter).

B.3.3 ships simple `create()` only. The "current weight" lookup
(latest `effective_from <= now()` per signal) lands in B.3.4 along
with the engine wiring; for now the seed utility writes initial rows
with `effective_from = now()` and the scoring engine continues to
read from the pack module.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.core.ids import new_id
from app.db.models import VerticalSignalWeight
from app.db.repositories.base import BaseRepository


class VerticalSignalWeightRepository(BaseRepository[VerticalSignalWeight]):
    model_class = VerticalSignalWeight

    async def create(
        self,
        *,
        vertical_id: UUID,
        signal_name: str,
        weight: Decimal | float,
        effective_from: datetime | None = None,
    ) -> VerticalSignalWeight:
        """Stage a new weight row.

        `effective_from=None` uses the DB-side default (`now()`). Pass
        explicitly for historical backfill.
        """
        kwargs: dict = {
            "id": new_id(),
            "vertical_id": vertical_id,
            "signal_name": signal_name,
            "weight": Decimal(str(weight)),
        }
        if effective_from is not None:
            kwargs["effective_from"] = effective_from
        row = VerticalSignalWeight(**kwargs)
        self.add(row)
        return row
