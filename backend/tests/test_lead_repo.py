"""B.4.1 behavior tests for LeadRepository.

Mock-only (per phase-b4-plan.md §2 #11 — deterministic synthetic
data, no real DB integration). Mirrors the B.2.2 test_user_repo
pattern.

Asserts:
- Class structure (model_class, BaseRepository subclass).
- Tenancy + soft-delete filters BOTH active (Lead has both columns).
- _base_select raises when account_id=None (no force_cross_account
  use case for leads — leads are account-scoped).
- create() mints a UUIDv7 id, sets supplied fields, stages.
- find_by_email_hash + find_by_phone_hash + find_by_lifecycle_state
  issue the right SELECTs with tenancy + soft-delete filters.
- update_lifecycle_state builds an UPDATE with the right WHERE
  clauses + tenancy filter + soft-delete predicate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead
from app.db.repositories.base import BaseRepository
from app.db.repositories.lead_repo import LeadRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    return s


def _where_sql(stmt: object) -> str:
    """Return the lowercased WHERE clause text of a compiled SELECT
    (or '' if none). Normalizes whitespace."""
    sql = " ".join(str(stmt.compile()).lower().split())
    if " where " not in sql:
        return ""
    return sql.split(" where ", 1)[1]


# --- Class structure


def test_lead_repository_is_base_repository_subclass() -> None:
    assert issubclass(LeadRepository, BaseRepository)


def test_lead_repository_model_class_is_lead() -> None:
    assert LeadRepository.model_class is Lead


# --- Column introspection (BOTH filters active on Lead)


def test_lead_repository_has_account_id_column(mock_session: AsyncMock) -> None:
    """Lead has `account_id` -> tenancy filter active."""
    repo = LeadRepository(session=mock_session, account_id=uuid4())
    assert repo._has_account_id_column is True


def test_lead_repository_has_deleted_at_column(mock_session: AsyncMock) -> None:
    """Lead has `deleted_at` -> soft-delete filter active."""
    repo = LeadRepository(session=mock_session, account_id=uuid4())
    assert repo._has_deleted_at_column is True


# --- _base_select behavior


def test_base_select_applies_both_filters(mock_session: AsyncMock) -> None:
    """Tenancy AND soft-delete WHERE clauses present by default."""
    repo = LeadRepository(session=mock_session, account_id=uuid4())
    stmt = repo._base_select()
    where = _where_sql(stmt)
    assert "account_id" in where
    assert "deleted_at is null" in where


def test_base_select_raises_when_account_id_is_none(
    mock_session: AsyncMock,
) -> None:
    """Lead reads without an account_id are forbidden by default.

    Unlike User during magic-link consume, Lead has no
    system-context read path -- all lead operations are account-scoped.
    """
    repo = LeadRepository(session=mock_session, account_id=None)
    with pytest.raises(ValueError, match="requires account_id"):
        repo._base_select()


# --- create


async def test_create_assigns_uuidv7_id_and_stages(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    repo = LeadRepository(session=mock_session, account_id=account_id)

    lead = await repo.create(
        account_id=account_id,
        source="import_batch_001",
        vertical_id=None,
    )

    assert isinstance(lead, Lead)
    assert isinstance(lead.id, UUID) and lead.id.version == 7
    assert lead.account_id == account_id
    assert lead.source == "import_batch_001"
    assert lead.vertical_id is None
    # Defaults applied at Python-construction time (Mapped default='cold').
    assert lead.lifecycle_state == "cold"
    assert lead.consent_sms is False
    assert lead.consent_email is False
    # PII fields default to None.
    assert lead.email_hash is None
    assert lead.email_encrypted is None
    assert lead.phone_hash is None
    assert lead.phone_encrypted is None
    mock_session.add.assert_called_once_with(lead)


async def test_create_with_pii_fields(mock_session: AsyncMock) -> None:
    """PII bytea fields land on the staged instance when supplied."""
    account_id = uuid4()
    repo = LeadRepository(session=mock_session, account_id=account_id)

    lead = await repo.create(
        account_id=account_id,
        source="form_submission",
        email_hash=b"\xab" * 32,
        email_encrypted=b"\xcd" * 64,
        phone_hash=b"\xef" * 32,
        phone_encrypted=b"\x12" * 64,
        consent_sms=True,
        consent_email=True,
        consent_source="checkbox_v2",
    )

    assert lead.email_hash == b"\xab" * 32
    assert lead.email_encrypted == b"\xcd" * 64
    assert lead.phone_hash == b"\xef" * 32
    assert lead.phone_encrypted == b"\x12" * 64
    assert lead.consent_sms is True
    assert lead.consent_email is True
    assert lead.consent_source == "checkbox_v2"


async def test_create_with_explicit_lifecycle_state(
    mock_session: AsyncMock,
) -> None:
    """Non-default initial state allowed (import of already-engaged lead)."""
    account_id = uuid4()
    repo = LeadRepository(session=mock_session, account_id=account_id)

    lead = await repo.create(
        account_id=account_id,
        source="csv_import",
        lifecycle_state="engaged",
    )

    assert lead.lifecycle_state == "engaged"


async def test_create_with_vertical_id(mock_session: AsyncMock) -> None:
    """vertical_id FK passes through to the staged instance."""
    account_id = uuid4()
    vertical_id = uuid4()
    repo = LeadRepository(session=mock_session, account_id=account_id)

    lead = await repo.create(
        account_id=account_id,
        source="manual",
        vertical_id=vertical_id,
    )

    assert lead.vertical_id == vertical_id


# --- find_by_email_hash


async def test_find_by_email_hash_applies_tenancy_filter(
    mock_session: AsyncMock,
) -> None:
    """ACCOUNT-SCOPED lookup -- a lead with the same email_hash in a
    different account is a different lead."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = LeadRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_by_email_hash(b"\xab" * 32)

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    assert "email_hash" in where
    assert "account_id" in where  # tenancy filter active
    assert "deleted_at is null" in where  # soft-delete filter active


