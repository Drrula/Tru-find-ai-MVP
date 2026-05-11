"""B.3.4 tests for `app.vertical.db_pack`.

Covers four surfaces:
  - `DatabaseBackedVerticalPack` class shape + Protocol satisfaction.
  - `load_pack_from_db(session, pack_id)` — happy path + missing-vertical.
  - `populate_pack_cache(session)` — happy path + tolerated DB errors.
  - `get_active_pack(pack_id)` — cache hit returns DB-backed pack;
    cache miss falls back to source-module pack via registry.
  - `clear_pack_cache()` — test-isolation helper actually clears.

The `_pack_cache` is process-global, so every test clears it before
+ after to avoid leakage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Vertical,
    VerticalCopy,
    VerticalSignalWeight,
    VerticalTemplate,
)
from app.vertical.db_pack import (
    DatabaseBackedVerticalPack,
    clear_pack_cache,
    get_active_pack,
    is_db_backed,
    load_pack_from_db,
    populate_pack_cache,
)
from app.vertical.pack import VerticalPack
from app.vertical.registry import UnknownPackError


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """Ensure every test starts + ends with an empty cache so the global
    `_pack_cache` doesn't leak between tests."""
    clear_pack_cache()
    yield
    clear_pack_cache()


@pytest.fixture
def mock_session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    return s


# --- DatabaseBackedVerticalPack class shape


def test_db_pack_satisfies_protocol() -> None:
    """Runtime-checkable Protocol — `isinstance` works."""
    pack = DatabaseBackedVerticalPack(
        pack_id="x",
        display_name="X",
        schema_version=1,
        weights={},
        copy={},
        competitor_pool=[],
        tier_thresholds=[],
        category_mapping={},
    )
    assert isinstance(pack, VerticalPack)


def test_db_pack_methods_return_copies_not_internal_state() -> None:
    """Mutating a returned dict/list must not affect the pack instance."""
    pack = DatabaseBackedVerticalPack(
        pack_id="x",
        display_name="X",
        schema_version=1,
        weights={"a": 0.5},
        copy={("en-US", "k"): "v"},
        competitor_pool=["one"],
        tier_thresholds=[(50, "ok")],
        category_mapping={"a": "b"},
    )
    pack.signal_weights()["mutated"] = 99.0
    pack.competitor_pool().append("mutated")
    pack.tier_thresholds().append((0, "mutated"))
    pack.category_mapping()["mutated"] = "mutated"
    pack.copy()[("en-US", "mutated")] = "mutated"

    # Re-read; no mutation should have leaked.
    assert "mutated" not in pack.signal_weights()
    assert "mutated" not in pack.competitor_pool()
    assert all(name != "mutated" for _, name in pack.tier_thresholds())
    assert "mutated" not in pack.category_mapping()
    assert ("en-US", "mutated") not in pack.copy()


def test_db_pack_identity_attributes() -> None:
    pack = DatabaseBackedVerticalPack(
        pack_id="local_business_ai_visibility",
        display_name="Local Business AI Visibility",
        schema_version=2,
        weights={},
        copy={},
        competitor_pool=[],
        tier_thresholds=[],
        category_mapping={},
    )
    assert pack.pack_id == "local_business_ai_visibility"
    assert pack.display_name == "Local Business AI Visibility"
    assert pack.schema_version == 2


# --- load_pack_from_db


