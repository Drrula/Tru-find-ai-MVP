"""B.2.2 tests for SessionRepository.

Mock-only. Verifies:
- Tenancy filter active (UserSession has account_id).
- Soft-delete filter NOT active (UserSession has no deleted_at).
- create() denormalizes account_id from the user.
- create() truncates user_agent to 256 chars.
- revoke() builds the right UPDATE with revoked_at = now() and the
  tenancy WHERE clause.
- BaseRepository.soft_delete raises NotImplementedError on UserSession
  (no deleted_at column — explicit revoke semantics instead).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserSession
from app.db.repositories.base import BaseRepository
from app.db.repositories.session_repo import SessionRepository


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


def _make_user(account_id: UUID | None = None) -> User:
    """Build an unpersisted User for create() tests.

    Direct construction (not via repo.create) is fine here — we're not
    exercising UserRepository, just providing a stand-in for the FK.
    """
    return User(
        id=uuid4(),
        account_id=account_id or uuid4(),
        email_hash=b"\x00" * 32,
        email_encrypted=b"\x01" * 64,
    )


# --- Class structure


def test_session_repository_is_base_repository_subclass() -> None:
    assert issubclass(SessionRepository, BaseRepository)


def test_session_repository_model_class_is_user_session() -> None:
    assert SessionRepository.model_class is UserSession


# --- Column introspection


def test_session_repository_has_account_id_column(
    mock_session: AsyncMock,
) -> None:
    """UserSession has account_id (denormalized) -> tenancy filter active."""
    repo = SessionRepository(session=mock_session, account_id=uuid4())
    assert repo._has_account_id_column is True


def test_session_repository_has_no_deleted_at_column(
    mock_session: AsyncMock,
) -> None:
    """UserSession uses revoked_at instead -> base soft-delete filter inert."""
    repo = SessionRepository(session=mock_session, account_id=uuid4())
    assert repo._has_deleted_at_column is False


# --- _base_select WHERE clauses


def test_base_select_applies_tenancy_filter_no_soft_delete(
    mock_session: AsyncMock,
) -> None:
    repo = SessionRepository(session=mock_session, account_id=uuid4())
    stmt = repo._base_select()
    where = _where_sql(stmt)
    assert "account_id" in where
    # No deleted_at clause (column doesn't exist).
    assert "deleted_at" not in where


# --- SessionRepository.create


async def test_create_denormalizes_account_id_from_user(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    user = _make_user(account_id=account_id)
    repo = SessionRepository(session=mock_session, account_id=account_id)
    issued = datetime.now(timezone.utc)
    expires = issued + timedelta(days=30)

    sess = await repo.create(
        user=user,
        issued_at=issued,
        expires_at=expires,
        ip_hash=b"\x99" * 32,
        user_agent="Mozilla/5.0",
    )

    assert isinstance(sess, UserSession)
    assert isinstance(sess.id, UUID)
    assert sess.id.version == 7
    assert sess.user_id == user.id
    assert sess.account_id == user.account_id  # denormalized
    assert sess.issued_at == issued
    assert sess.expires_at == expires
    assert sess.ip_hash == b"\x99" * 32
    assert sess.user_agent == "Mozilla/5.0"
    assert sess.revoked_at is None
    mock_session.add.assert_called_once_with(sess)


async def test_create_truncates_long_user_agent(mock_session: AsyncMock) -> None:
    account_id = uuid4()
    user = _make_user(account_id=account_id)
    repo = SessionRepository(session=mock_session, account_id=account_id)
    issued = datetime.now(timezone.utc)

    long_ua = "x" * 1000
    sess = await repo.create(
        user=user,
        issued_at=issued,
        expires_at=issued + timedelta(days=30),
        user_agent=long_ua,
    )

    assert sess.user_agent is not None
    assert len(sess.user_agent) == 256


async def test_create_handles_none_user_agent(mock_session: AsyncMock) -> None:
    account_id = uuid4()
    user = _make_user(account_id=account_id)
    repo = SessionRepository(session=mock_session, account_id=account_id)
    issued = datetime.now(timezone.utc)

    sess = await repo.create(
        user=user,
        issued_at=issued,
        expires_at=issued + timedelta(days=30),
        user_agent=None,
    )

    assert sess.user_agent is None


# --- SessionRepository.revoke


async def test_revoke_builds_update_with_revoked_at_now_and_tenancy(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    repo = SessionRepository(session=mock_session, account_id=account_id)
    target_id = uuid4()
    revoked = await repo.revoke(target_id)

    assert revoked is True
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "update" in sql and "session" in sql
    assert "revoked_at" in sql
    assert "now()" in sql or "current_timestamp" in sql
    # Tenancy WHERE applied.
    assert "account_id" in sql


async def test_revoke_returns_false_when_no_row_updated(
    mock_session: AsyncMock,
) -> None:
    """Idempotent: already-revoked or missing session returns False."""
    result = MagicMock()
    result.rowcount = 0
    mock_session.execute.return_value = result

    repo = SessionRepository(session=mock_session, account_id=uuid4())
    revoked = await repo.revoke(uuid4())

    assert revoked is False


# --- BaseRepository.soft_delete on UserSession


async def test_base_soft_delete_raises_for_session_no_deleted_at(
    mock_session: AsyncMock,
) -> None:
    """UserSession has no deleted_at; base soft_delete must refuse to operate
    rather than silently no-op."""
    repo = SessionRepository(session=mock_session, account_id=uuid4())

    with pytest.raises(NotImplementedError, match="deleted_at"):
        await repo.soft_delete(uuid4())
