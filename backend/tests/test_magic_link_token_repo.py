"""B.2.2 tests for MagicLinkTokenRepository.

Mock-only. Verifies:
- Tenancy filter NOT active (MagicLinkToken has no account_id).
- Soft-delete filter NOT active (no deleted_at; uses consumed_at).
- create() mints a UUIDv7 id and stages a row with the supplied fields.
- find_active_by_token_hash filters by consumed_at IS NULL.
- mark_consumed builds the right UPDATE with consumed_at = now() and is
  idempotent on already-consumed tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MagicLinkToken
from app.db.repositories.base import BaseRepository
from app.db.repositories.magic_link_token_repo import MagicLinkTokenRepository


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


def test_repo_is_base_repository_subclass() -> None:
    assert issubclass(MagicLinkTokenRepository, BaseRepository)


def test_repo_model_class_is_magic_link_token() -> None:
    assert MagicLinkTokenRepository.model_class is MagicLinkToken


# --- Column introspection


def test_repo_has_no_account_id_column(mock_session: AsyncMock) -> None:
    """MagicLinkToken is intentionally pre-account; no tenancy filter."""
    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    assert repo._has_account_id_column is False


def test_repo_has_no_deleted_at_column(mock_session: AsyncMock) -> None:
    """Uses consumed_at; base soft-delete filter inert."""
    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    assert repo._has_deleted_at_column is False


# --- _base_select WHERE clauses


def test_base_select_no_filters_on_magic_link_token(
    mock_session: AsyncMock,
) -> None:
    """Neither tenancy nor soft-delete filter applies; WHERE is empty."""
    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    stmt = repo._base_select()
    where = _where_sql(stmt)
    assert where == ""


# --- create


async def test_create_assigns_uuidv7_id_and_stages_row(
    mock_session: AsyncMock,
) -> None:
    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    issued = datetime.now(timezone.utc)
    expires = issued + timedelta(minutes=15)

    token = await repo.create(
        email_hash=b"\xe1" * 32,
        token_hash=b"\xe2" * 32,
        issued_at=issued,
        expires_at=expires,
        ip_hash=b"\xe3" * 32,
    )

    assert isinstance(token, MagicLinkToken)
    assert isinstance(token.id, UUID)
    assert token.id.version == 7
    assert token.email_hash == b"\xe1" * 32
    assert token.token_hash == b"\xe2" * 32
    assert token.issued_at == issued
    assert token.expires_at == expires
    assert token.ip_hash == b"\xe3" * 32
    assert token.consumed_at is None
    mock_session.add.assert_called_once_with(token)


async def test_create_handles_none_ip_hash(mock_session: AsyncMock) -> None:
    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    issued = datetime.now(timezone.utc)

    token = await repo.create(
        email_hash=b"x" * 32,
        token_hash=b"y" * 32,
        issued_at=issued,
        expires_at=issued + timedelta(minutes=15),
        ip_hash=None,
    )

    assert token.ip_hash is None


# --- find_active_by_token_hash


async def test_find_active_by_token_hash_filters_consumed_at_is_null(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)

    out = await repo.find_active_by_token_hash(b"\xab" * 32)

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    assert "token_hash" in where
    assert "consumed_at is null" in where


# --- mark_consumed


async def test_mark_consumed_builds_update_with_consumed_at_now(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    target_id = uuid4()

    consumed = await repo.mark_consumed(target_id)

    assert consumed is True
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "update" in sql and "magic_link_token" in sql
    assert "consumed_at" in sql
    assert "now()" in sql or "current_timestamp" in sql


async def test_mark_consumed_returns_false_when_already_consumed(
    mock_session: AsyncMock,
) -> None:
    """Idempotent: re-consuming a consumed token returns False."""
    result = MagicMock()
    result.rowcount = 0
    mock_session.execute.return_value = result

    repo = MagicLinkTokenRepository(session=mock_session, account_id=None)
    consumed = await repo.mark_consumed(uuid4())

    assert consumed is False
