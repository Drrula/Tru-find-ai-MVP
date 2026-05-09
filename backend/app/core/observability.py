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


def report_event_breadcrumb(event_type: str, payload: dict | None = None) -> None:
    """Record an emitted event as a Sentry breadcrumb; no-op until A.12.

    Hook reserved for the future SentryBreadcrumbPublisher composed via
    MultiPublisher (Phase D+). Kept here so the integration shape is
    predictable when sentry-sdk is wired in A.12.

    Note: `publish_event` does not currently call this hook. PII redaction
    policy for breadcrumbs (per ADR-013) will be decided when the hook is
    activated; until then, leaving it unwired avoids accidental leaks.
    """
    return None
