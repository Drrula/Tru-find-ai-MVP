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


@pytest_asyncio.fixture
async def db_engine(_apply_migrations) -> AsyncIterator[AsyncEngine]:
    """Function-scoped AsyncEngine with NullPool. Fresh engine per
    test so pooled connections never get tied to a dead event loop
    (pytest-asyncio creates a new loop per function-scoped test;
    asyncpg sockets bound to a previous loop raise RuntimeError on
    ping when checked out by the next test).

    Distinct from the runtime singleton at `app.db.engine.get_engine()`
    -- tests must NOT share the production engine because the
    production pool's connection-reuse strategy conflicts with the
    per-test loop semantics. NullPool means every `engine.connect()`
    opens a brand-new asyncpg connection bound to the current loop
    and closes it on context exit.

    `_apply_migrations` is session-scoped, so the migration upgrade
    runs exactly once at session start; this engine fixture pays
    only the per-test cost of opening one fresh connection.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    settings = get_settings()
    assert settings.database_url is not None
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator:
    """httpx.AsyncClient bound to the FastAPI app via ASGITransport.

    Async-native -- runs the entire ASGI lifecycle (including
    BackgroundTasks) inside the calling test's event loop, so
    asyncpg connections stay loop-bound. Use this for B.6B.3
    HTTP integration tests instead of the sync TestClient, which
    spawns its own AnyIO portal and corrupts loop binding.
    """
    pytest.importorskip("httpx")
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


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
    no actual durability across tests. The listener is removed at
    teardown so it doesn't accumulate across tests.

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

        def _restart_savepoint(sess, trans):  # noqa: ARG001
            if trans.nested and not trans._parent.nested:
                connection.sync_connection.begin_nested()

        event.listen(
            session.sync_session,
            "after_transaction_end",
            _restart_savepoint,
        )

        try:
            yield session
        finally:
            event.remove(
                session.sync_session,
                "after_transaction_end",
                _restart_savepoint,
            )
            await session.close()
            await outer_transaction.rollback()


# ---------------------------------------------------------------------------
# B.6B.3: shadow-path fixtures (opt-in)
# ---------------------------------------------------------------------------


@pytest.fixture
def b6b_flag_on(monkeypatch):
    """Patch `bridge_shadow.get_settings` so the shadow flag reads
    True for this test. Mirrors the pattern from
    test_bridge_shadow.py but at the conftest level so HTTP route
    tests can opt in by listing the fixture."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.domain.bridge_shadow.get_settings",
        lambda: SimpleNamespace(b6b_shadow_scoring_enabled=True),
    )


@pytest.fixture
def b6b_flag_off(monkeypatch):
    """Explicit OFF override (also the default in every env).
    Listing this fixture documents the test's flag assumption."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.domain.bridge_shadow.get_settings",
        lambda: SimpleNamespace(b6b_shadow_scoring_enabled=False),
    )


@pytest.fixture
def shadow_orchestrator_mock(monkeypatch):
    """Patch `analyze_and_persist` at the bridge_shadow import path.

    Returns the AsyncMock so route-level tests can configure
    side_effect / return_value and assert call shapes. Mocking at
    the orchestrator boundary keeps route tests isolated from
    the B.6A.4 implementation (which is exhaustively tested in
    test_analyze_and_persist.py and end-to-end in
    test_bridge_corpus.py).
    """
    from unittest.mock import AsyncMock

    mock = AsyncMock(name="analyze_and_persist_mock")
    monkeypatch.setattr(
        "app.domain.bridge_shadow.analyze_and_persist", mock
    )
    return mock


@pytest_asyncio.fixture
async def shadow_session_capture(
    db_session: AsyncSession, monkeypatch
):
    """Override `_get_sessionmaker` so the shadow path's OWN
    session is bound to the SAME connection as `db_session`,
    using `join_transaction_mode="create_savepoint"`. Shadow
    writes inherit the test's outer-transaction rollback
    discipline at fixture teardown.

    Used by the small set of B.6B.3 tests that exercise the real
    orchestrator end-to-end through the HTTP route (most route
    tests mock at the orchestrator boundary via
    `shadow_orchestrator_mock` instead -- faster + simpler).
    """
    test_connection = db_session.bind

    class _SavepointBoundFactory:
        def __call__(self) -> AsyncSession:
            return AsyncSession(
                bind=test_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

    factory_instance = _SavepointBoundFactory()

    monkeypatch.setattr(
        "app.domain.bridge_shadow._get_sessionmaker",
        lambda: factory_instance,
    )
    yield factory_instance
