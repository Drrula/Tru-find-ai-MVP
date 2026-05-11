"""Register the canonical `lead.*` event types with the in-process
registry (per ADR-040 + ADR-044 + phase-b4-plan.md §5).

This is the IN-PROCESS registry (`app.core.event_registry`) that
`publish_event(...)` consults to validate event_type strings.
SEPARATE from the DB `lead_event_definition` catalog (introduced in
B.4.2 — the catalog is consulted by domain code at write time to
resolve the `event_definition_id` FK). The two catalogs must stay in
sync; operators / future seed tooling ensures it.

Mirrors `app.domain.auth.events` pattern — idempotent registration
so tests that `reset_registry()` and re-import don't blow up.

B.4.2 seeds three event types. Future sub-phases (B.4.4 + B.4.5)
emit through them; future phases extend the set.
"""

from __future__ import annotations

from app.core.event_registry import (
    DuplicateRegistrationError,
    EventTypeDefinition,
    register,
)

# All lead.* events project to the `lead_event` table per ADR-044.

LEAD_LIFECYCLE_TRANSITION = EventTypeDefinition(
    event_type="lead.lifecycle.transition",
    category="lifecycle",
    target_table="lead_event",
    payload_schema={
        "type": "object",
        "properties": {
            "from_state": {"type": "string"},
            "to_state": {"type": "string"},
        },
        "additionalProperties": True,
    },
    actor_kinds_allowed=frozenset({"user", "system", "webhook", "job", "ai"}),
    description=(
        "A lead transitioned between lifecycle states. Emitted by the "
        "domain lifecycle helper (`app.domain.leads.lifecycle.transition`)."
    ),
)

LEAD_SIGNAL_OBSERVED = EventTypeDefinition(
    event_type="lead.signal.observed",
    category="enrichment",
    target_table="lead_event",
    payload_schema={
        "type": "object",
        "properties": {
            "signal_name": {"type": "string"},
            "source": {"type": "string"},
        },
        "additionalProperties": True,
    },
    actor_kinds_allowed=frozenset({"user", "system", "webhook", "job", "ai"}),
    description=(
        "A new lead_signal observation was recorded. Emitted by the "
        "domain recording helper (`app.domain.leads.recording.record_lead_signal`)."
    ),
)

LEAD_EVENT_RECORDED = EventTypeDefinition(
    event_type="lead.event.recorded",
    category="engagement",
    target_table="lead_event",
    payload_schema={"type": "object", "additionalProperties": True},
    actor_kinds_allowed=frozenset({"user", "system", "webhook", "job", "ai"}),
    description=(
        "Generic lead event recorded. Emitted by the domain recording "
        "helper when no more specific lead.* event_type applies."
    ),
)


_LEAD_DEFINITIONS = (
    LEAD_LIFECYCLE_TRANSITION,
    LEAD_SIGNAL_OBSERVED,
    LEAD_EVENT_RECORDED,
)


def register_lead_event_types() -> None:
    """Register all lead.* event definitions. Idempotent.

    Called once at module import. Tests that call
    `app.core.event_registry.reset_registry()` and re-import can
    call this directly to re-register without forcing a module
    reload (matches the auth-events pattern).
    """
    for definition in _LEAD_DEFINITIONS:
        try:
            register(definition)
        except DuplicateRegistrationError:
            continue


register_lead_event_types()
