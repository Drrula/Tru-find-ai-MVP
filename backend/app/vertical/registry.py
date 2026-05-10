"""In-process registry of vertical packs (per ADR-048).

Mirrors the registration semantics of `app/core/event_registry.py`
with one refinement: re-registering the SAME pack instance is a
silent no-op (matches the auth-events pattern). Re-registering a
DIFFERENT instance under an existing `pack_id` raises
`DuplicatePackError` — that's an operator error (two source modules
claim the same `pack_id`).

Lifecycle: pack modules register at import time via `register(pack)`;
consumers call `lookup(pack_id)` to retrieve the instance. The
scoring engine (B.3.2+) reads through this registry; the DB
repositories (B.3.4+) take over once `vertical_*` tables are seeded
and the engine switches to DB reads.
"""

from __future__ import annotations

from app.vertical.pack import VerticalPack


class UnknownPackError(KeyError):
    """Raised by `lookup()` when the `pack_id` is not registered."""


class DuplicatePackError(ValueError):
    """Raised by `register()` when a DIFFERENT pack instance attempts
    to claim a `pack_id` already held by another. Re-registering the
    same instance is a silent no-op (see `register()`)."""


_REGISTRY: dict[str, VerticalPack] = {}


def register(pack: VerticalPack) -> None:
    """Register a pack.

    Idempotent on the SAME instance: re-registration is a no-op (so
    tests that clear + reload pack modules don't blow up; matches the
    auth-events pattern). Re-registration of a DIFFERENT instance
    under an existing `pack_id` raises `DuplicatePackError`.
    """
    existing = _REGISTRY.get(pack.pack_id)
    if existing is None:
        _REGISTRY[pack.pack_id] = pack
        return
    if existing is pack:
        return  # idempotent
    raise DuplicatePackError(
        f"pack_id {pack.pack_id!r} already registered by a different "
        "instance — two source modules claim the same id."
    )


def lookup(pack_id: str) -> VerticalPack:
    """Look up a registered pack by id. Raises `UnknownPackError` if
    no pack with that id has been registered."""
    try:
        return _REGISTRY[pack_id]
    except KeyError as e:
        raise UnknownPackError(pack_id) from e


def all_packs() -> list[VerticalPack]:
    """Return every registered pack, sorted by `pack_id`."""
    return sorted(_REGISTRY.values(), key=lambda p: p.pack_id)


def reset_registry() -> None:
    """Test-only: clear the registry. Do not call from production code.

    Tests that need a clean registry should follow up by re-registering
    whatever packs they need (typically by calling the pack module's
    `register_pack()` function — see
    `app.vertical.packs.local_business_ai_visibility.register_pack`).
    """
    _REGISTRY.clear()
