"""LeadSignalDefinitionRepository — catalog of lead signal names.

Per ADR-031 + ADR-036 + ADR-047 (platform-owned: no `account_id`
→ BaseRepository tenancy filter is naturally inert; no `deleted_at`
either; retirement via `default_enabled=False`).

Per feedback_inspectability_over_abstraction: explicit named
methods. `find_by_name` is the PK lookup; `find_all_enabled` is
the operational query.

Note: `name` is the PK (text), not a UUID. So `create()` does NOT
mint a UUIDv7 — the caller supplies the signal name directly.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.db.models import LeadSignalDefinition
from app.db.repositories.base import BaseRepository


class LeadSignalDefinitionRepository(BaseRepository[LeadSignalDefinition]):
    model_class = LeadSignalDefinition

    async def create(
        self,
        *,
        name: str,
        description: str,
        contributes_to: list[str],
        freshness_ttl_seconds: int,
        source_kind: str,
        default_weight: Decimal | float,
        default_enabled: bool = True,
    ) -> LeadSignalDefinition:
        """Stage a new catalog entry.

        Caller supplies `name` (the PK) directly — diverges from the
        UUIDv7-mint pattern used by every other repo.create() in the
        codebase because LeadSignalDefinition's PK is the signal name.

        `default_weight` is normalized to Decimal via str() to avoid
        float-precision noise on the numeric(4,3) column (matches
        the pattern in LeadEventDefinitionRepository.create).
        """
        row = LeadSignalDefinition(
            name=name,
            description=description,
            contributes_to=list(contributes_to),
            freshness_ttl_seconds=freshness_ttl_seconds,
            source_kind=source_kind,
            default_weight=Decimal(str(default_weight)),
            default_enabled=default_enabled,
        )
        self.add(row)
        return row

    async def find_by_name(self, name: str) -> LeadSignalDefinition | None:
        """PK lookup for a single signal definition. Returns None
        when the signal name is unknown."""
        return await self.find_one(name=name)

    async def find_all_enabled(self) -> list[LeadSignalDefinition]:
        """Operational query: "what signals are currently active?"
        Returns rows with `default_enabled = TRUE` sorted by name
        for deterministic order."""
        stmt = (
            select(LeadSignalDefinition)
            .where(LeadSignalDefinition.default_enabled.is_(True))
            .order_by(LeadSignalDefinition.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