async def test_load_pack_from_db_returns_none_when_vertical_missing(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `vertical` row -> None -> caller falls back to source pack."""
    from app.db.repositories.vertical_repo import VerticalRepository

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    result = await load_pack_from_db(mock_session, "nonexistent_pack")
    assert result is None


async def test_load_pack_from_db_returns_populated_pack_on_happy_path(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`vertical` + weights + copy + templates + lead-signal-weights
    (B.4.6) all land in the returned pack."""
    from app.db.models import VerticalLeadSignalWeight
    from app.db.repositories.vertical_repo import VerticalRepository

    vid = uuid4()
    vertical = Vertical(
        id=vid,
        pack_id="local_business_ai_visibility",
        display_name="Local Business AI Visibility",
        schema_version=1,
    )
    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=vertical)
    )

    # Mock session.execute responses for the FOUR sub-loads.
    # Load order: weights -> copy -> templates -> lead_signal_weights.
    weight_rows = [
        VerticalSignalWeight(
            id=uuid4(),
            vertical_id=vid,
            signal_name="website_presence",
            weight=Decimal("0.30"),
        ),
        VerticalSignalWeight(
            id=uuid4(),
            vertical_id=vid,
            signal_name="reviews",
            weight=Decimal("0.20"),
        ),
    ]
    copy_rows = [
        VerticalCopy(
            id=uuid4(),
            vertical_id=vid,
            locale="en-US",
            key="gap.no_website",
            text="No website detected.",
        ),
    ]
    template_rows = [
        VerticalTemplate(
            id=uuid4(),
            vertical_id=vid,
            name="competitor_pool",
            config_json={"names": ["TopRank Local", "Apex Listings"]},
        ),
        VerticalTemplate(
            id=uuid4(),
            vertical_id=vid,
            name="tier_thresholds",
            config_json={"tiers": [[80, "strong"], [50, "moderate"], [0, "weak"]]},
        ),
        VerticalTemplate(
            id=uuid4(),
            vertical_id=vid,
            name="category_mapping",
            config_json={"mapping": {"reviews": "authority"}},
        ),
    ]
    # B.4.6 lead-signal-weight rows (one active per signal_name).
    lead_weight_rows = [
        VerticalLeadSignalWeight(
            id=uuid4(),
            vertical_id=vid,
            signal_name="lead_quality_score",
            dimension="lead_quality",
            weight=Decimal("0.4"),
            effective_from=datetime.now(timezone.utc),
            effective_to=None,
        ),
    ]

    def _make_result(rows):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r

    mock_session.execute.side_effect = [
        _make_result(weight_rows),
        _make_result(copy_rows),
        _make_result(template_rows),
        _make_result(lead_weight_rows),  # B.4.6 4th sub-load
    ]

    pack = await load_pack_from_db(mock_session, "local_business_ai_visibility")

    assert pack is not None
    assert pack.pack_id == "local_business_ai_visibility"
    assert pack.display_name == "Local Business AI Visibility"
    assert pack.schema_version == 1
    assert pack.signal_weights() == {
        "website_presence": 0.30,
        "reviews": 0.20,
    }
    assert pack.copy() == {("en-US", "gap.no_website"): "No website detected."}
    assert pack.competitor_pool() == ["TopRank Local", "Apex Listings"]
    # JSONB stored as lists; restored to tuples by load_pack_from_db.
    assert pack.tier_thresholds() == [
        (80, "strong"),
        (50, "moderate"),
        (0, "weak"),
    ]
    assert pack.category_mapping() == {"reviews": "authority"}
    # B.4.6: lead-signal weights present, flattened (dimension dropped).
    assert pack.lead_signal_weights() == {"lead_quality_score": 0.4}


