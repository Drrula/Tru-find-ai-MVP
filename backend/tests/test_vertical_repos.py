"""B.3.3 tests for the five vertical_* repositories.

Mock-only. Verifies:
- Each repo subclasses BaseRepository with the right model_class.
- All five are platform-owned (no account_id column -> tenancy filter
  inert).
- _base_select issues no tenancy WHERE clause.
- create() mints a UUIDv7 id and stages the row with the supplied
  fields.
- VerticalRepository.find_by_pack_id issues a SELECT keyed on pack_id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Vertical,
    VerticalCopy,
    VerticalPromptVersion,
    VerticalSignalWeight,
    VerticalTemplate,
)
from app.db.repositories.base import BaseRepository
from app.db.repositories.vertical_copy_repo import VerticalCopyRepository
from app.db.repositories.vertical_prompt_version_repo import (
    VerticalPromptVersionRepository,
)
from app.db.repositories.vertical_repo import VerticalRepository
from app.db.repositories.vertical_signal_weight_repo import (
    VerticalSignalWeightRepository,
)
from app.db.repositories.vertical_template_repo import VerticalTemplateRepository


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


# --- Class structure (all five at once)


@pytest.mark.parametrize(
    "repo_cls, model_cls",
    [
        (VerticalRepository, Vertical),
        (VerticalSignalWeightRepository, VerticalSignalWeight),
        (VerticalCopyRepository, VerticalCopy),
        (VerticalTemplateRepository, VerticalTemplate),
        (VerticalPromptVersionRepository, VerticalPromptVersion),
    ],
)
def test_repo_subclass_and_model_class(repo_cls, model_cls) -> None:
    assert issubclass(repo_cls, BaseRepository)
    assert repo_cls.model_class is model_cls


# --- All platform-owned: no tenancy filter


@pytest.mark.parametrize(
    "repo_cls",
    [
        VerticalRepository,
        VerticalSignalWeightRepository,
        VerticalCopyRepository,
        VerticalTemplateRepository,
        VerticalPromptVersionRepository,
    ],
)
def test_repo_has_no_account_id_column(repo_cls, mock_session: AsyncMock) -> None:
    """All five vertical_* models are platform-owned (per ADR-047) — no
    account_id column means the BaseRepository tenancy filter never
    fires for these repos."""
    repo = repo_cls(session=mock_session, account_id=None)
    assert repo._has_account_id_column is False


@pytest.mark.parametrize(
    "repo_cls",
    [
        VerticalRepository,
        VerticalSignalWeightRepository,
        VerticalCopyRepository,
        VerticalTemplateRepository,
        VerticalPromptVersionRepository,
    ],
)
def test_base_select_no_filters_for_platform_owned(
    repo_cls, mock_session: AsyncMock
) -> None:
    repo = repo_cls(session=mock_session, account_id=None)
    stmt = repo._base_select()
    where = _where_sql(stmt)
    assert where == ""


# --- VerticalRepository.create + find_by_pack_id


async def test_vertical_create_assigns_uuidv7_id_and_stages(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalRepository(session=mock_session, account_id=None)
    v = await repo.create(
        pack_id="local_business_ai_visibility",
        display_name="Local Business AI Visibility",
        schema_version=1,
    )
    assert isinstance(v, Vertical)
    assert isinstance(v.id, UUID) and v.id.version == 7
    assert v.pack_id == "local_business_ai_visibility"
    assert v.display_name == "Local Business AI Visibility"
    assert v.schema_version == 1
    mock_session.add.assert_called_once_with(v)


async def test_vertical_find_by_pack_id_filters_on_pack_id(
    mock_session: AsyncMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    repo = VerticalRepository(session=mock_session, account_id=None)
    out = await repo.find_by_pack_id("does_not_exist")
    assert out is None

    sent_stmt = mock_session.execute.await_args.args[0]
    where = _where_sql(sent_stmt)
    assert "pack_id" in where


# --- VerticalSignalWeightRepository.create


async def test_weight_create_stages_with_decimal_weight(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalSignalWeightRepository(session=mock_session, account_id=None)
    vid = uuid4()
    row = await repo.create(
        vertical_id=vid,
        signal_name="website_presence",
        weight=0.30,
    )
    assert isinstance(row, VerticalSignalWeight)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.vertical_id == vid
    assert row.signal_name == "website_presence"
    assert row.weight == Decimal("0.3")
    mock_session.add.assert_called_once_with(row)


async def test_weight_create_uses_db_default_effective_from_when_none(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalSignalWeightRepository(session=mock_session, account_id=None)
    row = await repo.create(
        vertical_id=uuid4(),
        signal_name="reviews",
        weight=Decimal("0.2"),
    )
    # When effective_from is None, the kwarg is omitted -> model gets the
    # server-side default (now()) at flush. The Python attribute is None
    # on the unflushed instance, which is correct.
    assert row.effective_from is None


async def test_weight_create_accepts_explicit_effective_from(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalSignalWeightRepository(session=mock_session, account_id=None)
    when = datetime(2026, 5, 10, tzinfo=timezone.utc)
    row = await repo.create(
        vertical_id=uuid4(),
        signal_name="reviews",
        weight=0.2,
        effective_from=when,
    )
    assert row.effective_from == when


# --- VerticalCopyRepository.create


async def test_copy_create_stages(mock_session: AsyncMock) -> None:
    repo = VerticalCopyRepository(session=mock_session, account_id=None)
    vid = uuid4()
    row = await repo.create(
        vertical_id=vid,
        locale="en-US",
        key="gap.no_website",
        text="No website detected.",
    )
    assert isinstance(row, VerticalCopy)
    assert isinstance(row.id, UUID) and row.id.version == 7
    assert row.vertical_id == vid
    assert row.locale == "en-US"
    assert row.key == "gap.no_website"
    assert row.text == "No website detected."
    mock_session.add.assert_called_once_with(row)


# --- VerticalTemplateRepository.create


async def test_template_create_stages_with_jsonb_config(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalTemplateRepository(session=mock_session, account_id=None)
    vid = uuid4()
    config = {"tiers": [[80, "strong"], [50, "moderate"], [0, "weak"]]}
    row = await repo.create(
        vertical_id=vid,
        name="tier_thresholds",
        config_json=config,
    )
    assert isinstance(row, VerticalTemplate)
    assert row.vertical_id == vid
    assert row.name == "tier_thresholds"
    assert row.config_json == config
    mock_session.add.assert_called_once_with(row)


# --- VerticalPromptVersionRepository.create


async def test_prompt_version_create_stages_with_default_status_draft(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalPromptVersionRepository(session=mock_session, account_id=None)
    row = await repo.create(
        vertical_id=uuid4(),
        prompt_key="summary",
        version=1,
        prompt_text="Summarize this business.",
    )
    assert row.status == "draft"


async def test_prompt_version_create_accepts_active_status(
    mock_session: AsyncMock,
) -> None:
    repo = VerticalPromptVersionRepository(session=mock_session, account_id=None)
    row = await repo.create(
        vertical_id=uuid4(),
        prompt_key="summary",
        version=2,
        prompt_text="...",
        status="active",
    )
    assert row.status == "active"
