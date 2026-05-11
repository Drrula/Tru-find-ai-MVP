"""B.4.2 tests for the lead.* canonical event-type registrations.

Mirrors the auth-events registry tests from test_auth_domain.py.
"""

from __future__ import annotations

from app.core.event_registry import lookup
from app.domain.leads.events import register_lead_event_types


def test_lead_event_types_registered() -> None:
    """All three canonical lead.* types are in the in-process registry
    after importing the leads package."""
    import app.domain.leads  # noqa: F401 -- triggers side-effect registration

    for event_type in (
        "lead.lifecycle.transition",
        "lead.signal.observed",
        "lead.event.recorded",
    ):
        definition = lookup(event_type)
        assert definition.event_type == event_type
        assert definition.target_table == "lead_event"


def test_register_lead_event_types_is_idempotent() -> None:
    """Re-calling register_lead_event_types() does not raise -- needed
    because tests that reset_registry() and re-import the module
    would otherwise fail on DuplicateRegistrationError."""
    register_lead_event_types()
    register_lead_event_types()  # second call must not raise


def test_lead_lifecycle_transition_is_lifecycle_category() -> None:
    from app.domain.leads.events import LEAD_LIFECYCLE_TRANSITION

    assert LEAD_LIFECYCLE_TRANSITION.category == "lifecycle"
    assert LEAD_LIFECYCLE_TRANSITION.target_table == "lead_event"


def test_lead_signal_observed_is_enrichment_category() -> None:
    from app.domain.leads.events import LEAD_SIGNAL_OBSERVED

    assert LEAD_SIGNAL_OBSERVED.category == "enrichment"
    assert LEAD_SIGNAL_OBSERVED.target_table == "lead_event"


def test_lead_event_recorded_is_engagement_category() -> None:
    from app.domain.leads.events import LEAD_EVENT_RECORDED

    assert LEAD_EVENT_RECORDED.category == "engagement"
    assert LEAD_EVENT_RECORDED.target_table == "lead_event"


def test_all_lead_event_types_allow_full_actor_kind_set() -> None:
    """Lead events can be emitted by any actor kind from ADR-044's
    closed set."""
    from app.domain.leads.events import _LEAD_DEFINITIONS

    expected = frozenset({"user", "system", "webhook", "job", "ai"})
    for definition in _LEAD_DEFINITIONS:
        assert definition.actor_kinds_allowed == expected
