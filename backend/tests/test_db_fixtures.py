"""B.6A.5 self-tests for the real-DB fixtures.

Verifies the conftest additions work end-to-end:
  - alembic upgrade ran to head
  - db_engine yields a working AsyncEngine
  - db_session executes real SQL
  - migration 0020's seed rows are queryable by their deterministic
    UUID5 identities
  - nested-SAVEPOINT rollback isolates state across tests

REQUIRES: Postgres reachable at Settings.database_url (dev default:
docker-compose at localhost:5432/trufindai). The mock-only suite
runs without these fixtures; this file is the only place that opens
a real connection in B.6A.5.

Per docs/phase-b6a-plan.md §6 (B.6A.5 sub-phase row).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_MIGRATION_PATH = (
    _REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "0020_seed_demo_account_vertical_catalog.py"
)


def _load_seed_module():
    """Load migration 0020 as a module so the tests can reach its
    DEMO_ACCOUNT_ID / DEMO_VERTICAL_ID constants."""
    spec = importlib.util.spec_from_file_location(
        "alembic_0020_seed_for_tests", _SEED_MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SEED = _load_seed_module()
DEMO_ACCOUNT_ID: UUID = _SEED.DEMO_ACCOUNT_ID
DEMO_VERTICAL_ID: UUID = _SEED.DEMO_VERTICAL_ID


# ---------------------------------------------------------------------------
# Engine + session shapes
# ---------------------------------------------------------------------------


def test_db_engine_is_async_engine(db_engine: AsyncEngine) -> None:
    assert isinstance(db_engine, AsyncEngine)


def test_db_engine_targets_postgresql_asyncpg(db_engine: AsyncEngine) -> None:
    """Confirms the engine is wired to the runtime DB (not a mocked /
    in-memory shim). Per ADR-002."""
    assert db_engine.url.drivername == "postgresql+asyncpg"


async def test_db_session_executes_real_sql(
    db_session: AsyncSession,
) -> None:
    """SELECT 1 round-trips through Postgres."""
    result = await db_session.execute(text("SELECT 1 AS one"))
    row = result.one()
    assert row.one == 1


# ---------------------------------------------------------------------------
# Migration upgrade verification
# ---------------------------------------------------------------------------


async def test_alembic_version_is_at_head(
    db_session: AsyncSession,
) -> None:
    """After conftest's `_apply_migrations` runs, the
    `alembic_version` table must hold the head revision (which is
    0020 at B.6A.5)."""
    result = await db_session.execute(
        text("SELECT version_num FROM alembic_version")
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0] == "0020_seed_demo_account_vertical_catalog"


# ---------------------------------------------------------------------------
# Migration 0020 seed row presence
# ---------------------------------------------------------------------------


async def test_demo_account_row_present(
    db_session: AsyncSession,
) -> None:
    """The deterministic UUID5 demo account exists after the seed
    migration runs. Queried by its specific id, not a count, so the
    test is robust against other dev-DB rows."""
    result = await db_session.execute(
        text("SELECT display_name FROM account WHERE id = :id"),
        {"id": str(DEMO_ACCOUNT_ID)},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.display_name == "demo"


async def test_demo_vertical_row_present(
    db_session: AsyncSession,
) -> None:
    result = await db_session.execute(
        text(
            "SELECT pack_id, display_name, schema_version "
            "FROM vertical WHERE id = :id"
        ),
        {"id": str(DEMO_VERTICAL_ID)},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.pack_id == "local_business_ai_visibility"
    assert row.display_name == "Local Business AI Visibility"
    assert row.schema_version == 1


async def test_four_lead_signal_definitions_seeded(
    db_session: AsyncSession,
) -> None:
    result = await db_session.execute(
        text(
            "SELECT name FROM lead_signal_definition "
            "WHERE name = ANY(:names) ORDER BY name"
        ),
        {
            "names": [
                "content_signals",
                "google_business_presence",
                "reviews",
                "website_presence",
            ]
        },
    )
    names = [r.name for r in result.all()]
    assert names == [
        "content_signals",
        "google_business_presence",
        "reviews",
        "website_presence",
    ]


async def test_four_vertical_lead_signal_weights_seeded(
    db_session: AsyncSession,
) -> None:
    """All 4 weights present for the demo vertical, dimension =
    'lead_quality', summing to 1.000 (matches pack WEIGHTS)."""
    result = await db_session.execute(
        text(
            "SELECT signal_name, weight FROM vertical_lead_signal_weight "
            "WHERE vertical_id = :vid AND dimension = 'lead_quality' "
            "AND effective_to IS NULL "
            "ORDER BY signal_name"
        ),
        {"vid": str(DEMO_VERTICAL_ID)},
    )
    rows = [(r.signal_name, float(r.weight)) for r in result.all()]
    by_name = dict(rows)
    assert by_name == {
        "content_signals": 0.200,
        "google_business_presence": 0.300,
        "reviews": 0.200,
        "website_presence": 0.300,
    }
    assert sum(by_name.values()) == 1.0


# ---------------------------------------------------------------------------
# Rollback isolation
# ---------------------------------------------------------------------------
#
# These two tests rely on declaration order (pytest runs tests in the
# order they appear in the file). Test 1 inserts + commits a row;
# test 2 asserts the row is gone. The nested-SAVEPOINT pattern in the
# fixture rolls back the OUTER transaction at teardown, so even an
# explicit session.commit() in test 1 does not durably persist.


_ROLLBACK_TEST_ACCOUNT_ID: UUID = uuid4()


async def test_rollback_step_1_insert_commits_within_session(
    db_session: AsyncSession,
) -> None:
    """Insert + commit a row; assert it's visible in this session
    AFTER the commit. The fixture teardown will roll it back."""
    await db_session.execute(
        text(
            "INSERT INTO account (id, display_name, status, region) "
            "VALUES (:id, 'rollback-isolation-test', 'active', 'us')"
        ),
        {"id": str(_ROLLBACK_TEST_ACCOUNT_ID)},
    )
    await db_session.commit()

    # Visible inside the same session post-commit (savepoint
    # restarted automatically).
    result = await db_session.execute(
        text("SELECT count(*) AS c FROM account WHERE id = :id"),
        {"id": str(_ROLLBACK_TEST_ACCOUNT_ID)},
    )
    assert result.one().c == 1


async def test_rollback_step_2_step_1_row_no_longer_visible(
    db_session: AsyncSession,
) -> None:
    """Fresh db_session in a new outer transaction. The row inserted
    + committed in step 1 was rolled back at step 1's fixture
    teardown. This test sees zero rows for that UUID -- the proof of
    cross-test rollback isolation."""
    result = await db_session.execute(
        text("SELECT count(*) AS c FROM account WHERE id = :id"),
        {"id": str(_ROLLBACK_TEST_ACCOUNT_ID)},
    )
    assert result.one().c == 0
