"""B.1.2 introspection smoke tests for the SQLAlchemy engine + session.

Per docs/phase-b-plan.md §5. **NO database connection is opened by these
tests** — they verify module structure, factory shapes, and the FastAPI
dependency contract. Real-DB integration tests are deferred (plan §11);
they land alongside testcontainers when a future sub-phase needs them.
"""

from __future__ import annotations

import inspect

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase


def test_db_modules_import_cleanly() -> None:
    """The `app.db` package and its three modules import without side effects."""
    from app.db import base, engine, session  # noqa: F401
    from app.db.base import Base  # noqa: F401
    from app.db.engine import dispose_engine, get_engine  # noqa: F401
    from app.db.session import get_session  # noqa: F401


def test_base_is_declarative_base() -> None:
    """`Base` is a SQLAlchemy DeclarativeBase subclass — models can inherit from it."""
    from app.db.base import Base

    assert issubclass(Base, DeclarativeBase)


def test_get_engine_returns_async_engine() -> None:
    """get_engine() returns an AsyncEngine instance."""
    from app.db.engine import dispose_engine, get_engine
    import asyncio

    # Reset any prior engine so this test sees a fresh construction path.
    asyncio.run(dispose_engine())

    engine = get_engine()
    assert isinstance(engine, AsyncEngine)


def test_get_engine_is_singleton() -> None:
    """Subsequent get_engine() calls return the same instance (process-wide)."""
    from app.db.engine import get_engine

    a = get_engine()
    b = get_engine()
    assert a is b


def test_get_engine_uses_postgresql_asyncpg_dialect() -> None:
    """Engine targets postgresql+asyncpg per docs/phase-b-plan.md §3."""
    from app.db.engine import get_engine

    engine = get_engine()
    assert engine.url.drivername == "postgresql+asyncpg"


def test_get_engine_url_matches_settings() -> None:
    """Engine URL components reflect Settings.database_url (dev default in tests)."""
    from app.core.config import get_settings
    from app.db.engine import get_engine

    settings = get_settings()
    engine = get_engine()
    # Dev default per docs/phase-b-plan.md §6.
    assert settings.database_url is not None
    assert engine.url.host == "localhost"
    assert engine.url.database == "trufindai"
    assert engine.url.port == 5432


def test_get_session_is_async_generator() -> None:
    """get_session is an async generator function — required for FastAPI Depends."""
    from app.db.session import get_session

    assert inspect.isasyncgenfunction(get_session)


def test_dispose_engine_is_coroutine() -> None:
    """dispose_engine is an async function for clean shutdown."""
    from app.db.engine import dispose_engine

    assert inspect.iscoroutinefunction(dispose_engine)
