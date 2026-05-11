"""Database-backed vertical packs + process-level cache (ADR-048
lifecycle stage "DB-runtime").

Three primary surfaces:
- `DatabaseBackedVerticalPack` — `VerticalPack` Protocol implementation
  whose method results are pre-loaded from the `vertical_*` tables. The
  Protocol methods are sync (return copies of in-memory dicts/lists);
  the loading is async and happens once at app startup via lifespan.
- `populate_pack_cache(session)` — async startup helper. Loads each
  configured pack from DB into the process-global cache. Tolerated
  failures (DB unavailable in tests / fresh deployments) leave the
  cache empty; `get_active_pack` then falls back to the source-module
  pack via the registry.
- `get_active_pack(pack_id)` — sync accessor used by the scoring
  engine + signal primitives. Cache hit returns the DB-backed pack;
  cache miss falls back to the registry source pack.

This pattern keeps the scoring path SYNC end-to-end (no async cascade
into signal probes or route handlers) while making ADR-011 actually
true in production: the DB rows seeded by `app.vertical.seed.seed_pack`
become the runtime source.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    VerticalCopy,
    VerticalSignalWeight,
    VerticalTemplate,
)
from app.db.repositories.vertical_repo import VerticalRepository
from app.vertical.pack import VerticalPack
from app.vertical.registry import UnknownPackError, lookup

log = structlog.get_logger("app.vertical.db_pack")


# --- DatabaseBackedVerticalPack


class DatabaseBackedVerticalPack:
    """Concrete `VerticalPack` whose configuration came from the
    `vertical_*` tables. Methods are sync and return COPIES of
    pre-loaded data so callers cannot mutate the cached instance."""

    def __init__(
        self,
        *,
        pack_id: str,
        display_name: str,
        schema_version: int,
        weights: dict[str, float],
        copy: dict[tuple[str, str], str],
        competitor_pool: list[str],
        tier_thresholds: list[tuple[int, str]],
        category_mapping: dict[str, str],
        lead_signal_weights: dict[str, float] | None = None,
    ) -> None:
        self.pack_id = pack_id
        self.display_name = display_name
        self.schema_version = schema_version
        self._weights = weights
        self._copy = copy
        self._competitor_pool = competitor_pool
        self._tier_thresholds = tier_thresholds
        self._category_mapping = category_mapping
        # B.4.6 additive Protocol surface. Defaults to empty dict so
        # existing test constructors (which don't pass this kwarg) keep
        # working with the same shape.
        self._lead_signal_weights = lead_signal_weights or {}

    def signal_weights(self) -> dict[str, float]:
        return dict(self._weights)

    def copy(self) -> dict[tuple[str, str], str]:
        return dict(self._copy)

    def competitor_pool(self) -> list[str]:
        return list(self._competitor_pool)

    def tier_thresholds(self) -> list[tuple[int, str]]:
        return list(self._tier_thresholds)

    def category_mapping(self) -> dict[str, str]:
        return dict(self._category_mapping)

    def lead_signal_weights(self) -> dict[str, float]:
        return dict(self._lead_signal_weights)


# --- DB loading


async def _load_current_weights(
    session: AsyncSession, vertical_id: UUID
) -> dict[str, float]:
    """Load latest `effective_from <= now()` weight per signal_name.

    Python-side dedup against the ordered result — small data, no need
    for a Postgres-specific DISTINCT ON. Returns an empty dict if no
    weight rows exist (caller decides how to react).
    """
    stmt = (
        select(VerticalSignalWeight)
        .where(VerticalSignalWeight.vertical_id == vertical_id)
        .where(VerticalSignalWeight.effective_from <= sa_func.now())
        .order_by(
            VerticalSignalWeight.signal_name,
            VerticalSignalWeight.effective_from.desc(),
        )
    )
    result = await session.execute(stmt)
    weights: dict[str, float] = {}
    for row in result.scalars().all():
        # First row per signal_name (ordered DESC) = the current weight.
        if row.signal_name not in weights:
            weights[row.signal_name] = float(row.weight)
    return weights


async def _load_copy(
    session: AsyncSession, vertical_id: UUID
) -> dict[tuple[str, str], str]:
    stmt = select(VerticalCopy).where(VerticalCopy.vertical_id == vertical_id)
    result = await session.execute(stmt)
    return {(row.locale, row.key): row.text for row in result.scalars().all()}


async def _load_templates(
    session: AsyncSession, vertical_id: UUID
) -> dict[str, dict[str, Any]]:
    stmt = select(VerticalTemplate).where(
        VerticalTemplate.vertical_id == vertical_id
    )
    result = await session.execute(stmt)
    return {row.name: row.config_json for row in result.scalars().all()}


async def _load_current_lead_signal_weights(
    session: AsyncSession, vertical_id: UUID
) -> dict[str, float]:
    """Load currently-active lead-signal weights, flattened to
    `{signal_name: weight}` for the Protocol's flat-dict shape.

    "Currently active" = `effective_to IS NULL`. Same dedup pattern
    as `_load_current_weights`: take the latest `effective_from`
    per signal_name if multiple unclosed rows exist (which is a
    discipline violation but tolerated at read time).

    DROPS the `dimension` column when flattening -- the Protocol's
    flat-dict shape predates multi-dimension support. When real
    packs need multi-dimension weights, an additive Protocol method
    extends the read path.

    Returns an empty dict if no weight rows exist (B.4.6 default
    state with the empty reference pack).
    """
    # Avoid importing at module-load time so seed-utility imports
    # don't pull this in unconditionally; the model is a B.4.3
    # addition and keeping the import local mirrors the lazy pattern
    # already used elsewhere in this module.
    from app.db.models import VerticalLeadSignalWeight

    stmt = (
        select(VerticalLeadSignalWeight)
        .where(VerticalLeadSignalWeight.vertical_id == vertical_id)
        .where(VerticalLeadSignalWeight.effective_to.is_(None))
        .order_by(
            VerticalLeadSignalWeight.signal_name,
            VerticalLeadSignalWeight.effective_from.desc(),
        )
    )
    result = await session.execute(stmt)
    weights: dict[str, float] = {}
    for row in result.scalars().all():
        if row.signal_name not in weights:
            weights[row.signal_name] = float(row.weight)
    return weights


async def load_pack_from_db(
    session: AsyncSession, pack_id: str
) -> DatabaseBackedVerticalPack | None:
    """Load a vertical's full configuration from DB.

    Returns None if no `vertical` row exists for `pack_id` — caller
    falls back to the source-module pack.
    """
    vertical_repo = VerticalRepository(session, account_id=None)
    vertical = await vertical_repo.find_by_pack_id(pack_id)
    if vertical is None:
        return None

    weights = await _load_current_weights(session, vertical.id)
    copy_map = await _load_copy(session, vertical.id)
    templates = await _load_templates(session, vertical.id)
    # B.4.6: load lead-signal weights (B.4.3 schema). Empty result
    # is the B.4.6 default since the reference pack returns {}.
    lead_signal_weights = await _load_current_lead_signal_weights(
        session, vertical.id
    )

    return DatabaseBackedVerticalPack(
        pack_id=vertical.pack_id,
        display_name=vertical.display_name,
        schema_version=vertical.schema_version,
        weights=weights,
        copy=copy_map,
        competitor_pool=list(
            templates.get("competitor_pool", {}).get("names", [])
        ),
        # Stored as `[[80, "strong"], ...]` (JSONB doesn't preserve
        # tuples); restore to tuples for the Protocol contract.
        tier_thresholds=[
            (int(min_score), str(name))
            for min_score, name in templates.get("tier_thresholds", {}).get(
                "tiers", []
            )
        ],
        category_mapping=dict(
            templates.get("category_mapping", {}).get("mapping", {})
        ),
        lead_signal_weights=lead_signal_weights,
    )


# --- Process-global cache


_pack_cache: dict[str, VerticalPack] = {}


async def populate_pack_cache(session: AsyncSession) -> None:
    """Pre-load all configured packs from DB into the cache.

    Called by the FastAPI lifespan at startup. Failures (DB
    unavailable, missing tables, etc.) are tolerated — the cache
    stays empty for the affected pack and `get_active_pack()` falls
    back to the source-module pack via the registry.

    B.3.4 ships with one configured pack (`Settings.default_vertical_pack_id`);
    future commits that introduce multi-pack deployments extend the
    list of pack_ids loaded here.
    """
    settings = get_settings()
    pack_ids = [settings.default_vertical_pack_id]

    for pack_id in pack_ids:
        try:
            db_pack = await load_pack_from_db(session, pack_id)
        except Exception:
            log.warning(
                "vertical_pack_db_load_failed",
                pack_id=pack_id,
                exc_info=True,
            )
            continue

        if db_pack is None:
            log.info(
                "vertical_pack_not_in_db_using_source_fallback",
                pack_id=pack_id,
            )
            continue

        _pack_cache[pack_id] = db_pack
        log.info(
            "vertical_pack_loaded_from_db",
            pack_id=pack_id,
            schema_version=db_pack.schema_version,
        )


def get_active_pack(pack_id: str) -> VerticalPack:
    """Return the active pack for `pack_id`.

    Cache hit: returns the DB-backed pack loaded at startup.
    Cache miss: falls back to the source-module pack via the registry
    (raises `UnknownPackError` only if neither cache nor registry has
    the pack — a configuration error).
    """
    cached = _pack_cache.get(pack_id)
    if cached is not None:
        return cached
    # Fallback to source-module pack. Lets fresh deployments + tests
    # operate without DB-seeded rows; production gets the DB-backed
    # version via the lifespan startup populate.
    return lookup(pack_id)


def is_db_backed(pack_id: str) -> bool:
    """Diagnostic: is the active pack for `pack_id` a DB-backed
    instance (True) or the source-module fallback (False)?

    Operators can hit a future health endpoint that reports this to
    confirm a deploy successfully loaded vertical config from DB.
    """
    return pack_id in _pack_cache


def clear_pack_cache() -> None:
    """Test-only: clear the cache. Do not call from production code."""
    _pack_cache.clear()


# Re-export the registry's UnknownPackError so callers don't need a
# second import to handle the all-misses error.
__all__ = [
    "DatabaseBackedVerticalPack",
    "UnknownPackError",
    "clear_pack_cache",
    "get_active_pack",
    "is_db_backed",
    "load_pack_from_db",
    "populate_pack_cache",
]
