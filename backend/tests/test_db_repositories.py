"""B.1.5 tests for BaseRepository + AccountRepository.

NO real database — all tests use mock AsyncSession. The contract being
verified:

- Class-level configuration (model_class assigned correctly).
- Column introspection (has_account_id_column, has_deleted_at_column)
  reflects the model's actual columns.
- _base_select includes / excludes the right WHERE clauses based on
  introspection + force-bypass kwargs.
- AccountRepository.create stages a row with a UUIDv7 id and the given
  display_name.
- soft_delete builds the right UPDATE (mock execute returns rowcount).

Tenancy-filter behavior on tables that DO have account_id will be
exercised in B.2 when the user / session models land.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Account
from app.db.repositories.account_repo import AccountRepository
from app.db.repositories.base import BaseRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Mock AsyncSession. `add` is sync; `execute` and `flush` are async."""
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()  # session.add is sync in real SA
    return s


def _where_sql(stmt: object) -> str:
    """Return the lowercased WHERE clause text of a compiled SELECT (or '' if none).

    Avoids false positives from column names that legitimately appear in the
    SELECT column list (e.g. `account.parent_account_id`, `account.deleted_at`).
    Normalizes whitespace because compiled SQL contains newlines.
    """
    sql = " ".join(str(stmt.compile()).lower().split())
    if " where " not in sql:
        return ""
    return sql.split(" where ", 1)[1]


# --- Class structure


def test_account_repository_is_base_repository_subclass() -> None:
    assert issubclass(AccountRepository, BaseRepository)


def test_account_repository_model_class_is_account() -> None:
    assert AccountRepository.model_class is Account


# --- Column introspection


def test_account_repository_has_no_account_id_column(mock_session: AsyncMock) -> None:
    """Account is the tenancy root — no `account_id` column to filter on."""
    repo = AccountRepository(session=mock_session, account_id=None)
    assert repo._has_account_id_column is False


def test_account_repository_has_deleted_at_column(mock_session: AsyncMock) -> None:
    """Account has `deleted_at` per Lock §2.3 — soft-delete applies."""
    repo = AccountRepository(session=mock_session, account_id=None)
    assert repo._has_deleted_at_column is True


# --- _base_select WHERE clauses (compiled SQL inspection)


def test_base_select_skips_tenancy_filter_on_account(mock_session: AsyncMock) -> None:
    """No `account_id = ...` clause in the WHERE for the Account table."""
    repo = AccountRepository(session=mock_session, account_id=None)
    stmt = repo._base_select()
    where = _where_sql(stmt)
    # Account has no `account_id` column, so the tenancy clause is absent.
    # (parent_account_id IS in the SELECT column list but never in WHERE here.)
    assert "account_id" not in where


def test_base_select_applies_soft_delete_filter_on_account(
    mock_session: AsyncMock,
) -> None:
    """`deleted_at IS NULL` clause present in the WHERE by default."""
    repo = AccountRepository(session=mock_session, account_id=None)
    stmt = repo._base_select()
    where = _where_sql(stmt)
    assert "deleted_at is null" in where


def test_force_include_deleted_skips_soft_delete_filter(
    mock_session: AsyncMock,
) -> None:
    """force_include_deleted=True bypasses the WHERE soft-delete filter."""
    repo = AccountRepository(session=mock_session, account_id=None)
    stmt = repo._base_select(force_include_deleted=True)
    where = _where_sql(stmt)
    # Neither tenancy nor soft-delete filters → WHERE is empty.
    assert where == ""


# --- AccountRepository.create


async def test_create_assigns_uuidv7_id_and_stages_row(
    mock_session: AsyncMock,
) -> None:
    repo = AccountRepository(session=mock_session, account_id=None)

    acc = await repo.create("Test Account")

    assert isinstance(acc, Account)
    assert acc.display_name == "Test Account"
    assert isinstance(acc.id, UUID)
    assert acc.id.version == 7  # UUIDv7 per ADR-033
    assert acc.parent_account_id is None
    mock_session.add.assert_called_once_with(acc)


async def test_create_with_parent_account_id(mock_session: AsyncMock) -> None:
    """parent_account_id is set when supplied (future agency / white-label)."""
    repo = AccountRepository(session=mock_session, account_id=None)
    parent = uuid4()

    acc = await repo.create("Sub Account", parent_account_id=parent)

    assert acc.parent_account_id == parent


async def test_create_default_region_falls_through_to_db_default(
    mock_session: AsyncMock,
) -> None:
    """B.3.5: when `region` is not supplied, the repo does NOT pass the
    kwarg to the Account constructor — the model's `default='us'` and
    `server_default='us'` apply at flush time.

    On the unflushed instance the attribute is None (SQLAlchemy column
    defaults fire at flush, not at __init__), and the actual `'us'`
    value lands when the INSERT executes. We assert both that no
    region was staged AND that the column has the expected
    server_default declaration."""
    from app.db.models import Account

    repo = AccountRepository(session=mock_session, account_id=None)

    acc = await repo.create("Test")

    # Unflushed instance has no explicit region.
    assert acc.region is None
    # The column declares server_default='us' so Postgres backfills.
    assert "us" in str(Account.__table__.columns["region"].server_default.arg)


async def test_create_with_explicit_region(mock_session: AsyncMock) -> None:
    """B.3.5: caller can override the default per ADR-046's
    `{'us','ca','uk'}` allowlist."""
    repo = AccountRepository(session=mock_session, account_id=None)

    acc = await repo.create("UK Tenant", region="uk")

    assert acc.region == "uk"


# --- AccountRepository.find_by_status


async def test_find_by_status_delegates_to_find_many(mock_session: AsyncMock) -> None:
    """find_by_status is a thin wrapper around find_many(status=...)."""
    # Arrange: execute returns a result whose scalars().all() returns []
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = AccountRepository(session=mock_session, account_id=None)
    out = await repo.find_by_status("active")

    assert out == []
    # The single execute call carried a SELECT with the status filter
    assert mock_session.execute.await_count == 1
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = str(sent_stmt.compile()).lower()
    assert "status" in sql


# --- soft_delete on Account


async def test_soft_delete_builds_update_with_deleted_at_now(
    mock_session: AsyncMock,
) -> None:
    """soft_delete issues an UPDATE setting deleted_at = now() for the given id."""
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    repo = AccountRepository(session=mock_session, account_id=None)
    target_id = uuid4()
    deleted = await repo.soft_delete(target_id)

    assert deleted is True
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = str(sent_stmt.compile()).lower()
    assert "update" in sql
    assert "deleted_at" in sql
    assert "now()" in sql or "current_timestamp" in sql


async def test_soft_delete_returns_false_when_no_row_updated(
    mock_session: AsyncMock,
) -> None:
    """Idempotent: already-deleted (or non-existent) row returns False."""
    result = MagicMock()
    result.rowcount = 0
    mock_session.execute.return_value = result

    repo = AccountRepository(session=mock_session, account_id=None)
    deleted = await repo.soft_delete(uuid4())

    assert deleted is False


# --- BaseRepository.add


def test_add_delegates_to_session_add(mock_session: AsyncMock) -> None:
    repo = AccountRepository(session=mock_session, account_id=None)
    instance = Account(display_name="x")

    repo.add(instance)

    mock_session.add.assert_called_once_with(instance)
