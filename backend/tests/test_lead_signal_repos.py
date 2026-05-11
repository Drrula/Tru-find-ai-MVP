"""B.4.3 behavior tests for the three lead-signal repositories.

Mock-only per phase-b4-plan.md §2 #11. Combined file (mirrors B.3.3
test_vertical_repos.py + B.4.2 test_lead_event_repos.py).

Covers:
- LeadSignalDefinitionRepository: subclass + tenancy filter inert +
  create (no UUID mint -- name is the PK) + find_by_name +
  find_all_enabled with `default_enabled=true` filter.
- LeadSignalRepository: subclass + tenancy filter active + no
  soft-delete filter + append-only (no mutators; inherited
  soft_delete raises) + create denormalizes account_id from lead +
  find_current orders by observed_at DESC then id DESC LIMIT 1 +
  find_history same ordering without limit + find_by_lead_id.
- VerticalLeadSignalWeightRepository: subclass + tenancy filter
  inert + create with Decimal + find_active filters
  effective_to IS NULL + close_active builds the ONE B.4.3
  mutator UPDATE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Lead,
    LeadSignal,
    LeadSignalDefinition,
    VerticalLeadSignalWeight,
)
from app.db.repositories.base import BaseRepository
from app.db.repositories.lead_signal_definition_repo import (
    LeadSignalDefinitionRepository,
)
from app.db.repositories.lead_signal_repo import LeadSignalRepository
from app.db.repositories.vertical_lead_signal_weight_repo import (
    VerticalLeadSignalWeightRepository,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    return s


def _where_sql(stmt: object) -> str:
    sql = " ".join(str(stmt.compile()).lower().split())
    if " where " not in sql:
        return ""
    return sql.split(" where ", 1)[1]


def _make_lead(account_id: UUID | None = None) -> Lead:
    return Lead(
        id=uuid4(),
        account_id=account_id or uuid4(),
        source="test",
        lifecycle_state="cold",
    )


# ============================================================================
# LeadSignalDefinitionRepository (platform-owned, name as text PK)
# ============================================================================


def test_definition_repo_subclass_and_model() -> None:
    assert issubclass(LeadSignalDefinitionRepository, BaseRepository)
    assert (
        LeadSignalDefinitionRepository.model_class is LeadSignalDefinition
    )


def test_definition_repo_tenancy_filter_inert(
    mock_session: AsyncMock,
) -> None:
    repo = LeadSignalDefinitionRepository(
        session=mock_session, account_id=None
    )
    assert repo._has_account_id_column is False
    assert repo._has_deleted_at_column is False


async def test_definition_create_uses_name_as_pk_no_uuid_mint(
    mock_session: AsyncMock,
) -> None:
    """Diverges from UUIDv7 pattern -- `name` is the PK supplied by
    the caller."""
    repo = LeadSignalDefinitionRepository(
        session=mock_session, account_id=None
    )

    row = await repo.create(
        name="lead_quality_score",
        description="Composite quality indicator for the lead.",
        contributes_to=["lead_quality", "qualification"],
        freshness_ttl_seconds=86400,
        source_kind="computed",
        default_weight=0.5,
    )

    assert isinstance(row, LeadSignalDefinition)
    assert row.name == "lead_quality_score"
    assert row.contributes_to == ["lead_quality", "qualification"]
    assert row.default_weight == Decimal("0.5")
    assert row.default_enabled is True
    mock_session.add.assert_called_once_with(row)


async def test_definition_find_by_name(mock_session: AsyncMock) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = LeadSignalDefinitionRepository(
        session=mock_session, account_id=None
    )
    out = await repo.find_by_name("does_not_exist")

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "name" in sql


async def test_definition_find_all_enabled_filters_default_enabled_true(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadSignalDefinitionRepository(
        session=mock_session, account_id=None
    )
    out = await repo.find_all_enabled()

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "default_enabled" in sql
    assert "order by" in sql  # deterministic ordering by name


# ============================================================================
# LeadSignalRepository (customer-owned, append-only)
# ============================================================================


def test_signal_repo_subclass_and_model() -> None:
    assert issubclass(LeadSignalRepository, BaseRepository)
    assert LeadSignalRepository.model_class is LeadSignal


def test_signal_repo_tenancy_filter_active_no_soft_delete(
    mock_session: AsyncMock,
) -> None:
    repo = LeadSignalRepository(session=mock_session, account_id=uuid4())
    assert repo._has_account_id_column is True
    assert repo._has_deleted_at_column is False


def test_signal_repo_base_select_raises_without_account_id(
    mock_session: AsyncMock,
) -> None:
    """Account-scoped only -- no system-context read path for lead
    signals."""
    repo = LeadSignalRepository(session=mock_session, account_id=None)
    with pytest.raises(ValueError, match="requires account_id"):
        repo._base_select()


async def test_signal_create_denormalizes_account_id_from_lead(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    now = datetime.now(timezone.utc)

    repo = LeadSignalRepository(session=mock_session, account_id=account_id)
    row = await repo.create(
        lead=lead,
        signal_name="review_count",
        value={"count": 42},
        source="google_business",
        observed_at=now,
        recorded_at=now,
    )

    assert isinstance(row, LeadSignal)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.account_id == lead.account_id  # denormalized
    assert row.lead_id == lead.id
    assert row.signal_name == "review_count"
    assert row.value == {"count": 42}
    assert row.source == "google_business"
    assert row.observed_at == now
    assert row.recorded_at == now
    assert row.source_ref_id is None
    mock_session.add.assert_called_once_with(row)


async def test_signal_create_accepts_source_ref_id(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    ref_id = uuid4()
    now = datetime.now(timezone.utc)

    repo = LeadSignalRepository(session=mock_session, account_id=account_id)
    row = await repo.create(
        lead=lead,
        signal_name="referrer",
        value={"url": "https://example.com"},
        source="webhook",
        observed_at=now,
        recorded_at=now,
        source_ref_id=ref_id,
    )

    assert row.source_ref_id == ref_id


async def test_signal_find_current_orders_observed_desc_id_desc_limit_1(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = LeadSignalRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_current(uuid4(), "review_count")

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "lead_id" in sql
    assert "signal_name" in sql
    assert "account_id" in sql  # tenancy filter
    assert "order by" in sql
    assert "observed_at desc" in sql
    # Tie-break on id DESC (UUIDv7 is time-sortable per ADR-033).
    assert "id desc" in sql
    assert "limit" in sql


async def test_signal_find_history_orders_newest_first_no_limit(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadSignalRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_history(uuid4(), "review_count")

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "lead_id" in sql
    assert "signal_name" in sql
    assert "observed_at desc" in sql
    assert "limit" not in sql


async def test_signal_find_by_lead_id_all_signals_newest_first(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadSignalRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_by_lead_id(uuid4())

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "lead_id" in sql
    assert "signal_name" not in _where_sql(sent_stmt)
    assert "observed_at desc" in sql


async def test_signal_inherited_soft_delete_raises(
    mock_session: AsyncMock,
) -> None:
    """Append-only contract enforced by absent deleted_at column."""
    repo = LeadSignalRepository(session=mock_session, account_id=uuid4())
    with pytest.raises(NotImplementedError, match="deleted_at"):
        await repo.soft_delete(uuid4())


# ============================================================================
# VerticalLeadSignalWeightRepository (platform-owned, ONE mutator)
# ============================================================================


def test_weight_repo_subclass_and_model() -> None:
    assert issubclass(VerticalLeadSignalWeightRepository, BaseRepository)
    assert (
        VerticalLeadSignalWeightRepository.model_class
        is VerticalLeadSignalWeight
    )


def test_weight_repo_tenancy_filter_inert(mock_session: AsyncMock) -> None:
    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    assert repo._has_account_id_column is False
    assert repo._has_deleted_at_column is False


async def test_weight_create_stages_with_decimal(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    when = datetime.now(timezone.utc)
    row = await repo.create(
        vertical_id=uuid4(),
        signal_name="lead_quality_score",
        dimension="lead_quality",
        weight=0.75,
        effective_from=when,
    )

    assert isinstance(row, VerticalLeadSignalWeight)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.dimension == "lead_quality"
    assert row.weight == Decimal("0.75")
    assert row.effective_from == when
    assert row.effective_to is None
    assert row.enabled is True
    mock_session.add.assert_called_once_with(row)


async def test_weight_find_active_filters_effective_to_null(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    out = await repo.find_active(uuid4(), "review_count", "engagement")

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "vertical_id" in sql
    assert "signal_name" in sql
    assert "dimension" in sql
    assert "effective_to is null" in sql
    assert "effective_from desc" in sql
    assert "limit" in sql


async def test_weight_close_active_builds_one_update_only_mutator(
    mock_session: AsyncMock,
) -> None:
    """The ONE mutator across B.4.3 -- a single explicit UPDATE
    against rows where effective_to IS NULL. Re-running close_active
    on an already-closed row is a no-op (returns False)."""
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    when = datetime.now(timezone.utc) + timedelta(seconds=1)
    closed = await repo.close_active(
        vertical_id=uuid4(),
        signal_name="lead_quality_score",
        dimension="lead_quality",
        effective_to=when,
    )

    assert closed is True
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "update" in sql and "vertical_lead_signal_weight" in sql
    assert "effective_to" in sql
    # Targets ONLY unclosed rows so re-running is a no-op.
    assert "effective_to is null" in sql


async def test_weight_close_active_idempotent_no_op_returns_false(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.rowcount = 0
    mock_session.execute.return_value = result

    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    closed = await repo.close_active(
        vertical_id=uuid4(),
        signal_name="x",
        dimension="y",
        effective_to=datetime.now(timezone.utc),
    )

    assert closed is False


# ============================================================================
# B.5.2: VerticalLeadSignalWeightRepository.find_all_active_for_vertical
# ============================================================================


async def test_find_all_active_for_vertical_default_mode_filters_effective_to_null(
    mock_session: AsyncMock,
) -> None:
    """Default mode (at_time=None) returns rows currently active --
    effective_to IS NULL only."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    out = await repo.find_all_active_for_vertical(uuid4())

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "vertical_id" in sql
    assert "effective_to is null" in sql
    # Deterministic ordering by (signal_name, dimension).
    assert "order by" in sql
    assert "signal_name" in sql
    assert "dimension" in sql


async def test_find_all_active_for_vertical_replay_mode_at_historical_time(
    mock_session: AsyncMock,
) -> None:
    """Replay mode: at_time supplied -> returns rows that were active
    at that timestamp (effective_from <= at_time AND
    (effective_to IS NULL OR effective_to > at_time))."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    historical = datetime(2026, 4, 1, tzinfo=timezone.utc)
    out = await repo.find_all_active_for_vertical(
        uuid4(), at_time=historical
    )

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "vertical_id" in sql
    assert "effective_from" in sql  # effective_from <= at_time
    assert "effective_to" in sql  # effective_to IS NULL OR effective_to > at_time
    # Both branches of the historical-active predicate are present.
    assert "is null" in sql


async def test_find_all_active_for_vertical_no_rowcount_limit(
    mock_session: AsyncMock,
) -> None:
    """Returns ALL active rows for the vertical -- no implicit LIMIT
    (unlike find_active which is the singleton variant)."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = VerticalLeadSignalWeightRepository(
        session=mock_session, account_id=None
    )
    await repo.find_all_active_for_vertical(uuid4())

    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "limit" not in sql
