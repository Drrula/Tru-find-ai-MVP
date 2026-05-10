"""Async session factory + FastAPI dependency.

Per docs/phase-b-plan.md §3. `get_session()` is the per-request
dependency that yields an `AsyncSession` bound to the process-wide
`AsyncEngine`. The session lifecycle is request-scoped:
  - on success: `await session.commit()`
  - on exception: `await session.rollback()`
  - always: `async with` closes the connection (returns to pool)

Per ADR-031, route handlers receive a session via `Depends(get_session)`
and pass it to a repository (`AccountRepository(session, account_id)`).
Domain code never instantiates a session directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import get_engine

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async_sessionmaker, constructing on first call."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            # expire_on_commit=False so attributes remain accessible after commit
            # without triggering a fresh DB load — matches FastAPI request lifetime
            # where the response serializer reads attributes after the handler returns.
            expire_on_commit=False,
            # autoflush=False makes flushes explicit; reduces surprising side-effects
            # during repository read paths.
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession with auto-commit-or-rollback.

    Wire as `Depends(get_session)` in route handlers (Phase C+ when handlers
    actually use the DB). For B.1.2 this is just the contract — no caller
    consumes it yet.
    """
    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
