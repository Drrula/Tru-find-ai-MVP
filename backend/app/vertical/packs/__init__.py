"""Vertical pack source modules.

One subpackage per pack (per ADR-048):
- `local_business_ai_visibility/` — reference pack; carries content
  that's currently hardcoded in `app/domain/scoring.py` +
  `app/domain/signals.py`. B.3.2 moves that content here; B.3.1
  registers an empty stub so the registry contract is exercised.

New verticals add a sibling subpackage + (B.3.3+) a migration that
seeds `vertical_*` rows.
"""
