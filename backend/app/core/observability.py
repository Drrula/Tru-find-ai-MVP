"""Observability: Sentry integration.

Per ADR-030. Initializes Sentry SDK when SENTRY_DSN is set; otherwise
all entry points are no-ops so callers never need conditional checks.

Exception capture attaches `request_id` from structlog contextvars (set
by RequestIDMiddleware) so Sentry events correlate to the originating
request. Event breadcrumbs route through `report_event_breadcrumb`,
called by `publish_event` after dispatch.

PII redaction (per ADR-013) applied via beforeSend hook on every Sentry
event and on every breadcrumb payload. Field list lives in
`app.core.pii` so logging + observability scrubbing stay aligned.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core.pii import PII_FIELDS

log = structlog.get_logger("app.core.observability")

# Module-level state. `_sentry_sdk` holds the imported sentry_sdk module
# after init so the rest of this module doesn't carry a hard import
# dependency when Sentry is disabled.
_sentry_sdk: Any = None
_initialized = False


def _redact_payload(payload: Any) -> Any:
    """Walk a value (dict / list / scalar) and redact known PII keys.

    Used by both the Sentry beforeSend hook (event-level) and the
    breadcrumb scrubber (payload-level).
    """
    if isinstance(payload, dict):
        return {
            k: ("[redacted]" if k.lower() in PII_FIELDS else _redact_payload(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    return payload


def _before_send(event: dict, _hint: dict) -> dict | None:
    """Sentry beforeSend hook: scrub PII keys recursively before transmission."""
    return _redact_payload(event)


def init_sentry(dsn: str | None, env: str = "development") -> None:
    """Initialize Sentry if DSN is set; otherwise no-op.

    Idempotent — safe to call multiple times (only the first call with
    a DSN initializes). Conservative defaults: traces sampled at 10%,
    profiling off, no default PII collection. Tune via env vars per
    Railway environment.
    """
    global _sentry_sdk, _initialized
    if not dsn:
        log.debug("sentry_disabled")
        return
    if _initialized:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.0,
        send_default_pii=False,
        before_send=_before_send,
        attach_stacktrace=True,
    )

    _sentry_sdk = sentry_sdk
    _initialized = True
    log.info("sentry_initialized", env=env)


def report_exception(exc: BaseException) -> None:
    """Capture an exception to Sentry. No-op when Sentry isn't initialized.

    Attaches `request_id` from structlog contextvars (set by
    RequestIDMiddleware per ADR-030) so the Sentry event correlates
    with the originating request.
    """
    if not _initialized or _sentry_sdk is None:
        return
    ctx = structlog.contextvars.get_contextvars()
    request_id = ctx.get("request_id")
    with _sentry_sdk.push_scope() as scope:
        if request_id:
            scope.set_tag("request_id", request_id)
        _sentry_sdk.capture_exception(exc)


def report_event_breadcrumb(event_type: str, payload: dict | None = None) -> None:
    """Record an emitted event as a Sentry breadcrumb. No-op when not initialized.

    Called by `publish_event` after dispatch (per ADR-044). Payload is
    PII-scrubbed before attaching so a future error report shows the
    event timeline without leaking sensitive data.
    """
    if not _initialized or _sentry_sdk is None:
        return
    _sentry_sdk.add_breadcrumb(
        category="event",
        message=event_type,
        level="info",
        data=_redact_payload(payload or {}),
    )
