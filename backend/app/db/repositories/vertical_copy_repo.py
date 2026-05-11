"""VerticalCopy repository.

Per ADR-031 + ADR-046 (locale-keyed) + ADR-047 (platform-owned).
"""

from __future__ import annotations

from uuid import UUID

from app.core.ids import new_id
from app.db.models import VerticalCopy
from app.db.repositories.base import BaseRepository


class VerticalCopyRepository(BaseRepository[VerticalCopy]):
    model_class = VerticalCopy

    async def create(
        self,
        *,
        vertical_id: UUID,
        locale: str,
        key: str,
        text: str,
    ) -> VerticalCopy:
        """Stage a new copy row."""
        row = VerticalCopy(
            id=new_id(),
            vertical_id=vertical_id,
            locale=locale,
            key=key,
            text=text,
        )
        self.add(row)
        return row
