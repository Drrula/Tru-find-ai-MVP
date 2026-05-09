"""Smoke tests for the canonical event envelope and publisher (B.0.2).

Per ADR-044. Verifies envelope shape, publisher protocol, registry-driven
emission, and correlation-id propagation through structlog contextvars.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

import pytest


def _make_event() -> "object":
    """Build a minimal Event for direct-construction tests."""
    from app.core.events import Event
    from app.core.ids import new_id

    return Event(
        event_id=new_id(),
        event_type="system.app.started",
        occurred_at=datetime.now(timezone.utc),
        account_id=None,
        correlation_id=None,
        actor_kind="system",
        actor_user_id=None,
        target_kind=None,
        target_id=None,
        payload={},
    )


def test_event_is_frozen() -> None:
    e = _make_event()
    with pytest.raises(FrozenInstanceError):
        e.event_type = "other"  # type: ignore[misc]


def test_event_to_dict_serializes_uuids_and_timestamps() -> None:
    from app.core.events import ENVELOPE_SCHEMA_VERSION, Event
    from app.core.ids import new_id

    eid = new_id()
    occ = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)
    e = Event(
        event_id=eid,
        event_type="system.app.started",
        occurred_at=occ,
        account_id=None,
        correlation_id=None,
        actor_kind="system",
        actor_user_id=None,
        target_kind=None,
        target_id=None,
        payload={"env": "test"},
    )
    d = e.to_dict()
    assert d["event_id"] == str(eid)
    assert d["occurred_at"] == "2026-05-09T12:00:00+00:00"
    assert d["actor_kind"] == "system"
    assert d["payload"] == {"env": "test"}
    assert d["schema_version"] == ENVELOPE_SCHEMA_VERSION
    assert d["account_id"] is None
    assert d["correlation_id"] is None


def test_publish_event_via_recording_publisher() -> None:
    from app.core.events import (
        RecordingEventPublisher,
        publish_event,
        reset_publisher,
        set_publisher,
    )

    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        ev = publish_event(
            "system.app.started",
            payload={"env": "test"},
            actor_kind="system",
        )
        assert len(rec.events) == 1
        assert rec.events[0] is ev
        assert ev.event_type == "system.app.started"
        assert ev.actor_kind == "system"
        assert ev.event_id.version == 7
    finally:
        reset_publisher()


def test_publish_event_unknown_type_raises() -> None:
    from app.core.event_registry import UnknownEventTypeError
    from app.core.events import publish_event

    with pytest.raises(UnknownEventTypeError):
        publish_event("nonexistent.event.type", payload={})


def test_publish_event_disallowed_actor_kind_raises() -> None:
    from app.core.events import publish_event

    # system.app.started only allows actor_kind="system"
    with pytest.raises(ValueError, match="not allowed"):
        publish_event("system.app.started", payload={}, actor_kind="user")


def test_publish_event_unknown_actor_kind_raises() -> None:
    from app.core.events import publish_event

    with pytest.raises(ValueError, match="Unknown actor_kind"):
        publish_event("system.app.started", payload={}, actor_kind="bogus")


def test_publish_event_explicit_correlation_id_passes_through() -> None:
    """Explicit correlation_id parameter is set on the envelope verbatim."""
    from app.core.events import (
        RecordingEventPublisher,
        publish_event,
        reset_publisher,
        set_publisher,
    )
    from app.core.ids import new_id

    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        rid = new_id()
        ev = publish_event("system.app.started", payload={}, correlation_id=rid)
        assert ev.correlation_id == rid
    finally:
        reset_publisher()


def test_publish_event_autofills_correlation_from_contextvars() -> None:
    """B.0.3: correlation_id falls back to the structlog `request_id` contextvar.

    Mirrors what RequestIDMiddleware sets per request, so events emitted from
    request handlers inherit the request's correlation automatically.
    """
    import structlog

    from app.core.events import (
        RecordingEventPublisher,
        publish_event,
        reset_publisher,
        set_publisher,
    )
    from app.core.ids import new_id

    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        rid = new_id()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=str(rid))
        try:
            ev = publish_event("system.app.started", payload={})
            assert ev.correlation_id == rid
        finally:
            structlog.contextvars.clear_contextvars()
    finally:
        reset_publisher()


def test_publish_event_explicit_correlation_overrides_contextvar() -> None:
    """If both an explicit correlation_id and a contextvar request_id exist,
    the explicit parameter wins (caller intent is authoritative)."""
    import structlog

    from app.core.events import (
        RecordingEventPublisher,
        publish_event,
        reset_publisher,
        set_publisher,
    )
    from app.core.ids import new_id

    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        ctx_rid = new_id()
        explicit_rid = new_id()
        assert ctx_rid != explicit_rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=str(ctx_rid))
        try:
            ev = publish_event(
                "system.app.started",
                payload={},
                correlation_id=explicit_rid,
            )
            assert ev.correlation_id == explicit_rid
        finally:
            structlog.contextvars.clear_contextvars()
    finally:
        reset_publisher()


def test_publish_event_handles_non_uuid_request_id() -> None:
    """If middleware honored a non-UUID inbound X-Request-ID, degrade gracefully:
    correlation_id ends up None rather than crashing the publish."""
    import structlog

    from app.core.events import (
        RecordingEventPublisher,
        publish_event,
        reset_publisher,
        set_publisher,
    )

    rec = RecordingEventPublisher()
    set_publisher(rec)
    try:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id="not-a-uuid")
        try:
            ev = publish_event("system.app.started", payload={})
            assert ev.correlation_id is None
        finally:
            structlog.contextvars.clear_contextvars()
    finally:
        reset_publisher()


def test_logging_event_publisher_calls_logger_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """LoggingEventPublisher routes to structlog with the envelope as kwargs."""
    from app.core.events import LoggingEventPublisher

    pub = LoggingEventPublisher()
    fake = MagicMock()
    monkeypatch.setattr(pub, "_log", fake)

    pub.publish(_make_event())

    fake.info.assert_called_once()
    args, kwargs = fake.info.call_args
    assert args == ("event",)
    assert kwargs["event_type"] == "system.app.started"
    assert kwargs["actor_kind"] == "system"
    assert kwargs["schema_version"] == 1
    # UUID-ish strings on the wire (not raw UUID objects)
    UUID(kwargs["event_id"])


def test_get_publisher_default_is_logging_publisher() -> None:
    from app.core.events import LoggingEventPublisher, get_publisher, reset_publisher

    reset_publisher()
    try:
        assert isinstance(get_publisher(), LoggingEventPublisher)
    finally:
        reset_publisher()
