"""B.4.2 behavior tests for LeadEventDefinitionRepository +
LeadEventRepository.

Mock-only per phase-b4-plan.md §2 #11.

Covers:
- LeadEventDefinitionRepository: subclass + model_class + tenancy
  filter inert (platform-owned) + create() shape +
  find_active_by_event_type SQL.
- LeadEventRepository: subclass + model_class + tenancy filter
  active + create() denormalizes account_id from lead + named
  query methods (find_by_lead_id, find_by_event_type).
- APPEND-ONLY discipline: BaseRepository.soft_delete raises on
  LeadEvent because there's no deleted_at column.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead, LeadEvent, LeadEventDefinition
from app.db.repositories.base import BaseRepository
from app.db.repositories.lead_event_definition_repo import (
    LeadEventDefinitionRepository,
)
from app.db.repositories.lead_event_repo import LeadEventRepository


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
# LeadEventDefinitionRepository (platform-owned)
# ============================================================================


def test_definition_repo_subclass_and_model() -> None:
    assert issubclass(LeadEventDefinitionRepository, BaseRepository)
    assert LeadEventDefinitionRepository.model_class is LeadEventDefinition


def test_definition_repo_tenancy_filter_inert(
    mock_session: AsyncMock,
) -> None:
    """LeadEventDefinition is platform-owned -> no account_id ->
    tenancy filter never fires."""
    repo = LeadEventDefinitionRepository(
        session=mock_session, account_id=None
    )
    assert repo._has_account_id_column is False
    assert repo._has_deleted_at_column is False


async def test_definition_create_stages_with_decimal_weight(
    mock_session: AsyncMock,
) -> None:
    repo = LeadEventDefinitionRepository(
        session=mock_session, account_id=None
    )

    row = await repo.create(
        event_type="lead.lifecycle.transition",
        version=1,
        status="active",
        category="lifecycle",
        source="domain",
        default_weight=0.25,
        freshness_ttl_seconds=3600,
        payload_schema={"type": "object"},
    )

    assert isinstance(row, LeadEventDefinition)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.event_type == "lead.lifecycle.transition"
    assert row.version == 1
    assert row.status == "active"
    assert row.default_weight == Decimal("0.25")
    assert row.lenient is False  # default
    mock_session.add.assert_called_once_with(row)


async def test_definition_find_active_by_event_type_filters_active(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = LeadEventDefinitionRepository(
        session=mock_session, account_id=None
    )
    out = await repo.find_active_by_event_type("does.not.exist")

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "event_type" in sql
    assert "status" in sql  # filters by status='active'
    assert "limit" in sql  # we ORDER BY version DESC LIMIT 1


# ============================================================================
# LeadEventRepository (customer-owned, append-only)
# ============================================================================


def test_event_repo_subclass_and_model() -> None:
    assert issubclass(LeadEventRepository, BaseRepository)
    assert LeadEventRepository.model_class is LeadEvent


def test_event_repo_tenancy_filter_active_no_soft_delete(
    mock_session: AsyncMock,
) -> None:
    """LeadEvent is customer-owned -> account_id present -> tenancy
    filter active. NO deleted_at -> soft-delete filter inert."""
    repo = LeadEventRepository(session=mock_session, account_id=uuid4())
    assert repo._has_account_id_column is True
    assert repo._has_deleted_at_column is False


def test_event_repo_base_select_raises_when_account_id_none(
    mock_session: AsyncMock,
) -> None:
    """Account-scoped only -- no system-context read path for lead
    events."""
    repo = LeadEventRepository(session=mock_session, account_id=None)
    with pytest.raises(ValueError, match="requires account_id"):
        repo._base_select()


async def test_event_create_denormalizes_account_id_from_lead(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    definition_id = uuid4()
    now = datetime.now(timezone.utc)

    repo = LeadEventRepository(session=mock_session, account_id=account_id)
    row = await repo.create(
        lead=lead,
        event_type="lead.signal.observed",
        event_definition_id=definition_id,
        payload={"signal_name": "review_count"},
        actor_kind="system",
        occurred_at=now - timedelta(minutes=5),
        recorded_at=now,
    )

    assert isinstance(row, LeadEvent)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.account_id == lead.account_id  # denormalized from lead
    assert row.lead_id == lead.id
    assert row.event_type == "lead.signal.observed"
    assert row.event_definition_id == definition_id
    assert row.payload == {"signal_name": "review_count"}
    assert row.actor_kind == "system"
    assert row.actor_user_id is None
    assert row.occurred_at == now - timedelta(minutes=5)
    assert row.recorded_at == now
    mock_session.add.assert_called_once_with(row)


async def test_event_create_accepts_actor_user_id(
    mock_session: AsyncMock,
) -> None:
    """User-initiated events carry actor_user_id."""
    account_id = uuid4()
    lead = _make_lead(account_id=account_id)
    user_id = uuid4()
    repo = LeadEventRepository(session=mock_session, account_id=account_id)

    row = await repo.create(
        lead=lead,
        event_type="lead.event.recorded",
        event_definition_id=uuid4(),
        payload={"note": "manual entry"},
        actor_kind="user",
        actor_user_id=user_id,
        occurred_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
    )

    assert row.actor_user_id == user_id
    assert row.actor_kind == "user"


async def test_event_find_by_lead_id_orders_newest_first(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadEventRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_by_lead_id(uuid4())

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "lead_id" in sql
    assert "account_id" in sql  # tenancy filter applied
    assert "order by" in sql
    assert "occurred_at desc" in sql


async def test_event_find_by_event_type_orders_newest_first(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadEventRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_by_event_type("lead.lifecycle.transition")

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "event_type" in sql
    assert "account_id" in sql
    assert "occurred_at desc" in sql


async def test_event_inherited_soft_delete_raises(
    mock_session: AsyncMock,
) -> None:
    """LeadEvent has no deleted_at -> base soft_delete refuses
    (the append-only discipline is enforced by the absent column)."""
    repo = LeadEventRepository(session=mock_session, account_id=uuid4())

    with pytest.raises(NotImplementedError, match="deleted_at"):
        await repo.soft_delete(uuid4())
