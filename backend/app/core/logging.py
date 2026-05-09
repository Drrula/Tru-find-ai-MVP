"""Structured JSON logging via structlog.

Per ADR-030. Per-request context (request_id, account_id) is bound via
contextvars and propagated automatically through the call stack and into
worker jobs. Known PII fields are redacted at the formatter level (per
ADR-013).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

# Fields that, if present in a log event_dict, are redacted before output.
# Aligned with ADR-013 PII policy. Keep this set in sync as new sensitive
# fields are introduced.
_REDACT_FIELDS = frozenset(
    {
        "email",
        "email_plaintext",
        "phone",
        "phone_plaintext",
        "address",
        "tax_id",
        "ssn",
        "password",
        "api_key",
        "secret",
        "access_token",
        "session_token",
        "magic_link_token",
        "encryption_key",
    }
)


def _redact_pii(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Replace values for known PII keys with '[redacted]'."""
    for key in event_dict:
        if key.lower() in _REDACT_FIELDS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging to emit JSON lines.

    Idempotent — safe to call from app startup or tests.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_pii,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a bound logger; pre-binds the module name when provided."""
    return structlog.get_logger(name) if name else structlog.get_logger()
