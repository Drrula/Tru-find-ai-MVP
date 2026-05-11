"""VerticalTemplate repository.

Per ADR-031 + ADR-047 (platform-owned).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.ids import new_id
from app.db.models import VerticalTemplate
from app.db.repositories.base import BaseRepository


class VerticalTemplateRepository(BaseRepository[VerticalTemplate]):
    model_class = VerticalTemplate

    async def create(
        self,
        *,
        vertical_id: UUID,
        name: str,
        config_json: dict[str, Any],
    ) -> VerticalTemplate:
        """Stage a new template row."""
        row = VerticalTemplate(
            id=new_id(),
            vertical_id=vertical_id,
            name=name,
            config_json=config_json,
        )
        self.add(row)
        return row
