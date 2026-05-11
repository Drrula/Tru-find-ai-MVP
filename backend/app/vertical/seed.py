"""Seed-from-pack utility (per ADR-048 lifecycle stage "schema-time").

Writes a `VerticalPack`'s configuration surfaces into the
`vertical_*` tables. Used by operator commands and (eventually)
deploy hooks to populate the DB rows that B.3.4's engine reads from.

Idempotency contract for B.3.3:
- If a `vertical` row with the pack's `pack_id` already exists,
  `seed_pack` returns it immediately as a no-op. Child rows
  (weights, copy, templates) are NOT inspected — re-seeding a
  modified pack requires explicit clear+re-seed by the operator.
- On a fresh pack: creates the vertical row, then one row per
  weight, one row per copy entry, and three template rows
  (`tier_thresholds`, `competitor_pool`, `category_mapping`).

The function does NOT call `session.commit()` — the caller controls
the transaction boundary. Tests use mock sessions; operator scripts
wrap the call in their own commit/rollback.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Vertical
from app.db.repositories.vertical_copy_repo import VerticalCopyRepository
from app.db.repositories.vertical_repo import VerticalRepository
from app.db.repositories.vertical_signal_weight_repo import (
    VerticalSignalWeightRepository,
)
from app.db.repositories.vertical_template_repo import VerticalTemplateRepository
from app.vertical.pack import VerticalPack


async def seed_pack(pack: VerticalPack, session: AsyncSession) -> Vertical:
    """Idempotently seed `pack` into the `vertical_*` tables.

    Returns the `Vertical` row — either the existing one (when the
    pack was already seeded) or the freshly-created one. Callers can
    inspect the result to decide whether further seeding is needed
    in their own context.
    """
    vertical_repo = VerticalRepository(session, account_id=None)

    existing = await vertical_repo.find_by_pack_id(pack.pack_id)
    if existing is not None:
        return existing

    vertical = await vertical_repo.create(
        pack_id=pack.pack_id,
        display_name=pack.display_name,
        schema_version=pack.schema_version,
    )

    weight_repo = VerticalSignalWeightRepository(session, account_id=None)
    for signal_name, weight in pack.signal_weights().items():
        await weight_repo.create(
            vertical_id=vertical.id,
            signal_name=signal_name,
            weight=weight,
        )

    copy_repo = VerticalCopyRepository(session, account_id=None)
    for (locale, key), text in pack.copy().items():
        await copy_repo.create(
            vertical_id=vertical.id,
            locale=locale,
            key=key,
            text=text,
        )

    template_repo = VerticalTemplateRepository(session, account_id=None)
    await template_repo.create(
        vertical_id=vertical.id,
        name="tier_thresholds",
        config_json={"tiers": [list(t) for t in pack.tier_thresholds()]},
    )
    await template_repo.create(
        vertical_id=vertical.id,
        name="competitor_pool",
        config_json={"names": list(pack.competitor_pool())},
    )
    await template_repo.create(
        vertical_id=vertical.id,
        name="category_mapping",
        config_json={"mapping": dict(pack.category_mapping())},
    )

    return vertical
