"""Competitor pool for the local-business AI visibility pack.

Per ADR-048 (seed for the competitor portion of `vertical_template`).
Order matters: the engine seeds the deterministic competitor
selection from this list, so reordering changes the baseline score
output for `_generate_competitors`.

The names are presentational only — they're synthesized comparator
labels for the response, not real-business lookups. Future locales
would supply locale-appropriate names via additional pools keyed by
locale.
"""

from __future__ import annotations

COMPETITOR_POOL: list[str] = [
    "TopRank Local",
    "PrimeFind Pros",
    "Visible Edge",
    "FirstPage Co.",
    "Apex Listings",
    "BrightSearch",
]
