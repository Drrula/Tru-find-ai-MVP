"""B.5.1 behavior tests for LeadScoreSnapshotRepository.

Mock-only per phase-b5-plan.md §2 #16.

Covers:
- Class structure (model_class, BaseRepository subclass).
- Tenancy filter active (account_id present); soft-delete filter
  inert (no deleted_at — append-only).
- _base_select raises on account_id=None (account-scoped only).
- create() mints a UUIDv7 id, denormalizes account_id from lead,
  normalizes score to Decimal, stages.
- find_current_for_lead orders by computed_at DESC, id DESC, LIMIT 1.
- find_history_for_lead orders by computed_at DESC, id DESC, no limit.
- find_for_account_vertical filters by vertical_id + tenancy.
- Inherited soft_delete raises NotImplementedError (no deleted_at).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead, LeadScoreSnapshot
from app.db.repositories.base import BaseRepository
from app.db.repositories.lead_score_snapshot_repo import (
    LeadScoreSnapshotRepository,
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


# --- Class structure


def test_repo_subclass_and_model() -> None:
    assert issubclass(LeadScoreSnapshotRepository, BaseRepository)
    assert LeadScoreSnapshotRepository.model_class is LeadScoreSnapshot


def test_repo_tenancy_filter_active_no_soft_delete(
    mock_session: AsyncMock,
) -> None:
    """LeadScoreSnapshot is customer-owned -> account_id present ->
    tenancy filter active. APPEND-ONLY -> no deleted_at -> soft-delete
    filter inert."""
    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=uuid4()
    )
    assert repo._has_account_id_column is True
    assert repo._has_deleted_at_column is False


def test_base_select_raises_without_account_id(
    mock_session: AsyncMock,
) -> None:
    """Account-scoped only -- no system-context read path for
    lead-score snapshots."""
    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=None
    )
    with pytest.raises(ValueError, match="requires account_id"):
        repo._base_select()


# --- create


async def test_create_denormalizes_account_id_from_lead(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    vertical_id = uuid4()
    now = datetime.now(timezone.utc)

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=account_id
    )
    row = await repo.create(
        lead=lead,
        vertical_id=vertical_id,
        score=60.0,
        score_breakdown={"signal_contributions": []},
        inputs={"signals": {}},
        weight_version_at=now,
        computed_at=now,
    )

    assert isinstance(row, LeadScoreSnapshot)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.account_id == lead.account_id  # denormalized
    assert row.lead_id == lead.id
    assert row.vertical_id == vertical_id
    # Decimal normalization (str(...) round-trip preserves precision).
    assert row.score == Decimal("60.0")
    assert row.score_breakdown == {"signal_contributions": []}
    assert row.inputs == {"signals": {}}
    assert row.weight_version_at == now
    assert row.computed_at == now
    mock_session.add.assert_called_once_with(row)


async def test_create_normalizes_score_to_decimal(
    mock_session: AsyncMock,
) -> None:
    """Float input -> Decimal via str() to avoid float-precision noise
    on the numeric(5,2) column."""
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    now = datetime.now(timezone.utc)

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=account_id
    )

    row_float = await repo.create(
        lead=lead,
        vertical_id=uuid4(),
        score=75.50,
        score_breakdown={},
        inputs={},
        weight_version_at=now,
        computed_at=now,
    )
    assert isinstance(row_float.score, Decimal)
    assert row_float.score == Decimal("75.5")


async def test_create_accepts_decimal_score(
    mock_session: AsyncMock,
) -> None:
    """Caller passing Decimal directly should round-trip safely."""
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    now = datetime.now(timezone.utc)

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=account_id
    )

    row = await repo.create(
        lead=lead,
        vertical_id=uuid4(),
        score=Decimal("42.42"),
        score_breakdown={},
        inputs={},
        weight_version_at=now,
        computed_at=now,
    )
    assert row.score == Decimal("42.42")


async def test_create_preserves_distinct_weight_version_at_and_computed_at(
    mock_session: AsyncMock,
) -> None:
    """Backfill case: weight_version_at represents a past moment (when
    the operator chose to score using historical weights); computed_at
    is when the computation actually ran. Both timestamps land on
    distinct columns."""
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    historical = datetime(2026, 4, 1, tzinfo=timezone.utc)
    now = datetime(2026, 5, 11, tzinfo=timezone.utc)

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=account_id
    )
    row = await repo.create(
        lead=lead,
        vertical_id=uuid4(),
        score=Decimal("50.0"),
        score_breakdown={},
        inputs={},
        weight_version_at=historical,
        computed_at=now,
    )
    assert row.weight_version_at == historical
    assert row.computed_at == now
    assert row.weight_version_at != row.computed_at


# --- find_current_for_lead


async def test_find_current_for_lead_orders_computed_desc_id_desc_limit_1(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=uuid4()
    )
    out = await repo.find_current_for_lead(uuid4())

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "lead_id" in sql
    assert "account_id" in sql  # tenancy filter
    assert "order by" in sql
    assert "computed_at desc" in sql
    # Tie-break on id DESC (UUIDv7 is time-sortable per ADR-033).
    assert "id desc" in sql
    assert "limit" in sql


# --- find_history_for_lead


async def test_find_history_for_lead_orders_newest_first_no_limit(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=uuid4()
    )
    out = await repo.find_history_for_lead(uuid4())

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "lead_id" in sql
    assert "computed_at desc" in sql
    assert "limit" not in sql


# --- find_for_account_vertical


async def test_find_for_account_vertical_filters_by_vertical_and_tenancy(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=uuid4()
    )
    out = await repo.find_for_account_vertical(uuid4())

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "vertical_id" in where
    assert "account_id" in where
    assert "computed_at desc" in sql


# --- Append-only enforcement


async def test_inherited_soft_delete_raises(
    mock_session: AsyncMock,
) -> None:
    """Append-only contract enforced by absent deleted_at column --
    BaseRepository.soft_delete refuses NotImplementedError. The
    absence of the column IS the contract, mirroring B.4.2
    lead_event + B.4.3 lead_signal."""
    repo = LeadScoreSnapshotRepository(
        session=mock_session, account_id=uuid4()
    )
    with pytest.raises(NotImplementedError, match="deleted_at"):
        await repo.soft_delete(uuid4())
