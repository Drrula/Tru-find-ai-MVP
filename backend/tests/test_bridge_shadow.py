"""B.6B.2 unit tests for the shadow seam.

Per docs/phase-b6b-plan.md §11 tests 6-13 + §6 flag-OFF invariant.
Mock-only -- no real Postgres, no FastAPI route. Validates the
function's contract in isolation:

  FLAG OFF: zero work, zero logs, return None
  FLAG ON success: orchestrator called, session committed, DEBUG log
  FLAG ON failure: exception swallowed, session rolled back, WARNING log
  FLAG ON timeout: TimeoutError swallowed, rollback attempted, WARNING log
  Rollback failure: WARNING log, never propagates

The HTTP integration tests (B.6B.3) wire the seam to live routes
via FastAPI BackgroundTasks.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.core.config import Settings
from app.domain import bridge_shadow
from app.domain.bridge_shadow import (
    DEMO_ACCOUNT_ID,
    DEMO_VERTICAL_ID,
    SHADOW_TIMEOUT_SECONDS,
    run_shadow_persist_if_enabled,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    """A mock AsyncSession with awaitable commit + rollback."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_sessionmaker(mock_session: AsyncMock) -> MagicMock:
    """A mock that mimics async_sessionmaker: calling it returns
    an async context manager yielding `mock_session`.

    Pattern: `_get_sessionmaker()` returns `factory`. Then
    `async with factory() as session:` yields mock_session.
    """
    factory = MagicMock(name="async_sessionmaker_instance")
    cm = AsyncMock(name="session_context_manager")
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = cm
    return factory


