"""Signal -> presentation-category mapping for the local-business
AI visibility pack.

Per ADR-048 (seed for the category-mapping portion of
`vertical_template`). PRESENTATION-ONLY — does not affect scoring;
controls how per-signal scores are projected into the response's
`category_scores` object.

Target categories are fixed by the response schema
(`CategoryScores`: ai_presence / seo_strength / authority /
performance). Future verticals that need different categories would
need either a flexible response shape or per-pack schema overrides
— both deferred per phase-b3-plan.md §10.
"""

from __future__ import annotations

CATEGORY_MAPPING: dict[str, str] = {
    "content_signals": "ai_presence",
    "website_presence": "seo_strength",
    "reviews": "authority",
    "google_business_presence": "performance",
}
