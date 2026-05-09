"""Canonical event envelope and publisher abstraction.

Per ADR-044. Every event in the system flows through this envelope;
persistence shapes (`lead_event`, `audit_log`, `billing_event`,
`compliance_policy_evaluation`) are projections of it. Producers do not
write directly to those tables.

In v1 (Phase A): synchronous publish. `LoggingEventPublisher` emits a
JSON line via structlog. `DatabaseEventPublisher` (Phase B+) and async
publish (Phase C) slot in via the same `EventPublisher` Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

import structlog

from app.core.event_registry import lookup
from app.core.ids import new_id

ENVELOPE_SCHEMA_VERSION = 1

ALLOWED_ACTOR_KINDS: frozenset[str] = frozenset(
    {"user", "system", "webhook", "job", "ai"}
)


@dataclass(frozen=True)
class Event:
    """Canonical event envelope. Frozen — no mutation after construction.

    Constructed via `publish_event(...)` in normal use; direct construction is
    reserved for tests and for replay (Phase B+).
    """

    event_id: UUID
    event_type: str
    occurred_at: datetime
    account_id: UUID | None
    correlation_id: UUID | None
    actor_kind: str
    actor_user_id: UUID | None
    target_kind: str | None
    target_id: UUID | None
    payload: dict[str, Any]
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict (UUIDs and datetime as strings)."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "account_id": str(self.account_id) if self.account_id else None,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "actor_kind": self.actor_kind,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "target_kind": self.target_kind,
            "target_id": str(self.target_id) if self.target_id else None,
            "payload": self.payload,
            "schema_version": self.schema_version,
        }


class EventPublisher(Protocol):
    """Producer-side API. Synchronous in v1; async deferred to Phase C."""

    def publish(self, event: Event) -> None: ...


class LoggingEventPublisher:
    """Default Phase A publisher: emits each event as a structured JSON log line.

    The DatabaseEventPublisher (Phase B+) and MultiPublisher (Phase D+) slot
    in via the same `EventPublisher` Protocol without producer-side change.
    """

    def __init__(self, logger_name: str = "events") -> None:
        self._log = structlog.get_logger(logger_name)

    def publish(self, event: Event) -> None:
        self._log.info("event", **event.to_dict())


class RecordingEventPublisher:
    """Test stub: stores emitted events for assertions."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)


# MultiPublisher (fan-out) is deferred to Phase D+ per ADR-044.

# --- Process-wide singleton publisher

_publisher: EventPublisher | None = None


def get_publisher() -> EventPublisher:
    """Return the process-wide publisher; defaults to LoggingEventPublisher."""
    global _publisher
    if _publisher is None:
        _publisher = LoggingEventPublisher()
    return _publisher


def set_publisher(publisher: EventPublisher) -> None:
    """Override the singleton (test injection or composition with MultiPublisher)."""
    global _publisher
    _publisher = publisher


def reset_publisher() -> None:
    """Reset to None so the next get_publisher() returns a fresh default."""
    global _publisher
    _publisher = None


# --- Producer-side helper

def publish_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    actor_kind: str = "system",
    actor_user_id: UUID | None = None,
    account_id: UUID | None = None,
    target_kind: str | None = None,
    target_id: UUID | None = None,
    correlation_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> Event:
    """Look up event_type in the registry, build the envelope, publish, and return it.

    Per ADR-044: producers obtain a Definition from the registry — never construct
    event_type strings inline at emit sites. This helper enforces that contract by
    raising UnknownEventTypeError for unregistered types.

    `correlation_id` is an explicit parameter in B.0.2; auto-fill from middleware
    contextvars lands in B.0.3 (correlation propagation).
    """
    definition = lookup(event_type)

    if actor_kind not in ALLOWED_ACTOR_KINDS:
        raise ValueError(f"Unknown actor_kind: {actor_kind!r}")
    if actor_kind not in definition.actor_kinds_allowed:
        raise ValueError(
            f"actor_kind {actor_kind!r} not allowed for event_type {event_type!r}; "
            f"allowed: {sorted(definition.actor_kinds_allowed)}"
        )

    event = Event(
        event_id=new_id(),
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        account_id=account_id,
        correlation_id=correlation_id,
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        target_kind=target_kind,
        target_id=target_id,
        payload=payload or {},
    )
    get_publisher().publish(event)
    return event
