"""Tier thresholds for the local-business AI visibility pack.

Per ADR-048 (seed for the tier portion of `vertical_template`). The
engine matches the first tier whose `min_score` the actual score
meets or exceeds, so entries are in DESCENDING `min_score` order
with a catch-all `(0, ...)` last.

Each tier_name has a corresponding `tier.<tier_name>.advice` key in
copy.py; adding a tier here requires adding the matching advice
string.
"""

from __future__ import annotations

TIERS: list[tuple[int, str]] = [
    (80, "strong"),
    (50, "moderate"),
    (0, "weak"),
]
