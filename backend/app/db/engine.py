"""Async SQLAlchemy engine wired to Settings.database_url.

Per docs/phase-b-plan.md §3 and ADR-002. A single process-wide
`AsyncEngine` is constructed lazily on first `get_engine()` call —
importing this module does not open a database connection. Connections
are opened only when a session checks one out from the engine's pool.

Pool: SQLAlchemy default `AsyncAdaptedQueuePool` with `pool_pre_ping=True`
so stale connections (Postgres timeouts, transient network blips) are
detected and replaced rather than handed to a session that then fails.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide AsyncEngine, constructing on first call.

    Idempotent — subsequent calls return the same engine instance.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        # database_url is guaranteed non-None by Settings._resolve_database_url
        # (dev default applied; staging/prod fail fast if unset).
        assert settings.database_url is not None
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            future=True,
            pool_pre_ping=True,
        )
    return _engine


async def dispose_engine() -> None:
    """Dispose the process-wide engine and reset the singleton.

    Call from FastAPI shutdown hook (Phase B+ when wired) or from tests
    that need a fresh engine. Safe to call when no engine has been built.
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
