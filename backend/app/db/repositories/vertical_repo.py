"""Vertical repository — config-root lookups + creation.

Per ADR-031 + ADR-047 (platform-owned: no `account_id`; the
BaseRepository tenancy filter is naturally inert). No `deleted_at`
either; verticals follow a version-and-replace lifecycle.

Pass `account_id=None` to the constructor.
"""

from __future__ import annotations

from app.core.ids import new_id
from app.db.models import Vertical
from app.db.repositories.base import BaseRepository


class VerticalRepository(BaseRepository[Vertical]):
    model_class = Vertical

    async def create(
        self,
        *,
        pack_id: str,
        display_name: str,
        schema_version: int,
    ) -> Vertical:
        """Stage a new vertical row.

        Mints the UUIDv7 id explicitly so callers can read `.id`
        immediately (needed by `seed_pack` to create child rows that
        FK to this row before flush).
        """
        vertical = Vertical(
            id=new_id(),
            pack_id=pack_id,
            display_name=display_name,
            schema_version=schema_version,
        )
        self.add(vertical)
        return vertical

    async def find_by_pack_id(self, pack_id: str) -> Vertical | None:
        """Look up a vertical by its pack identifier (the natural key)."""
        return await self.find_one(pack_id=pack_id)
