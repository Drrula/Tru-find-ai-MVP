"""User-visible copy for the local-business AI visibility pack.

Per ADR-011 + ADR-046 (locale-keyed) + ADR-048 (seed for
`vertical_copy`). Keys are dot-namespaced; locales are IETF BCP 47.

B.3.2 ships `'en-US'` only. Future locales add additional entries
under the same keys; the resolution path selects by
`Settings.default_locale` (added in a future commit when
locale-aware deployments are activated).

Dual role per phase-b3-plan.md §3:
- WORK strings (gap descriptions, tier advice, summary template) —
  describe what local-business AI-visibility scoring produces.
- BRAND-overlay strings (auth email subject + body, future
  marketing copy) — the TruFindAI brand. Brand strings live here
  because the local-business-AI-visibility pack is currently
  TruFindAI's primary vertical; if a future deployment uses the
  same work pack with a different brand, a separate
  brand-overlay pack would carry these strings instead (per
  ADR-045's anticipated `app/vertical/packs/<brand>_brand_*`
  pattern).
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

    # --- Auth email templates (B.3.6 — moved from app/domain/auth/issue.py
    # per ADR-045 + phase-b3-plan.md §9. The brand "TruFindAI" appears
    # here as a deployed-brand string; a future brand-overlay pack
    # could supply different values for a different deployment of the
    # same work pack.)
    ("en-US", "auth.email.sign_in.subject"): "Your TruFindAI sign-in link",
    ("en-US", "auth.email.sign_in.body"): (
        "Click this link to sign in to TruFindAI:\n\n{link}\n\n"
        "The link expires in {minutes} minutes. If you did not request "
        "this, you can safely ignore this email."
    ),
}