# --- find_by_phone_hash


async def test_find_by_phone_hash_applies_tenancy_filter(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = LeadRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_by_phone_hash(b"\xef" * 32)

    assert out is None
    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    assert "phone_hash" in where
    assert "account_id" in where
    assert "deleted_at is null" in where


# --- find_by_lifecycle_state


async def test_find_by_lifecycle_state_filters_correctly(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = result

    repo = LeadRepository(session=mock_session, account_id=uuid4())
    out = await repo.find_by_lifecycle_state("qualified")

    assert out == []
    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    assert "lifecycle_state" in where
    assert "account_id" in where
    assert "deleted_at is null" in where


# --- update_lifecycle_state


async def test_update_lifecycle_state_builds_correct_update(
    mock_session: AsyncMock,
) -> None:
    account_id = uuid4()
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    repo = LeadRepository(session=mock_session, account_id=account_id)
    target_id = uuid4()
    updated = await repo.update_lifecycle_state(target_id, "warm")

    assert updated is True
    sent_stmt = mock_session.execute.await_args.args[0]
    sql = " ".join(str(sent_stmt.compile()).lower().split())
    assert "update" in sql and "lead" in sql
    assert "lifecycle_state" in sql
    # Tenancy + soft-delete WHERE clauses applied.
    assert "account_id" in sql
    assert "deleted_at is null" in sql
    # updated_at is also bumped.
    assert "updated_at" in sql


async def test_update_lifecycle_state_returns_false_when_no_row_updated(
    mock_session: AsyncMock,
) -> None:
    """Idempotent: a missing lead or one in another tenant returns False."""
    result = MagicMock()
    result.rowcount = 0
    mock_session.execute.return_value = result

    repo = LeadRepository(session=mock_session, account_id=uuid4())
    updated = await repo.update_lifecycle_state(uuid4(), "warm")

    assert updated is False


# --- inherited soft_delete


async def test_inherited_soft_delete_on_lead(
    mock_session: AsyncMock,
) -> None:
    """BaseRepository.soft_delete works because Lead has deleted_at."""
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    repo = LeadRepository(session=mock_session, account_id=uuid4())
    deleted = await repo.soft_delete(uuid4())

    assert deleted is True
