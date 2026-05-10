"""B.2.2 tests for UserRepository.

Mock-only (no real DB). Verifies:
- Class structure (model_class, BaseRepository subclass).
- Column introspection: User HAS account_id -> tenancy filter ACTIVE
  (this is the FIRST repo where the BaseRepository tenancy filter
  actually fires).
- _base_select includes the tenancy WHERE for User.
- Constructor with account_id=None raises at first read.
- find_by_email_hash uses force_cross_account=True (system-context
  lookup during magic-link consume).
- create() mints a UUIDv7 id, sets the supplied account_id, stages.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.repositories.base import BaseRepository
from app.db.repositories.user_repo import UserRepository


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


# --- Class structure


def test_user_repository_is_base_repository_subclass() -> None:
    assert issubclass(UserRepository, BaseRepository)


def test_user_repository_model_class_is_user() -> None:
    assert UserRepository.model_class is User


# --- Column introspection (tenancy + soft-delete BOTH active for User)


def test_user_repository_has_account_id_column(mock_session: AsyncMock) -> None:
    """User has `account_id` -> tenancy filter is active for this repo.

    This is the FIRST repo where _has_account_id_column is True.
    """
    repo = UserRepository(session=mock_session, account_id=uuid4())
    assert repo._has_account_id_column is True


def test_user_repository_has_deleted_at_column(mock_session: AsyncMock) -> None:
    repo = UserRepository(session=mock_session, account_id=uuid4())
    assert repo._has_deleted_at_column is True


# --- _base_select WHERE clauses


def test_base_select_applies_tenancy_filter_on_user(
    mock_session: AsyncMock,
) -> None:
    """`account_id = ...` clause present in WHERE for User reads."""
    account_id = uuid4()
    repo = UserRepository(session=mock_session, account_id=account_id)
    stmt = repo._base_select()
    where = _where_sql(stmt)
    assert "account_id" in where
    assert "deleted_at is null" in where


def test_base_select_raises_when_account_id_is_none(
    mock_session: AsyncMock,
) -> None:
    """User reads without an account_id are forbidden by default."""
    repo = UserRepository(session=mock_session, account_id=None)
    with pytest.raises(ValueError, match="requires account_id"):
        repo._base_select()


def test_force_cross_account_skips_tenancy_filter_on_user(
    mock_session: AsyncMock,
) -> None:
    """force_cross_account=True is the documented escape hatch (audited bypass).

    Used by find_by_email_hash during magic-link consume.
    """
    repo = UserRepository(session=mock_session, account_id=None)
    stmt = repo._base_select(force_cross_account=True)
    where = _where_sql(stmt)
    # Tenancy clause is gone; soft-delete clause remains.
    assert "account_id" not in where
    assert "deleted_at is null" in where


# --- UserRepository.create


async def test_create_assigns_uuidv7_id_and_account_id_and_stages(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    repo = UserRepository(session=mock_session, account_id=account_id)

    user = await repo.create(
        account_id=account_id,
        email_hash=b"\x01" * 32,
        email_encrypted=b"\x02" * 64,
        display_name="Alice",
    )

    assert isinstance(user, User)
    assert isinstance(user.id, UUID)
    assert user.id.version == 7
    assert user.account_id == account_id
    assert user.email_hash == b"\x01" * 32
    assert user.email_encrypted == b"\x02" * 64
    assert user.display_name == "Alice"
    assert user.role == "owner"  # default per Lock §2.3
    mock_session.add.assert_called_once_with(user)


async def test_create_accepts_explicit_role(mock_session: AsyncMock) -> None:
    account_id = uuid4()
    repo = UserRepository(session=mock_session, account_id=account_id)

    user = await repo.create(
        account_id=account_id,
        email_hash=b"x" * 32,
        email_encrypted=b"y" * 64,
        role="admin",
    )

    assert user.role == "admin"


# --- UserRepository.find_by_email_hash


async def test_find_by_email_hash_uses_force_cross_account(
    mock_session: AsyncMock,
) -> None:
    """Lookup must work without an account context; the issued SELECT
    omits the tenancy WHERE clause."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = UserRepository(session=mock_session, account_id=None)  # no tenant

    out = await repo.find_by_email_hash(b"\x01" * 32)

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    # Tenancy clause must be ABSENT; lookup is system-context.
    assert "account_id" not in where
    # Soft-delete clause MUST still apply (the partial unique index is
    # also gated on deleted_at IS NULL).
    assert "deleted_at is null" in where
    # The email_hash filter is in the WHERE.
    assert "email_hash" in where
