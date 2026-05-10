"""User-visible copy for the local-business AI visibility pack.

Per ADR-011 + ADR-046 (locale-keyed) + ADR-048 (seed for
`vertical_copy`). Keys are dot-namespaced; locales are IETF BCP 47.

B.3.2 ships `'en-US'` only. Future locales add additional entries
under the same keys; the resolution path in the scoring engine
selects by `Settings.default_locale` (added in a future commit when
locale-aware deployments are activated).

Per ADR-045: no `"TruFindAI"` brand strings appear here — this pack
describes the WORK (local-business AI-visibility scoring), not the
deployed brand. Brand-overlay strings (subject lines, marketing
copy) would live in a separate brand-overlay pack or in
deployment-scoped `vertical_copy` rows when the platform's identity
finalizes.
"""

from __future__ import annotations

COPY: dict[tuple[str, str], str] = {
    # --- Gap descriptions (one per signal failure mode)
    ("en-US", "gap.no_website"): (
        "No website detected — create a simple branded site with your "
        "services and location."
    ),
    ("en-US", "gap.no_listing"): (
        "No Google Business Profile found — claim and verify a listing "
        "to appear on Maps and local search."
    ),
    ("en-US", "gap.weak_listing"): (
        "Google Business Profile is weak — {issues}. Build review "
        "velocity and respond to feedback to lift local rankings."
    ),
    ("en-US", "gap.content_thin"): (
        "Content is thin — add service pages, FAQs, and "
        "location-specific landing pages to improve discoverability."
    ),
    ("en-US", "gap.content_almost_none"): (
        "Almost no indexable content — publish core service pages and "
        "structured data so AI assistants can cite you."
    ),
    ("en-US", "gap.reviews_modest"): (
        "Review volume is modest — ask recent customers for Google "
        "reviews to build social proof."
    ),
    ("en-US", "gap.reviews_very_few"): (
        "Very few reviews — set up an automated review-request flow; "
        "reviews are a top-3 ranking factor for local search."
    ),

    # --- Tier advice (one per tier_name in tiers.TIERS)
    ("en-US", "tier.strong.advice"): (
        "Maintain momentum and focus on incremental improvements."
    ),
    ("en-US", "tier.moderate.advice"): (
        "A few targeted fixes could meaningfully lift discoverability."
    ),
    ("en-US", "tier.weak.advice"): (
        "Significant visibility work is needed before AI assistants and "
        "search engines will reliably surface this business."
    ),

    # --- Summary template + gap-count clauses
    ("en-US", "summary.template"): (
        "{business_name} has a {tier} AI visibility profile "
        "(score {score}/100). {gap_clause} {advice}"
    ),
    ("en-US", "summary.gap_count"): "{count} gap(s) identified.",
    ("en-US", "summary.no_gaps"): "No major gaps detected.",
}
