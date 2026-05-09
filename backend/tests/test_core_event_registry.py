"""Smoke tests for the event type registry (B.0.2).

Per ADR-044, ADR-040.
"""

from __future__ import annotations

import pytest


def test_seed_types_registered() -> None:
    from app.core.event_registry import lookup

    d = lookup("system.app.started")
    assert d.category == "system"
    assert d.target_table == "log_only"
    assert "system" in d.actor_kinds_allowed
    assert d.schema_version == 1


def test_lookup_unknown_raises() -> None:
    from app.core.event_registry import UnknownEventTypeError, lookup

    with pytest.raises(UnknownEventTypeError):
        lookup("does.not.exist")


def test_register_duplicate_raises() -> None:
    from app.core.event_registry import (
        DuplicateRegistrationError,
        EventTypeDefinition,
        register,
    )

    spec = EventTypeDefinition(
        event_type="system.app.started",  # already seeded
        category="system",
        target_table="log_only",
        payload_schema={"type": "object"},
        actor_kinds_allowed=frozenset({"system"}),
    )
    with pytest.raises(DuplicateRegistrationError):
        register(spec)


def test_register_unknown_category_raises() -> None:
    from app.core.event_registry import EventTypeDefinition, register

    spec = EventTypeDefinition(
        event_type="x.test_unknown_category",
        category="not_a_category",
        target_table="log_only",
        payload_schema={"type": "object"},
        actor_kinds_allowed=frozenset({"system"}),
    )
    with pytest.raises(ValueError, match="category"):
        register(spec)


def test_register_unknown_target_table_raises() -> None:
    from app.core.event_registry import EventTypeDefinition, register

    spec = EventTypeDefinition(
        event_type="x.test_unknown_target",
        category="system",
        target_table="invented_table",
        payload_schema={"type": "object"},
        actor_kinds_allowed=frozenset({"system"}),
    )
    with pytest.raises(ValueError, match="target_table"):
        register(spec)


def test_all_types_includes_seeds() -> None:
    from app.core.event_registry import all_types

    types = [d.event_type for d in all_types()]
    assert "system.app.started" in types


def test_categories_align_with_adr040_plus_system() -> None:
    """Sanity-check the category seed list against ADR-040 + system/audit/billing/compliance."""
    from app.core.event_registry import CATEGORIES

    # ADR-040 lead categories (Q10 in LOCK-SUMMARY.md)
    adr040_categories = {
        "engagement",
        "intent",
        "enrichment",
        "ai",
        "attribution",
        "communication",
        "lifecycle",
    }
    # Plus orchestration (reserved per ADR-040 Q15) and projection-table classes
    extra = {"orchestration", "system", "audit", "billing", "compliance"}

    assert adr040_categories.issubset(CATEGORIES)
    assert extra.issubset(CATEGORIES)
