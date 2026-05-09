"""Minimal smoke tests for B.0.1 core layer.

Verifies imports, config loading, ID generation, and the FastAPI app boots
with middleware + error handlers — and that the deterministic scoring
behavior is preserved end-to-end. A.9 will replace this with a fuller
harness (per-domain tests, integration tests).
"""

from __future__ import annotations

from uuid import UUID

import pytest


def test_imports() -> None:
    """All core modules import without side effects."""
    from app.core import config, errors, ids, logging, middleware, observability  # noqa: F401


def test_settings_loads_with_defaults() -> None:
    """Settings instantiates with sensible defaults (no env required)."""
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.app_env in {"development", "staging", "production"}
    assert s.log_level == "INFO"
    assert s.rate_limit_per_minute == 60
    assert s.request_id_header == "X-Request-ID"


def test_uuidv7_version_and_monotonicity() -> None:
    """new_id() returns version-7 UUIDs and is roughly time-ordered."""
    from app.core.ids import new_id

    a = new_id()
    b = new_id()
    assert isinstance(a, UUID)
    assert a.version == 7
    assert b.version == 7
    # First 6 bytes are timestamp_ms big-endian; equal-or-greater proves monotonicity.
    assert b.bytes[:6] >= a.bytes[:6]
    # Variant bits: top 2 bits of byte 8 must be 10
    assert (a.bytes[8] & 0xC0) == 0x80
    assert (b.bytes[8] & 0xC0) == 0x80


def test_uuidv7_uniqueness() -> None:
    """new_id() must not collide across many invocations."""
    from app.core.ids import new_id

    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_logging_configures_idempotent() -> None:
    """configure_logging() is safe to call multiple times."""
    from app.core.logging import configure_logging, get_logger

    configure_logging("INFO")
    configure_logging("INFO")
    log = get_logger("test")
    log.info("smoke", phase="B.0.1")  # must not raise


def test_app_boots_with_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """The FastAPI app instantiates with middleware/error handlers and /health responds."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_ENV", "development")
    from app.main import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    # Request ID middleware adds X-Request-ID to every response.
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    # And it's a valid UUID.
    UUID(rid)


def test_inbound_request_id_honored() -> None:
    """Client-supplied X-Request-ID is preserved on the response."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    inbound = "11111111-1111-7111-8111-111111111111"
    r = client.get("/health", headers={"X-Request-ID": inbound})
    assert r.headers["X-Request-ID"] == inbound


def test_analyze_business_unchanged() -> None:
    """Behavior parity check: legacy /analyze-business returns the deterministic
    response shape after the core layer is wired in. Same input must produce
    the same score (60) it did pre-A.4."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/analyze-business",
        json={"business_name": "Joe Pizza", "location": "Brooklyn, NY"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 60
    assert sorted(body.keys()) == [
        "category_scores",
        "competitors",
        "gaps",
        "score",
        "summary",
        "trade",
    ]
    assert len(body["competitors"]) == 3


def test_create_app_emits_system_started_event() -> None:
    """B.0.3 production emit site: create_app() publishes system.app.started
    via the active publisher. End-to-end proof that the event abstraction is
    wired into application startup (per ADR-044)."""
    from app.core.events import (
        RecordingEventPublisher,
        reset_publisher,
        set_publisher,
    )
    from app.main import create_app

    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        create_app()
        emitted_types = [e.event_type for e in rec.events]
        assert "system.app.started" in emitted_types

        started = next(e for e in rec.events if e.event_type == "system.app.started")
        assert started.actor_kind == "system"
        assert "env" in started.payload
        assert "version" in started.payload
    finally:
        reset_publisher()
