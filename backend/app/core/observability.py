"""Observability stubs (Sentry init, exception capture).

Real Sentry integration lands in A.12 once `sentry-sdk` is added as a
dependency. For now these are no-ops so the rest of the system can call
them without conditional checks. Per ADR-030.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger("app.core.observability")


def init_sentry(dsn: str | None, env: str = "development") -> None:
    """Initialize Sentry if DSN is set; otherwise no-op.

    Stub: real init lands in A.12 once sentry-sdk is a dependency.
    """
    if dsn:
        log.info("sentry_init_skipped", reason="stub_until_a12", env=env)
    else:
        log.debug("sentry_disabled")


def report_exception(exc: BaseException) -> None:
    """Capture an exception to Sentry; no-op until A.12."""
    # Intentionally empty in the stub. A.12 wires sentry_sdk.capture_exception(exc).
    return None