@pytest.fixture
def patch_seam(monkeypatch, mock_sessionmaker):
    """Patches the shadow seam's external dependencies:
      - `get_settings` (toggle the flag in each test)
      - `_get_sessionmaker` (return our mock factory)
      - `analyze_and_persist` (mock the orchestrator)
      - `_logger` (mock structlog logger)

    Returns a SimpleNamespace with handles to each mock so tests
    can assert call shapes.
    """
    settings_holder = SimpleNamespace(b6b_shadow_scoring_enabled=False)

    def fake_get_settings():
        return settings_holder

    sessionmaker_getter = MagicMock(
        name="_get_sessionmaker", return_value=mock_sessionmaker
    )
    orchestrator = AsyncMock(name="analyze_and_persist")
    logger = MagicMock(name="_logger")

    monkeypatch.setattr(bridge_shadow, "get_settings", fake_get_settings)
    monkeypatch.setattr(
        bridge_shadow, "_get_sessionmaker", sessionmaker_getter
    )
    monkeypatch.setattr(
        bridge_shadow, "analyze_and_persist", orchestrator
    )
    monkeypatch.setattr(bridge_shadow, "_logger", logger)

    return SimpleNamespace(
        settings=settings_holder,
        sessionmaker_getter=sessionmaker_getter,
        sessionmaker=mock_sessionmaker,
        orchestrator=orchestrator,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# 1-2: Settings flag
# ---------------------------------------------------------------------------


def test_settings_b6b_flag_defaults_false(monkeypatch) -> None:
    """Per plan §2 decision #3: default OFF in every environment."""
    # Clear env vars that might bleed from the shell.
    monkeypatch.delenv("B6B_SHADOW_SCORING_ENABLED", raising=False)
    s = Settings()
    assert s.b6b_shadow_scoring_enabled is False


def test_settings_b6b_flag_reads_true_from_env(monkeypatch) -> None:
    """Env var `B6B_SHADOW_SCORING_ENABLED=true` flips the flag."""
    monkeypatch.setenv("B6B_SHADOW_SCORING_ENABLED", "true")
    s = Settings()
    assert s.b6b_shadow_scoring_enabled is True


def test_settings_b6b_flag_reads_false_from_env(monkeypatch) -> None:
    monkeypatch.setenv("B6B_SHADOW_SCORING_ENABLED", "false")
    s = Settings()
    assert s.b6b_shadow_scoring_enabled is False


# ---------------------------------------------------------------------------
# 3-6: Flag OFF invariants
# ---------------------------------------------------------------------------


async def test_flag_off_returns_none(patch_seam) -> None:
    patch_seam.settings.b6b_shadow_scoring_enabled = False
    result = await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    assert result is None


async def test_flag_off_zero_orchestrator_calls(patch_seam) -> None:
    """Invariant §6.1: zero orchestrator execution when flag OFF."""
    patch_seam.settings.b6b_shadow_scoring_enabled = False
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    patch_seam.orchestrator.assert_not_called()


async def test_flag_off_zero_sessionmaker_calls(patch_seam) -> None:
    """Invariants §6.3 + §6.4: zero sessionmaker invocation +
    zero connection acquisition. The flag check happens BEFORE
    any session work."""
    patch_seam.settings.b6b_shadow_scoring_enabled = False
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    patch_seam.sessionmaker_getter.assert_not_called()
    # And the factory itself was never called either.
    patch_seam.sessionmaker.assert_not_called()


async def test_flag_off_zero_logs(patch_seam) -> None:
    """Invariant §6.6: no divergence logs, no shadow logs. Per
    plan §2 decision #6: absence-is-signal -- there is NO
    "skipped because disabled" log."""
    patch_seam.settings.b6b_shadow_scoring_enabled = False
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    patch_seam.logger.debug.assert_not_called()
    patch_seam.logger.info.assert_not_called()
    patch_seam.logger.warning.assert_not_called()
    patch_seam.logger.error.assert_not_called()


# ---------------------------------------------------------------------------
# 7-9: Flag ON success
# ---------------------------------------------------------------------------


async def test_flag_on_success_orchestrator_called_once(
    patch_seam,
) -> None:
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    await run_shadow_persist_if_enabled(
        business_name="Joe Pizza",
        location="Brooklyn, NY",
        trade=None,
    )
    patch_seam.orchestrator.assert_awaited_once()


async def test_flag_on_success_orchestrator_receives_demo_identities(
    patch_seam, mock_session
) -> None:
    """Per plan §2 decision #10: shadow targets the demo seed
    rows. account_id + vertical_id passed to the orchestrator
    are the deterministic UUID5 constants."""
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    kwargs = patch_seam.orchestrator.await_args.kwargs
    assert kwargs["account_id"] == DEMO_ACCOUNT_ID
    assert kwargs["vertical_id"] == DEMO_VERTICAL_ID
    assert kwargs["business_name"] == "x"
    assert kwargs["location"] == "y"
    assert kwargs["trade"] is None


async def test_flag_on_success_commits_shadow_session(
    patch_seam, mock_session
) -> None:
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_called()


async def test_flag_on_success_emits_debug_log(patch_seam) -> None:
    """`bridge.shadow_succeeded` at DEBUG (per plan §7)."""
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    patch_seam.logger.debug.assert_called_once()
    args, kwargs = patch_seam.logger.debug.call_args
    assert args[0] == "bridge.shadow_succeeded"
    assert kwargs.get("business_name") == "x"
    assert kwargs.get("location") == "y"
    patch_seam.logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# 10-12: Flag ON failure (orchestrator raises)
# ---------------------------------------------------------------------------


async def test_flag_on_orchestrator_failure_swallows_exception(
    patch_seam,
) -> None:
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    patch_seam.orchestrator.side_effect = RuntimeError("boom")
    # MUST NOT raise.
    result = await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    assert result is None


async def test_flag_on_orchestrator_failure_rolls_back(
    patch_seam, mock_session
) -> None:
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    patch_seam.orchestrator.side_effect = RuntimeError("boom")
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_not_called()


async def test_flag_on_orchestrator_failure_logs_warning(
    patch_seam,
) -> None:
    """`bridge.shadow_failed` at WARNING with exc_info=True."""
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    patch_seam.orchestrator.side_effect = RuntimeError("boom")
    await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    patch_seam.logger.warning.assert_called_once()
    args, kwargs = patch_seam.logger.warning.call_args
    assert args[0] == "bridge.shadow_failed"
    assert kwargs.get("exc_info") is True
    patch_seam.logger.debug.assert_not_called()


# ---------------------------------------------------------------------------
# 13-15: Flag ON timeout
# ---------------------------------------------------------------------------


async def test_flag_on_timeout_swallows_timeout_error(
    patch_seam,
) -> None:
    """Orchestrator hangs past SHADOW_TIMEOUT_SECONDS ->
    asyncio.wait_for raises TimeoutError -> seam swallows it.
    To exercise this fast, configure the orchestrator mock to
    hang via a never-completing future + override the timeout
    constant to a tiny value."""
    patch_seam.settings.b6b_shadow_scoring_enabled = True

    async def hang_forever(**kwargs):
        await asyncio.sleep(10)  # well past the patched timeout

    patch_seam.orchestrator.side_effect = hang_forever

    # Override the timeout constant for fast test execution.
    import app.domain.bridge_shadow as bs

    original_timeout = bs.SHADOW_TIMEOUT_SECONDS
    bs.SHADOW_TIMEOUT_SECONDS = 0.05
    try:
        result = await run_shadow_persist_if_enabled(
            business_name="x", location="y", trade=None
        )
    finally:
        bs.SHADOW_TIMEOUT_SECONDS = original_timeout
    assert result is None


async def test_flag_on_timeout_rolls_back(
    patch_seam, mock_session
) -> None:
    patch_seam.settings.b6b_shadow_scoring_enabled = True

    async def hang_forever(**kwargs):
        await asyncio.sleep(10)

    patch_seam.orchestrator.side_effect = hang_forever

    import app.domain.bridge_shadow as bs

    original_timeout = bs.SHADOW_TIMEOUT_SECONDS
    bs.SHADOW_TIMEOUT_SECONDS = 0.05
    try:
        await run_shadow_persist_if_enabled(
            business_name="x", location="y", trade=None
        )
    finally:
        bs.SHADOW_TIMEOUT_SECONDS = original_timeout

    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_not_called()


async def test_flag_on_timeout_logs_warning(patch_seam) -> None:
    """`bridge.shadow_timeout` at WARNING -- distinct event from
    `bridge.shadow_failed` (per plan §2 decision #7: timeout is
    operational, divergence is scoring)."""
    patch_seam.settings.b6b_shadow_scoring_enabled = True

    async def hang_forever(**kwargs):
        await asyncio.sleep(10)

    patch_seam.orchestrator.side_effect = hang_forever

    import app.domain.bridge_shadow as bs

    original_timeout = bs.SHADOW_TIMEOUT_SECONDS
    bs.SHADOW_TIMEOUT_SECONDS = 0.05
    try:
        await run_shadow_persist_if_enabled(
            business_name="x", location="y", trade=None
        )
    finally:
        bs.SHADOW_TIMEOUT_SECONDS = original_timeout

    patch_seam.logger.warning.assert_called_once()
    args, kwargs = patch_seam.logger.warning.call_args
    assert args[0] == "bridge.shadow_timeout"
    assert kwargs.get("timeout_seconds") == 0.05
    # And specifically NOT shadow_failed -- the two events are
    # operationally distinct incident classes.
    for call in patch_seam.logger.warning.call_args_list:
        call_args, _ = call
        assert call_args[0] != "bridge.shadow_failed"


# ---------------------------------------------------------------------------
# 16: Rollback failure
# ---------------------------------------------------------------------------


async def test_rollback_failure_is_swallowed_and_logged(
    patch_seam, mock_session
) -> None:
    """When the rollback itself raises (e.g. session already
    closed by upstream cleanup), the seam MUST swallow and log
    at WARNING. The "return None unconditionally" contract
    cannot be broken by a nested failure."""
    patch_seam.settings.b6b_shadow_scoring_enabled = True
    patch_seam.orchestrator.side_effect = RuntimeError("orchestrator boom")
    mock_session.rollback.side_effect = RuntimeError("rollback boom")

    # MUST NOT raise.
    result = await run_shadow_persist_if_enabled(
        business_name="x", location="y", trade=None
    )
    assert result is None

    # Two WARNING events emitted: shadow_failed THEN
    # shadow_rollback_failed.
    warning_events = [
        c.args[0] for c in patch_seam.logger.warning.call_args_list
    ]
    assert "bridge.shadow_failed" in warning_events
    assert "bridge.shadow_rollback_failed" in warning_events
    # The rollback-failed call must carry exc_info=True.
    rollback_call = next(
        c for c in patch_seam.logger.warning.call_args_list
        if c.args[0] == "bridge.shadow_rollback_failed"
    )
    assert rollback_call.kwargs.get("exc_info") is True


# ---------------------------------------------------------------------------
# Demo-identity constants match migration 0020
# ---------------------------------------------------------------------------


def test_demo_account_id_matches_migration_0020() -> None:
    """The shadow seam targets the migration-seeded demo account.
    The constants here MUST equal the constants in
    backend/alembic/versions/0020_seed_demo_account_vertical_catalog.py."""
    repo_root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "alembic_0020_for_shadow_check",
        repo_root
        / "backend"
        / "alembic"
        / "versions"
        / "0020_seed_demo_account_vertical_catalog.py",
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert DEMO_ACCOUNT_ID == migration.DEMO_ACCOUNT_ID
    assert DEMO_VERTICAL_ID == migration.DEMO_VERTICAL_ID


def test_shadow_timeout_seconds_is_five() -> None:
    """Per plan §2 decision #5: hard 5s ceiling on shadow
    execution."""
    assert SHADOW_TIMEOUT_SECONDS == 5.0
