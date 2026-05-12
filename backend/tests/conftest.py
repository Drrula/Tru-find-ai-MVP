"""Shared pytest fixtures.

Per A.9. New tests should prefer these fixtures over inline setup; the
existing per-test inline setup (in test_core_*.py) stays as-is to avoid
churn — refactor opportunistically as those files are touched for other
reasons.

B.6A.5 added real-DB fixtures (`db_engine`, `db_session`) for tests
that exercise persistence end-to-end. They are OPT-IN: only tests
that request them open a Postgres connection. The existing mock-only
suite is unaffected.

Real-DB fixture contract:
  - Requires Postgres reachable at Settings.database_url
    (dev default: localhost:5432/trufindai via docker-compose).
  - Runs `alembic upgrade head` once per test session (idempotent).
  - Each test wraps its work in a nested SAVEPOINT; the outer
    transaction rolls back at teardown -- cross-test state never
    bleeds, even if the test calls session.commit().
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


_BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    """FastAPI TestClient with the production middleware stack.

    Skips if `httpx` (TestClient's transport) isn't installed — should
    always be present in CI via backend[dev].
    """
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture
def recording_publisher() -> Iterator:
    """A RecordingEventPublisher set as the active publisher; restored after.

    Use to assert that a code path emitted specific events. Yields the
    publisher so tests can inspect its `.events` list directly.
    """
    from app.core.events import (
        RecordingEventPublisher,
        get_publisher,
        reset_publisher,
        set_publisher,
    )

    original = get_publisher()
    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        yield rec
    finally:
        reset_publisher()
        if original is not None:
            set_publisher(original)


@pytest.fixture
def clear_contextvars() -> Iterator[None]:
    """Reset structlog contextvars before AND after the test.

    Use in tests that bind request_id (or other context) to avoid bleed
    between tests via the contextvars store.
    """
    import structlog

    structlog.contextvars.clear_contextvars()
    try:
        yield
    finally:
        structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# B.6A.5: real-DB fixtures (opt-in)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _apply_migrations() -> None:
    """Session-scoped one-shot: run `alembic upgrade head` against
    the DATABASE_URL the app uses (Settings.database_url; dev default
    is the docker-compose Postgres at localhost:5432/trufindai).

    Idempotent -- if the DB is already at head, alembic no-ops.

    NOT autouse: only fires when a fixture depends on it. The 686
    mock-only tests do not request `db_engine` / `db_session` and
    therefore never open a Postgres connection.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    # Resolve script_location to an absolute path so alembic works
    # regardless of where pytest is invoked from.
    cfg.set_main_option(
        "script_location", str(_BACKEND_ROOT / "alembic")
    )
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def db_engine(_apply_migrations) -> AsyncEngine:
    """Session-scoped AsyncEngine -- the singleton from
    `app.db.engine.get_engine()`. Migrations are guaranteed to have
    run to head (idempotent) before this fixture yields.

    Returned engine is reused across all tests in the session. No
    teardown -- the runtime engine's connection pool gets disposed
    by Python at interpreter exit; explicit dispose during pytest
    teardown is unnecessary for our test scale.
    """
    from app.db.engine import get_engine

    return get_engine()


@pytest_asyncio.fixture
async def db_session(
    db_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Per-test transactional session with nested-SAVEPOINT rollback.

    Pattern: open an outer transaction, start a nested savepoint,
    listen for savepoint release and recreate it. At test teardown,
    roll back the OUTER transaction -- everything the test
    committed inside is discarded. Cross-test state bleed is
    structurally impossible.

    The `after_transaction_end` listener restarts the savepoint
    after each `session.commit()` so the test's code-under-test can
    use commit() naturally; the outer-rollback at teardown ensures
    no actual durability across tests.

    Standard SQLAlchemy + asyncio savepoint pattern; see SQLA docs
    "Joining a Session into an External Transaction".
    """
    async with db_engine.connect() as connection:
        outer_transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
        )
        await connection.begin_nested()

        @event.listens_for(
            session.sync_session, "after_transaction_end"
        )
        def _restart_savepoint(sess, trans):  # noqa: ARG001
            if trans.nested and not trans._parent.nested:
                connection.sync_connection.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await outer_transaction.rollback()
