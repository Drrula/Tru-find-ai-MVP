"""Vertical packs (per ADR-011 + ADR-048).

A vertical pack is a self-contained configuration bundle: signal
weights, copy, competitor pool, tier thresholds, category mapping,
and (in later phases) prompts, workflows, outreach templates, and
KPIs. The `local_business_ai_visibility` reference pack carries
what was previously hardcoded in `app/domain/scoring.py` +
`app/domain/signals.py` — B.3.3 + B.3.4 will make the runtime read
from `vertical_*` DB tables, with the pack module remaining the
canonical seed for new deployments + tests.

Public surface:
- `app.vertical.pack.VerticalPack` — the Protocol
- `app.vertical.registry` — `register` / `lookup` / `all_packs`
- `load_default_packs()` — composition-root helper (below)

ADR-048 lifecycle stages:
  source-time (B.3.1)  -> packs register at module import
  schema-time (B.3.3)  -> vertical_* tables migrate; pack seeds rows
  DB-runtime (B.3.4+)  -> engine reads from DB via repositories
"""

from __future__ import annotations


def load_default_packs() -> None:
    """Import + register canonical vertical packs for this deployment.

    Called by `app.main` at startup. The composition root holds the
    list of canonical pack module imports here. Pack modules
    register themselves at import time (their `__init__.py`
    side-effect calls `register(...)`), so importing the module is
    sufficient.

    For multi-deployment / white-label scenarios where the canonical
    list differs, callers may load specific packs directly via
    `import app.vertical.packs.<name>` instead of going through this
    helper. This default function represents the platform's default
    deployment configuration.
    """
    # Side-effect imports; intentional. Ignore unused-import warnings.
    from app.vertical.packs import local_business_ai_visibility  # noqa: F401