async def test_load_pack_from_db_takes_latest_weight_per_signal(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_load_current_weights` dedups by signal_name, keeping the first
    row (ordered DESC by effective_from) -> that's the current weight."""
    from app.db.repositories.vertical_repo import VerticalRepository

    vid = uuid4()
    monkeypatch.setattr(
        VerticalRepository,
        "find_by_pack_id",
        AsyncMock(
            return_value=Vertical(
                id=vid,
                pack_id="x",
                display_name="X",
                schema_version=1,
            )
        ),
    )

    # SQL ordered by (signal_name ASC, effective_from DESC); for a
    # signal_name with two rows, the first one in the result is the
    # latest effective_from.
    rows = [
        VerticalSignalWeight(
            id=uuid4(),
            vertical_id=vid,
            signal_name="reviews",
            weight=Decimal("0.25"),  # latest -> wins
        ),
        VerticalSignalWeight(
            id=uuid4(),
            vertical_id=vid,
            signal_name="reviews",
            weight=Decimal("0.10"),  # earlier -> ignored
        ),
    ]
    # 4 side-effects matching the 4 sub-loads in load_pack_from_db
    # (weights -> copy -> templates -> lead-signal-weights). Empty
    # lists for everything except the weights under test.
    results = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # B.4.6
    ]
    mock_session.execute.side_effect = results

    pack = await load_pack_from_db(mock_session, "x")
    assert pack is not None
    assert pack.signal_weights() == {"reviews": 0.25}
    # B.4.6: no lead-signal-weight rows mocked -> empty flat dict.
    assert pack.lead_signal_weights() == {}


# --- populate_pack_cache


async def test_populate_pack_cache_loads_into_cache(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pack = DatabaseBackedVerticalPack(
        pack_id="local_business_ai_visibility",
        display_name="X",
        schema_version=1,
        weights={"a": 0.5},
        copy={},
        competitor_pool=[],
        tier_thresholds=[],
        category_mapping={},
    )
    monkeypatch.setattr(
        "app.vertical.db_pack.load_pack_from_db",
        AsyncMock(return_value=fake_pack),
    )

    await populate_pack_cache(mock_session)

    assert is_db_backed("local_business_ai_visibility")


async def test_populate_pack_cache_tolerates_db_errors(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lifespan must not crash if DB is unavailable; cache stays empty."""

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr("app.vertical.db_pack.load_pack_from_db", _boom)

    # Must not raise.
    await populate_pack_cache(mock_session)

    assert not is_db_backed("local_business_ai_visibility")


async def test_populate_pack_cache_leaves_cache_empty_when_vertical_missing(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """find_by_pack_id returns None -> load_pack_from_db returns None ->
    cache stays empty for that pack_id."""
    monkeypatch.setattr(
        "app.vertical.db_pack.load_pack_from_db",
        AsyncMock(return_value=None),
    )

    await populate_pack_cache(mock_session)

    assert not is_db_backed("local_business_ai_visibility")


# --- get_active_pack


def test_get_active_pack_returns_db_backed_when_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = DatabaseBackedVerticalPack(
        pack_id="local_business_ai_visibility",
        display_name="X",
        schema_version=1,
        weights={"flag": 1.0},
        copy={},
        competitor_pool=[],
        tier_thresholds=[],
        category_mapping={},
    )
    # Manually populate the cache via the module-level dict.
    from app.vertical import db_pack as dp

    dp._pack_cache["local_business_ai_visibility"] = fake

    result = get_active_pack("local_business_ai_visibility")
    assert result is fake
    # Sanity: it's the DB-backed instance, not the source-module pack.
    assert isinstance(result, DatabaseBackedVerticalPack)


def test_get_active_pack_falls_back_to_source_when_cache_empty() -> None:
    """Cache miss -> registry lookup -> returns the source-module pack
    (which is registered at import time of
    `app.vertical.packs.local_business_ai_visibility`)."""
    from app.vertical.packs.local_business_ai_visibility import (
        PACK as source_pack,
        register_pack,
    )

    register_pack()  # idempotent — ensures the source pack is registered

    result = get_active_pack("local_business_ai_visibility")
    assert result is source_pack
    assert not isinstance(result, DatabaseBackedVerticalPack)


def test_get_active_pack_raises_when_neither_cached_nor_registered() -> None:
    """Total miss (cache + registry) -> UnknownPackError. Indicates a
    configuration error: someone removed a pack but the engine is still
    configured to ask for it."""
    with pytest.raises(UnknownPackError):
        get_active_pack("does_not_exist_in_cache_or_registry")


# --- is_db_backed diagnostic + clear_pack_cache


def test_is_db_backed_false_when_cache_empty() -> None:
    assert is_db_backed("local_business_ai_visibility") is False


def test_is_db_backed_true_when_cache_populated() -> None:
    from app.vertical import db_pack as dp

    dp._pack_cache["local_business_ai_visibility"] = DatabaseBackedVerticalPack(
        pack_id="local_business_ai_visibility",
        display_name="X",
        schema_version=1,
        weights={},
        copy={},
        competitor_pool=[],
        tier_thresholds=[],
        category_mapping={},
    )
    assert is_db_backed("local_business_ai_visibility") is True


def test_clear_pack_cache_empties_cache() -> None:
    from app.vertical import db_pack as dp

    dp._pack_cache["x"] = DatabaseBackedVerticalPack(
        pack_id="x",
        display_name="X",
        schema_version=1,
        weights={},
        copy={},
        competitor_pool=[],
        tier_thresholds=[],
        category_mapping={},
    )
    assert is_db_backed("x")
    clear_pack_cache()
    assert not is_db_backed("x")
