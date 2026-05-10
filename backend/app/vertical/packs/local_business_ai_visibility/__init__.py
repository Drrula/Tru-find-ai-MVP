"""Reference vertical pack: local-business AI visibility.

B.3.1 ships this as a STUB — the pack registers itself and satisfies
the `VerticalPack` Protocol, but every configuration surface returns
an empty value. The real content (weights, copy, competitor pool,
tier thresholds, category mapping) moves in B.3.2 — the scoring
engine still reads from `app/domain/scoring.py` + `signals.py` until
that commit lands.

Why a stub first: B.3.1's contract is "registry seam exists +
reference pack registers". Moving content is its own commit (B.3.2)
so the verify-before-commit baseline stays clear at each step.

The pack name `local_business_ai_visibility` is intentionally
descriptive of the WORK (AI-visibility scoring for local businesses),
not the deployed brand (TruFindAI). Per ADR-045, the platform's
identity is `platform_core` and TruFindAI is a deployed brand string
that surfaces through `vertical_copy` once content lands. A future
commit may add a `trufindai_branded_overlay` pack or similar if
brand-specific overrides are needed; for now, the work itself is
brand-agnostic.
"""

from __future__ import annotations

from app.vertical.pack import VerticalPack
from app.vertical.registry import register


class _LocalBusinessAIVisibilityPack:
    """Stub implementation. B.3.2 fills in the surfaces."""

    pack_id: str = "local_business_ai_visibility"
    display_name: str = "Local Business AI Visibility"
    schema_version: int = 1

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


#: Module-level singleton; the registry holds a reference to this instance.
PACK: VerticalPack = _LocalBusinessAIVisibilityPack()


def register_pack() -> None:
    """Idempotently register this pack with `app.vertical.registry`.

    Called once at module import. Tests that have cleared the registry
    via `reset_registry()` can call this directly to re-register
    without forcing a module reload (matches the auth-events pattern).
    """
    register(PACK)


register_pack()
