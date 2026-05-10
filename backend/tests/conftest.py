"""Shared pytest fixtures.

Per A.9. New tests should prefer these fixtures over inline setup; the
existing per-test inline setup (in test_core_*.py) stays as-is to avoid
churn — refactor opportunistically as those files are touched for other
reasons.
"""

from __future__ import annotations

from typing import Iterator

import pytest


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
