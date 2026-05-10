"""Signal weights for the local-business AI visibility pack.

Per ADR-011 + ADR-048. Maps to `vertical_signal_weight` rows once
B.3.3 lands the schema; B.3.4 switches the runtime to DB reads.
Until then this module is the runtime source.

Weight sum is exactly 1.0 so the blended-score math is the
conventional probability-distribution form. Changing a weight here
requires updating the corresponding seed migration row when
`vertical_signal_weight` is populated, OR re-running the seed
operation (ADR-048 schema_version bump).
"""

from __future__ import annotations

WEIGHTS: dict[str, float] = {
    "website_presence": 0.30,
    "google_business_presence": 0.30,
    "content_signals": 0.20,
    "reviews": 0.20,
}
