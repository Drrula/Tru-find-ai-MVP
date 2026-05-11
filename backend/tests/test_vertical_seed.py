"""B.3.3 tests for `app.vertical.seed.seed_pack`.

Mock-only. Verifies:
- On a fresh DB (find_by_pack_id returns None): creates the vertical,
  one row per weight, one row per copy entry, three template rows
  (tier_thresholds, competitor_pool, category_mapping).
- On a populated DB (find_by_pack_id returns existing): no-op, no
  writes; returns the existing row.
- Does NOT call session.commit() (caller controls the transaction).
- Weights are passed as Decimal to the weight repo.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Vertical


@pytest.fixture
def mock_session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.rollback = AsyncMock()
    return s


async def test_seed_pack_fresh_db_creates_all_rows(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: pack not yet in DB -> seed creates everything."""
    from app.vertical.packs.local_business_ai_visibility import PACK
    from app.vertical.seed import seed_pack

    # find_by_pack_id returns None (fresh DB)
    from app.db.repositories.vertical_repo import VerticalRepository

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    result = await seed_pack(PACK, mock_session)

    assert isinstance(result, Vertical)
    assert result.pack_id == PACK.pack_id

    # session.add is the staging mechanism; count the total calls.
    # Expected: 1 vertical + 4 weights + 13 copy + 3 templates = 21 staged.
    expected_total = (
        1
        + len(PACK.signal_weights())
        + len(PACK.copy())
        + 3  # tier_thresholds, competitor_pool, category_mapping
    )
    assert mock_session.add.call_count == expected_total

    # Verify the seed did NOT commit the transaction itself.
    mock_session.commit.assert_not_called()


async def test_seed_pack_idempotent_when_pack_already_seeded(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When find_by_pack_id returns the existing vertical row, the seed
    returns immediately with no additional writes."""
    from app.vertical.packs.local_business_ai_visibility import PACK
    from app.vertical.seed import seed_pack

    existing = Vertical(
        id=uuid4(),
        pack_id=PACK.pack_id,
        display_name=PACK.display_name,
        schema_version=PACK.schema_version,
    )

    from app.db.repositories.vertical_repo import VerticalRepository

    monkeypatch.setattr(
        VerticalRepository,
        "find_by_pack_id",
        AsyncMock(return_value=existing),
    )

    result = await seed_pack(PACK, mock_session)

    assert result is existing
    # No staging calls at all on the idempotent path.
    mock_session.add.assert_not_called()


async def test_seed_pack_writes_weights_with_correct_signal_names(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spot-check: every weight in the pack lands as a staged weight row."""
    from app.vertical.packs.local_business_ai_visibility import PACK
    from app.vertical.seed import seed_pack
    from app.db.repositories.vertical_repo import VerticalRepository

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    await seed_pack(PACK, mock_session)

    # Inspect the staged objects: filter to VerticalSignalWeight instances.
    from app.db.models import VerticalSignalWeight

    staged_weights = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], VerticalSignalWeight)
    ]
    assert {w.signal_name for w in staged_weights} == set(
        PACK.signal_weights().keys()
    )
    # And weights converted to Decimal.
    for w in staged_weights:
        assert isinstance(w.weight, Decimal)


async def test_seed_pack_writes_three_templates_with_expected_names(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.vertical.packs.local_business_ai_visibility import PACK
    from app.vertical.seed import seed_pack
    from app.db.repositories.vertical_repo import VerticalRepository

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    await seed_pack(PACK, mock_session)

    from app.db.models import VerticalTemplate

    staged_templates = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], VerticalTemplate)
    ]
    template_names = {t.name for t in staged_templates}
    assert template_names == {
        "tier_thresholds",
        "competitor_pool",
        "category_mapping",
    }


async def test_seed_pack_template_config_json_shapes(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each template's config_json has the documented shape so B.3.4's
    engine can read it predictably."""
    from app.vertical.packs.local_business_ai_visibility import PACK
    from app.vertical.seed import seed_pack
    from app.db.repositories.vertical_repo import VerticalRepository

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    await seed_pack(PACK, mock_session)

    from app.db.models import VerticalTemplate

    by_name = {
        call.args[0].name: call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], VerticalTemplate)
    }
    assert "tiers" in by_name["tier_thresholds"].config_json
    assert "names" in by_name["competitor_pool"].config_json
    assert "mapping" in by_name["category_mapping"].config_json
    # Sanity: counts match pack contents.
    assert len(by_name["tier_thresholds"].config_json["tiers"]) == len(
        PACK.tier_thresholds()
    )
    assert len(by_name["competitor_pool"].config_json["names"]) == len(
        PACK.competitor_pool()
    )
    assert by_name["category_mapping"].config_json["mapping"] == dict(
        PACK.category_mapping()
    )
