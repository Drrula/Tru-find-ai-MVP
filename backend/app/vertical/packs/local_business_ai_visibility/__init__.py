"""Reference vertical pack: local-business AI visibility.

The pack name reflects the WORK (AI-visibility scoring for local
businesses). As of B.3.6, this pack ALSO carries deployment-brand
strings used by the auth flow (subject + body templates under
`auth.email.sign_in.*` keys in `copy.py`) because the
local-business-AI-visibility pack is currently TruFindAI's primary
vertical. If a future deployment uses the same work pack with a
different brand, ADR-045 anticipates a sibling brand-overlay pack
under `app/vertical/packs/<brand>_brand_*` carrying just the brand
strings, with this pack reduced to work-only.

Lifecycle (per ADR-048):
- B.3.1: stub registered.
- B.3.2: real content from sibling modules (work strings).
- B.3.3: `vertical_*` tables migrate; seed utility writes pack
  data into DB.
- B.3.4: engine reads from DB via repositories; this pack module
  remains the canonical SEED for new deployments + tests.
- B.3.6: auth email subject + body templates moved into this
  pack's copy (brand-overlay role acknowledged).
- B.4.6: lead_signal_weights() surface added (returns empty dict
  for B.4 -- real lead scoring activates in a later phase).
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
from app.vertical.packs.local_business_ai_visibility.lead_signal_weights import (
    LEAD_SIGNAL_WEIGHTS,
)
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

    def lead_signal_weights(self) -> dict[str, float]:
        return dict(LEAD_SIGNAL_WEIGHTS)


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
