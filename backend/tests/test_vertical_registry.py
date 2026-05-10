"""B.3.1 tests for the vertical-pack registry + Protocol + reference pack.

Verifies:
  - `VerticalPack` Protocol has the documented attribute + method shape.
  - `register` / `lookup` / `all_packs` work + raise the documented errors.
  - Re-registering the SAME instance is a silent no-op.
  - Re-registering a DIFFERENT instance with the SAME pack_id raises.
  - `reset_registry` clears state.
  - Reference pack `local_business_ai_visibility` is registered after
    importing `app.vertical.packs.local_business_ai_visibility`.
  - Reference pack satisfies the runtime-checkable Protocol.
  - Reference pack returns empty seed data in B.3.1 (real content
    arrives in B.3.2).

The registry is process-global, so tests that mutate it use the
`fresh_registry` fixture to snapshot + restore — otherwise the
local-business pack registration would leak between tests.
"""

from __future__ import annotations

from typing import Iterator

import pytest


@pytest.fixture
def fresh_registry() -> Iterator[None]:
    """Snapshot the registry, run the test against an empty one, restore.

    Use in tests that mutate the registry (register a fake pack,
    reset, etc.) so the production reference pack remains registered
    for subsequent tests.
    """
    from app.vertical import registry as r

    snapshot = dict(r._REGISTRY)
    r._REGISTRY.clear()
    try:
        yield
    finally:
        r._REGISTRY.clear()
        r._REGISTRY.update(snapshot)


# --- Protocol shape


def test_vertical_pack_protocol_has_attribute_and_method_surface() -> None:
    """The Protocol declares the documented attributes + methods."""
    from app.vertical.pack import VerticalPack

    # Annotations cover the attribute portion (pack_id, display_name,
    # schema_version). hasattr on the Protocol class itself isn't a
    # reliable check for Protocols, so we inspect the annotations dict.
    annotations = VerticalPack.__annotations__
    assert "pack_id" in annotations
    assert "display_name" in annotations
    assert "schema_version" in annotations

    # Methods exist as callables on the Protocol.
    for method_name in (
        "signal_weights",
        "copy",
        "competitor_pool",
        "tier_thresholds",
        "category_mapping",
    ):
        assert hasattr(VerticalPack, method_name)


def test_vertical_pack_protocol_is_runtime_checkable() -> None:
    """`@runtime_checkable` lets isinstance(...) work for duck-typed packs."""
    from app.vertical.pack import VerticalPack
    from app.vertical.packs.local_business_ai_visibility import PACK

    assert isinstance(PACK, VerticalPack)


# --- register / lookup happy paths


def test_register_and_lookup_round_trip(fresh_registry: None) -> None:
    from app.vertical.packs.local_business_ai_visibility import (
        PACK,
        register_pack,
    )
    from app.vertical.registry import lookup

    register_pack()  # populate the (currently empty) registry
    assert lookup("local_business_ai_visibility") is PACK


def test_lookup_unknown_pack_raises(fresh_registry: None) -> None:
    from app.vertical.registry import UnknownPackError, lookup

    with pytest.raises(UnknownPackError, match="does_not_exist"):
        lookup("does_not_exist")


def test_all_packs_sorted_by_pack_id(fresh_registry: None) -> None:
    """`all_packs()` returns every registered pack, sorted by `pack_id`."""
    from app.vertical.registry import all_packs, register

    class _Pack:
        def __init__(self, pid: str) -> None:
            self.pack_id = pid
            self.display_name = pid.upper()
            self.schema_version = 1

        def signal_weights(self) -> dict[str, float]:
            return {}

        def copy(self) -> dict[tuple[str, str], str]:
            return {}

        def competitor_pool(self) -> list[str]:
            return []

        def tier_thresholds(self) -> list[tuple[int, str]]:
            return []

        def category_mapping(self) -> dict[str, str]:
            return {}

    register(_Pack("zeta"))
    register(_Pack("alpha"))
    register(_Pack("mu"))

    ids = [p.pack_id for p in all_packs()]
    assert ids == ["alpha", "mu", "zeta"]


# --- idempotency / duplicate handling


def test_re_registering_same_instance_is_silent(fresh_registry: None) -> None:
    """Tests that clear + re-import pack modules need this contract."""
    from app.vertical.packs.local_business_ai_visibility import (
        PACK,
        register_pack,
    )
    from app.vertical.registry import lookup

    register_pack()
    register_pack()  # must not raise
    register_pack()
    assert lookup("local_business_ai_visibility") is PACK


def test_re_registering_different_instance_raises(
    fresh_registry: None,
) -> None:
    """Operator error: two source modules claim the same `pack_id`."""
    from app.vertical.registry import DuplicatePackError, register

    class _PackA:
        pack_id = "claimed"
        display_name = "A"
        schema_version = 1

        def signal_weights(self) -> dict[str, float]:
            return {}

        def copy(self) -> dict[tuple[str, str], str]:
            return {}

        def competitor_pool(self) -> list[str]:
            return []

        def tier_thresholds(self) -> list[tuple[int, str]]:
            return []

        def category_mapping(self) -> dict[str, str]:
            return {}

    class _PackB:
        pack_id = "claimed"  # same id, different instance
        display_name = "B"
        schema_version = 1

        def signal_weights(self) -> dict[str, float]:
            return {}

        def copy(self) -> dict[tuple[str, str], str]:
            return {}

        def competitor_pool(self) -> list[str]:
            return []

        def tier_thresholds(self) -> list[tuple[int, str]]:
            return []

        def category_mapping(self) -> dict[str, str]:
            return {}

    register(_PackA())
    with pytest.raises(DuplicatePackError, match="claimed"):
        register(_PackB())


# --- reset_registry


def test_reset_registry_clears(fresh_registry: None) -> None:
    from app.vertical.packs.local_business_ai_visibility import register_pack
    from app.vertical.registry import (
        UnknownPackError,
        all_packs,
        lookup,
        reset_registry,
    )

    register_pack()
    assert lookup("local_business_ai_visibility") is not None

    reset_registry()
    assert all_packs() == []
    with pytest.raises(UnknownPackError):
        lookup("local_business_ai_visibility")


# --- Reference pack registers on import (without fresh_registry — the
# production state is what we're asserting)


def test_reference_pack_registers_on_import() -> None:
    """Importing the production reference-pack module registers it.

    Note: this test relies on the registry's actual production state.
    The `fresh_registry` fixture is NOT used here, because clearing
    the registry would invalidate the test's premise.
    """
    import app.vertical.packs.local_business_ai_visibility  # noqa: F401
    from app.vertical.registry import lookup

    pack = lookup("local_business_ai_visibility")
    assert pack.pack_id == "local_business_ai_visibility"
    assert pack.display_name == "Local Business AI Visibility"
    assert pack.schema_version == 1


def test_reference_pack_returns_empty_seed_data() -> None:
    """B.3.1: stub returns empty values. B.3.2 fills these in."""
    from app.vertical.registry import lookup

    pack = lookup("local_business_ai_visibility")
    assert pack.signal_weights() == {}
    assert pack.copy() == {}
    assert pack.competitor_pool() == []
    assert pack.tier_thresholds() == []
    assert pack.category_mapping() == {}
