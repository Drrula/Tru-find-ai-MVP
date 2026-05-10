"""B.2.1 tests for app.domain.notifications.email.

Verifies the EmailSender Protocol contract is satisfied by
LoggingEmailSender, and that .send() emits a structured log line
carrying recipient + subject + body_text.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_logging_email_sender_satisfies_protocol_shape() -> None:
    """LoggingEmailSender exposes an async `send(*, to, subject, body_text)`."""
    import inspect

    from app.domain.notifications.email import LoggingEmailSender

    sender = LoggingEmailSender()
    assert hasattr(sender, "send")
    assert inspect.iscoroutinefunction(sender.send)


async def test_logging_email_sender_emits_structured_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.notifications.email import LoggingEmailSender

    sender = LoggingEmailSender()
    fake_log = MagicMock()
    monkeypatch.setattr(sender, "_log", fake_log)

    await sender.send(
        to="alice@example.com",
        subject="Your magic link",
        body_text="https://app.example.com/auth/consume?token=abc123",
    )

    fake_log.info.assert_called_once()
    args, kwargs = fake_log.info.call_args
    assert args == ("email_logged",)
    assert kwargs["recipient"] == "alice@example.com"
    assert kwargs["subject"] == "Your magic link"
    assert "consume?token=abc123" in kwargs["body_text"]


async def test_logging_email_sender_uses_non_pii_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recipient is logged under `recipient`, NOT `email`, so the structlog
    PII redactor (which redacts the key `email`) does not strip it.
    Documented behavior — operator needs the address in dev logs."""
    from app.domain.notifications.email import LoggingEmailSender

    sender = LoggingEmailSender()
    fake_log = MagicMock()
    monkeypatch.setattr(sender, "_log", fake_log)

    await sender.send(to="x@y.com", subject="s", body_text="b")

    _args, kwargs = fake_log.info.call_args
    assert "email" not in kwargs  # avoided the PII-redacted key name
    assert "recipient" in kwargs
