"""Vertical packs (per ADR-011 + ADR-048).

A vertical pack is a self-contained configuration bundle: signal
weights, copy, competitor pool, tier thresholds, category mapping,
and (in later phases) prompts, workflows, outreach templates, and
KPIs. The `local_business_ai_visibility` reference pack carries
what's currently hardcoded in `app/domain/scoring.py` +
`app/domain/signals.py` — B.3.2 moves that content in; B.3.3 + B.3.4
make the runtime read from `vertical_*` DB tables, with the pack
module becoming the canonical seed for new deployments + tests.

Public surface:
- `app.vertical.pack.VerticalPack` — the Protocol
- `app.vertical.registry` — `register` / `lookup` / `all_packs`

ADR-048 lifecycle stages:
  source-time (B.3.1)  -> packs register at module import
  schema-time (B.3.3)  -> vertical_* tables migrate; pack seeds rows
  DB-runtime (B.3.4+)  -> engine reads from DB via repositories
"""
