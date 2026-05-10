"""Reference vertical pack: local-business AI visibility.

B.3.2 fills in the configuration surfaces from sibling modules.
The pack name reflects the WORK (AI-visibility scoring for local
businesses), not the deployed brand. Per ADR-045, brand strings
(e.g. "TruFindAI") do NOT appear in this pack — they belong in a
separate brand-overlay pack or in deployment-scoped `vertical_copy`
rows when the platform's identity finalizes.

Lifecycle (per ADR-048):
- B.3.1: stub registered.
- B.3.2 (this commit): real content from sibling modules.
- B.3.3: `vertical_*` tables migrate; seed utility writes pack
  data into DB.
- B.3.4: engine reads from DB via repositories; this pack module
  remains the canonical SEED for new deployments + tests.
"""

from __future__ import annotations

from app.vertical.pack import VerticalPack
from app.vertical.packs.local_business_ai_visibility.categories import (
    CATEGORY_MAPPING,
)
from app.vertical.packs.local_business_ai_visibility.competitors import (
    COMPETITOR_POOL,
)
from app.vertical.packs.local_business_ai_visibility.copy import COPY
from app.vertical.packs.local_business_ai_visibility.tiers import TIERS
from app.vertical.packs.local_business_ai_visibility.weights import WEIGHTS
from app.vertical.registry import register


class _LocalBusinessAIVisibilityPack:
    """Concrete `VerticalPack` for local-business AI-visibility scoring."""

    pack_id: str = "local_business_ai_visibility"
    display_name: str = "Local Business AI Visibility"
    schema_version: int = 1

    def signal_weights(self) -> dict[str, float]:
        return dict(WEIGHTS)

    def copy(self) -> dict[tuple[str, str], str]:
        return dict(COPY)

    def competitor_pool(self) -> list[str]:
        return list(COMPETITOR_POOL)

    def tier_thresholds(self) -> list[tuple[int, str]]:
        return list(TIERS)

    def category_mapping(self) -> dict[str, str]:
        return dict(CATEGORY_MAPPING)


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
