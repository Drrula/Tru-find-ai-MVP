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
    # Expected: 1 vertical + 4 weights + 13 copy + 3 templates +
    # 0 lead-signal-weights (B.4.6 empty pack) = 21 staged.
    expected_total = (
        1
        + len(PACK.signal_weights())
        + len(PACK.copy())
        + 3  # tier_thresholds, competitor_pool, category_mapping
        + len(PACK.lead_signal_weights())  # B.4.6: 0 in the reference pack
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


# ============================================================================
# B.4.6: lead-signal weight seeding pathway
# ============================================================================


async def test_seed_pack_writes_zero_lead_signal_weights_for_empty_pack(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B.4.6 default state: the reference pack returns
    `lead_signal_weights() == {}` so no VerticalLeadSignalWeight rows
    are staged. The pathway code runs (loop iterates over zero
    entries) but produces no writes."""
    from app.db.models import VerticalLeadSignalWeight
    from app.db.repositories.vertical_repo import VerticalRepository
    from app.vertical.packs.local_business_ai_visibility import PACK
    from app.vertical.seed import seed_pack

    # Confirm precondition: B.4.6 reference pack is empty here.
    assert PACK.lead_signal_weights() == {}

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    await seed_pack(PACK, mock_session)

    staged_lead_weights = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], VerticalLeadSignalWeight)
    ]
    assert staged_lead_weights == []


async def test_seed_pack_writes_lead_signal_weights_with_default_dimension(
    mock_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-empty `lead_signal_weights()` -> one row per entry with the
    documented default dimension `'lead_quality'`. Future packs that
    need multi-dimension weights extend the Protocol additively; B.4.6
    handles the flat-dict case end-to-end."""
    from decimal import Decimal as _Decimal

    from app.db.models import Vertical, VerticalLeadSignalWeight
    from app.db.repositories.vertical_repo import VerticalRepository
    from app.vertical.seed import (
        LEAD_SIGNAL_WEIGHT_DEFAULT_DIMENSION,
        seed_pack,
    )

    # Build a synthetic pack with non-empty lead_signal_weights.
    class _PackWithLeadWeights:
        pack_id = "synthetic_with_lead_weights"
        display_name = "Synthetic"
        schema_version = 1

        def signal_weights(self) -> dict[str, float]:
            return {}

        def copy(self) -> dict[tuple[str, str], str]:
            return {}

        def competitor_pool(self) -> list[str]:
            return []

        def tier_thresholds(self) -> list[tuple[int, str]]:
            return []

        def category_mapping(self) -> dict[str, str]:
            return {}

        def lead_signal_weights(self) -> dict[str, float]:
            return {"signal_a": 0.4, "signal_b": 0.6}

    monkeypatch.setattr(
        VerticalRepository, "find_by_pack_id", AsyncMock(return_value=None)
    )

    pack = _PackWithLeadWeights()
    await seed_pack(pack, mock_session)

    staged_lead_weights = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], VerticalLeadSignalWeight)
    ]
    assert {w.signal_name for w in staged_lead_weights} == {"signal_a", "signal_b"}

    # All rows carry the documented default dimension.
    assert all(
        w.dimension == LEAD_SIGNAL_WEIGHT_DEFAULT_DIMENSION
        for w in staged_lead_weights
    )
    assert LEAD_SIGNAL_WEIGHT_DEFAULT_DIMENSION == "lead_quality"

    # Weights converted to Decimal by the repo (matches
    # VerticalLeadSignalWeightRepository.create behavior).
    for w in staged_lead_weights:
        assert isinstance(w.weight, _Decimal)

    # effective_from is stamped at seed time (not NULL); effective_to
    # defaults to NULL (active row).
    for w in staged_lead_weights:
        assert w.effective_from is not None
        assert w.effective_to is None
