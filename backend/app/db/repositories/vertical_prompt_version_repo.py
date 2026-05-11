"""VerticalPromptVersion repository.

Per ADR-031 + ADR-020 (versioned prompts) + ADR-047 (platform-owned).

B.3.3 ships simple `create()` only. The "active prompt by key" lookup
lands when prompt-management work activates (the
`local_business_ai_visibility` pack carries zero prompts today).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.core.ids import new_id
from app.db.models import VerticalPromptVersion
from app.db.repositories.base import BaseRepository

PromptStatus = Literal["draft", "active", "archived"]


class VerticalPromptVersionRepository(BaseRepository[VerticalPromptVersion]):
    model_class = VerticalPromptVersion

    async def create(
        self,
        *,
        vertical_id: UUID,
        prompt_key: str,
        version: int,
        prompt_text: str,
        status: PromptStatus = "draft",
    ) -> VerticalPromptVersion:
        """Stage a new prompt-version row."""
        row = VerticalPromptVersion(
            id=new_id(),
            vertical_id=vertical_id,
            prompt_key=prompt_key,
            version=version,
            prompt_text=prompt_text,
            status=status,
        )
        self.add(row)
        return row
