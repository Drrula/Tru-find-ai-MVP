"""Register the `auth.*` event types with the in-process registry.

Per ADR-040 + ADR-044: producers obtain a Definition from the registry
before calling `publish_event` — never construct event_type strings
inline at emit sites. This module is imported as a side-effect by
`app.domain.auth.__init__` so the registrations happen once at first
import.

All auth events project to `audit_log` (per ADR-015 — privileged auth
operations). actor_kinds are constrained to what the call sites in
`issue.py` / `consume.py` / `sessions.py` actually emit.

Registration is idempotent: if the registry has already been reset
(e.g. by a test via `reset_registry()`) and this module is re-imported,
the duplicate-registration error is swallowed for these definitions
specifically. Other producers' definitions will still surface real
duplicate errors.
"""

from __future__ import annotations

from app.core.event_registry import (
    DuplicateRegistrationError,
    EventTypeDefinition,
    register,
)

AUTH_MAGIC_LINK_REQUESTED = EventTypeDefinition(
    event_type="auth.magic_link.requested",
    category="audit",
    target_table="audit_log",
    payload_schema={"type": "object", "additionalProperties": True},
    actor_kinds_allowed=frozenset({"system"}),
    description=(
        "A magic-link token was minted and handed to the EmailSender "
        "(issue half of magic-link auth)."
    ),
)

AUTH_MAGIC_LINK_CONSUMED = EventTypeDefinition(
    event_type="auth.magic_link.consumed",
    category="audit",
    target_table="audit_log",
    payload_schema={"type": "object", "additionalProperties": True},
    actor_kinds_allowed=frozenset({"system"}),
    description=(
        "A magic-link token was successfully consumed; a session was created."
    ),
)

AUTH_MAGIC_LINK_REJECTED = EventTypeDefinition(
    event_type="auth.magic_link.rejected",
    category="audit",
    target_table="audit_log",
    payload_schema={"type": "object", "additionalProperties": True},
    actor_kinds_allowed=frozenset({"system"}),
    description=(
        "A magic-link consume attempt was rejected (token not found, "
        "already consumed, or expired)."
    ),
)

AUTH_SIGNUP_COMPLETED = EventTypeDefinition(
    event_type="auth.signup.completed",
    category="audit",
    target_table="audit_log",
    payload_schema={"type": "object", "additionalProperties": True},
    actor_kinds_allowed=frozenset({"system"}),
    description=(
        "A new account+user was self-signed-up via the magic-link "
        "consume flow (per phase-b2-plan.md §2 decision #6)."
    ),
)

AUTH_SESSION_REVOKED = EventTypeDefinition(
    event_type="auth.session.revoked",
    category="audit",
    target_table="audit_log",
    payload_schema={"type": "object", "additionalProperties": True},
    actor_kinds_allowed=frozenset({"user", "system"}),
    description="A session was revoked (user logout or admin action).",
)


_AUTH_DEFINITIONS = (
    AUTH_MAGIC_LINK_REQUESTED,
    AUTH_MAGIC_LINK_CONSUMED,
    AUTH_MAGIC_LINK_REJECTED,
    AUTH_SIGNUP_COMPLETED,
    AUTH_SESSION_REVOKED,
)


def register_auth_event_types() -> None:
    """Register all auth.* event definitions. Idempotent.

    Called once at module import. Tests that call
    `app.core.event_registry.reset_registry()` and then re-import this
    module pick up the registrations again without a duplicate error.
    """
    for definition in _AUTH_DEFINITIONS:
        try:
            register(definition)
        except DuplicateRegistrationError:
            continue


register_auth_event_types()
