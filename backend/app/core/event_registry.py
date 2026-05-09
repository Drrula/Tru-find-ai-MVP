"""In-process event type registry (per ADR-044, ADR-040 pattern).

In v1 (Phase A): definitions are code constants registered at module
import time. In Phase B+, this registry promotes to DB-driven tables
(`lead_event_definition` and analogues for audit / billing / compliance)
per ADR-040.

Producers look up an `EventTypeDefinition` by `event_type` before
constructing an `Event`. Emit-site code never hardcodes `event_type`
strings — only constants exported here or by a domain registry module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Categories: ADR-040 lead categories + system/audit/billing/compliance
# (which project to audit_log, billing_event, compliance_policy_evaluation).
CATEGORIES: frozenset[str] = frozenset(
    {
        "engagement",
        "intent",
        "enrichment",
        "ai",
        "attribution",
        "communication",
        "lifecycle",
        "orchestration",  # reserved per ADR-040 Q15
        "system",
        "audit",
        "billing",
        "compliance",
    }
)

# Target tables matching projection-table names in ARCHITECTURE-LOCK §2 and §2.5/§2.6.
TARGET_TABLES: frozenset[str] = frozenset(
    {
        "lead_event",
        "audit_log",
        "billing_event",
        "compliance_policy_evaluation",
        "log_only",  # Phase A default — no DB projection yet
    }
)


@dataclass(frozen=True)
class EventTypeDefinition:
    """One entry in the registry. Phase B+ promotes to a DB row per ADR-040."""

    event_type: str
    category: str
    target_table: str
    payload_schema: dict[str, Any]  # JSON Schema; strict validation deferred to Phase B
    actor_kinds_allowed: frozenset[str]
    schema_version: int = 1
    description: str = ""


class UnknownEventTypeError(KeyError):
    """Raised by lookup() when the event_type is not registered."""


class DuplicateRegistrationError(ValueError):
    """Raised by register() when the event_type is already registered."""


_REGISTRY: dict[str, EventTypeDefinition] = {}


def register(definition: EventTypeDefinition) -> None:
    """Register an event type. Validates category and target_table; rejects duplicates."""
    if definition.category not in CATEGORIES:
        raise ValueError(
            f"Unknown category: {definition.category!r}; allowed: {sorted(CATEGORIES)}"
        )
    if definition.target_table not in TARGET_TABLES:
        raise ValueError(
            f"Unknown target_table: {definition.target_table!r}; allowed: {sorted(TARGET_TABLES)}"
        )
    if definition.event_type in _REGISTRY:
        raise DuplicateRegistrationError(definition.event_type)
    _REGISTRY[definition.event_type] = definition


def lookup(event_type: str) -> EventTypeDefinition:
    """Look up a registered event type. Raises UnknownEventTypeError if missing."""
    try:
        return _REGISTRY[event_type]
    except KeyError as e:
        raise UnknownEventTypeError(event_type) from e


def all_types() -> list[EventTypeDefinition]:
    """Return all registered definitions, sorted by event_type."""
    return sorted(_REGISTRY.values(), key=lambda d: d.event_type)


def reset_registry() -> None:
    """Test-only: clear the registry and re-seed. Do not call from production code."""
    _REGISTRY.clear()
    _seed()


# --- Seed types
#
# Minimal in B.0.2 — just enough to demonstrate the pipeline. Domain-specific
# event types land in their respective domain phases (Phase B for lead lifecycle,
# Phase E for billing, etc.) and register against their target tables.

SYSTEM_APP_STARTED = EventTypeDefinition(
    event_type="system.app.started",
    category="system",
    target_table="log_only",
    payload_schema={
        "type": "object",
        "properties": {
            "env": {"type": "string"},
            "version": {"type": "string"},
        },
        "additionalProperties": True,
    },
    actor_kinds_allowed=frozenset({"system"}),
    description="Emitted once when the FastAPI app finishes initialization.",
)


def _seed() -> None:
    register(SYSTEM_APP_STARTED)


_seed()
