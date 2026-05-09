"""A.12 smoke tests for Sentry wire-up.

Per ADR-030. Verifies init / capture / breadcrumb behavior with a
mocked sentry_sdk so tests don't require a real DSN.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_observability_state():
    """Reset module-level Sentry state between tests."""
    import app.core.observability as obs

    obs._sentry_sdk = None
    obs._initialized = False
    yield
    obs._sentry_sdk = None
    obs._initialized = False


def test_init_sentry_no_dsn_is_noop() -> None:
    from app.core import observability as obs

    obs.init_sentry(None)
    assert obs._initialized is False
    assert obs._sentry_sdk is None


def test_init_sentry_with_dsn_initializes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import observability as obs

    fake_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)

    obs.init_sentry("https://fake@sentry.example.com/1", env="test")

    fake_sdk.init.assert_called_once()
    init_kwargs = fake_sdk.init.call_args.kwargs
    assert init_kwargs["dsn"] == "https://fake@sentry.example.com/1"
    assert init_kwargs["environment"] == "test"
    assert init_kwargs["send_default_pii"] is False
    assert init_kwargs["before_send"] is obs._before_send
    assert obs._initialized is True


def test_init_sentry_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import observability as obs

    fake_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)

    obs.init_sentry("https://fake@sentry.example.com/1")
    obs.init_sentry("https://fake@sentry.example.com/1")

    fake_sdk.init.assert_called_once()  # second call short-circuits


def test_report_exception_no_init_is_noop() -> None:
    from app.core import observability as obs

    obs.report_exception(ValueError("boom"))  # must not raise


def test_report_exception_attaches_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import structlog

    from app.core import observability as obs

    fake_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)

    obs.init_sentry("https://fake@sentry.example.com/1")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="rid-abc-123")
    try:
        obs.report_exception(ValueError("boom"))
    finally:
        structlog.contextvars.clear_contextvars()

    fake_sdk.capture_exception.assert_called_once()
    # push_scope is a context manager — verify scope.set_tag was called
    scope_mock = fake_sdk.push_scope.return_value.__enter__.return_value
    scope_mock.set_tag.assert_called_once_with("request_id", "rid-abc-123")


def test_report_event_breadcrumb_no_init_is_noop() -> None:
    from app.core import observability as obs

    obs.report_event_breadcrumb("system.test", {"k": "v"})  # must not raise


def test_report_event_breadcrumb_redacts_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import observability as obs

    fake_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)

    obs.init_sentry("https://fake@sentry.example.com/1")

    obs.report_event_breadcrumb(
        "lead.captured",
        {
            "lead_id": "lid-1",
            "email": "joe@example.com",  # PII per ADR-013
            "phone": "+15551234567",  # PII per ADR-013
            "nested": {"api_key": "sk_live_xxx"},  # PII inside nested dict
        },
    )

    fake_sdk.add_breadcrumb.assert_called_once()
    call_kwargs = fake_sdk.add_breadcrumb.call_args.kwargs
    assert call_kwargs["category"] == "event"
    assert call_kwargs["message"] == "lead.captured"
    data = call_kwargs["data"]
    assert data["lead_id"] == "lid-1"  # not PII, passes through
    assert data["email"] == "[redacted]"
    assert data["phone"] == "[redacted]"
    assert data["nested"]["api_key"] == "[redacted]"


def test_before_send_redacts_pii() -> None:
    from app.core import observability as obs

    event = {
        "message": "boom",
        "extra": {"email": "a@b.com", "ok": "fine"},
        "tags": [{"name": "tag1", "secret": "shh"}],
    }
    out = obs._before_send(event, {})

    assert out is not None
    assert out["message"] == "boom"
    assert out["extra"]["email"] == "[redacted]"
    assert out["extra"]["ok"] == "fine"
    assert out["tags"][0]["secret"] == "[redacted]"
    assert out["tags"][0]["name"] == "tag1"


def test_publish_event_triggers_breadcrumb_when_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    """publish_event() calls report_event_breadcrumb after dispatch (per A.12 wire-up)."""
    from app.core import observability as obs
    from app.core.events import (
        RecordingEventPublisher,
        publish_event,
        reset_publisher,
        set_publisher,
    )

    fake_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)
    obs.init_sentry("https://fake@sentry.example.com/1")

    set_publisher(RecordingEventPublisher())
    try:
        publish_event("system.app.started", payload={"env": "test"})
    finally:
        reset_publisher()

    fake_sdk.add_breadcrumb.assert_called_once()
    assert fake_sdk.add_breadcrumb.call_args.kwargs["message"] == "system.app.started"
