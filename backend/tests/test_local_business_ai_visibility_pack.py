"""B.3.2 tests for the `local_business_ai_visibility` vertical pack.

Pins the seed content so changes are deliberate, not silent. Per
ADR-048, this pack is the canonical source for what gets seeded
into `vertical_*` DB tables once B.3.3 lands.

The pack is registered at module import (via its `__init__.py`),
so these tests assert against the registered singleton.
"""

from __future__ import annotations

import pytest

from app.vertical.packs.local_business_ai_visibility import (
    PACK,
    register_pack,
)
from app.vertical.registry import lookup


# --- Identity


def test_pack_identity() -> None:
    """Pack identity matches what the engine + tests expect."""
    assert PACK.pack_id == "local_business_ai_visibility"
    assert PACK.display_name == "Local Business AI Visibility"
    assert PACK.schema_version == 1


def test_pack_registered() -> None:
    """Pack module's import-time `register_pack()` registers the singleton."""
    register_pack()  # idempotent — covers test contexts that cleared the registry
    assert lookup("local_business_ai_visibility") is PACK


# --- signal_weights


def test_signal_weights_cover_all_four_signal_names() -> None:
    weights = PACK.signal_weights()
    assert set(weights.keys()) == {
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    }


def test_signal_weights_sum_to_one() -> None:
    """The blending math expects normalized weights; sum=1.0 keeps the
    proportional contribution intuitive AND preserves the historical
    baseline score."""
    total = sum(PACK.signal_weights().values())
    assert total == pytest.approx(1.0)


def test_signal_weights_values_match_pre_b32_baseline() -> None:
    """B.3.2 preserves the exact weights that the pre-refactor code used.
    Changing any of these would change baseline scores -- which would
    fail test_known_baseline_score_inputs in test_signals.py."""
    weights = PACK.signal_weights()
    assert weights["website_presence"] == 0.30
    assert weights["google_business_presence"] == 0.30
    assert weights["content_signals"] == 0.20
    assert weights["reviews"] == 0.20


# --- copy


def test_copy_contains_all_seven_gap_keys() -> None:
    """Every signal failure mode has a corresponding gap.* copy entry."""
    copy = PACK.copy()
    for key in (
        "gap.no_website",
        "gap.no_listing",
        "gap.weak_listing",
        "gap.content_thin",
        "gap.content_almost_none",
        "gap.reviews_modest",
        "gap.reviews_very_few",
    ):
        assert ("en-US", key) in copy, f"missing gap key {key!r}"


def test_copy_contains_tier_advice_for_each_tier() -> None:
    """Every tier in tiers.TIERS has a matching `tier.<name>.advice` key."""
    copy = PACK.copy()
    for _, tier_name in PACK.tier_thresholds():
        key = f"tier.{tier_name}.advice"
        assert ("en-US", key) in copy, f"missing tier advice key {key!r}"


def test_copy_contains_summary_template_and_gap_clauses() -> None:
    copy = PACK.copy()
    assert ("en-US", "summary.template") in copy
    assert ("en-US", "summary.gap_count") in copy
    assert ("en-US", "summary.no_gaps") in copy


def test_copy_weak_listing_has_issues_placeholder() -> None:
    """`gap.weak_listing` is templated with an `{issues}` placeholder so
    `google_business_presence` can inject the dynamic issue list."""
    text = PACK.copy()[("en-US", "gap.weak_listing")]
    assert "{issues}" in text


def test_copy_summary_template_has_expected_placeholders() -> None:
    """Engine builds summary via .format() — placeholder mismatch would
    raise KeyError at scoring time."""
    text = PACK.copy()[("en-US", "summary.template")]
    for placeholder in ("{business_name}", "{tier}", "{score}", "{gap_clause}", "{advice}"):
        assert placeholder in text


def test_copy_locale_is_en_us_only_in_b32() -> None:
    """B.3.2 ships en-US only; future locales add additional entries."""
    locales = {locale for locale, _key in PACK.copy().keys()}
    assert locales == {"en-US"}


def test_copy_does_not_leak_trufindai_brand_string() -> None:
    """Per ADR-045: this pack describes the WORK, not the deployed brand."""
    for text in PACK.copy().values():
        assert "TruFindAI" not in text


# --- competitor_pool


def test_competitor_pool_preserves_pre_b32_order() -> None:
    """Competitor selection in scoring engine seeds from this list's
    order. Reordering would change baseline competitor output."""
    assert PACK.competitor_pool() == [
        "TopRank Local",
        "PrimeFind Pros",
        "Visible Edge",
        "FirstPage Co.",
        "Apex Listings",
        "BrightSearch",
    ]


def test_competitor_pool_returns_a_copy_not_the_internal_list() -> None:
    """Pack methods return fresh lists/dicts so callers can mutate without
    affecting the pack instance."""
    a = PACK.competitor_pool()
    b = PACK.competitor_pool()
    a.append("MUTATED")
    assert "MUTATED" not in b


# --- tier_thresholds


def test_tier_thresholds_descending_with_catch_all() -> None:
    """Thresholds must be in DESCENDING `min_score` order and end with
    a `(0, ...)` catch-all so `_resolve_tier` always returns a tier."""
    tiers = PACK.tier_thresholds()
    min_scores = [m for m, _ in tiers]
    assert min_scores == sorted(min_scores, reverse=True)
    assert tiers[-1][0] == 0


def test_tier_names_match_pre_b32_baseline() -> None:
    tiers = dict((m, n) for m, n in PACK.tier_thresholds())
    assert tiers[80] == "strong"
    assert tiers[50] == "moderate"
    assert tiers[0] == "weak"


# --- category_mapping


def test_category_mapping_covers_all_four_signal_names() -> None:
    mapping = PACK.category_mapping()
    assert set(mapping.keys()) == {
        "content_signals",
        "website_presence",
        "reviews",
        "google_business_presence",
    }


def test_category_mapping_values_match_response_schema_categories() -> None:
    """Response schema fixes the category names at `ai_presence`,
    `seo_strength`, `authority`, `performance`. Pack mapping must
    produce these category names."""
    mapping_values = set(PACK.category_mapping().values())
    assert mapping_values == {
        "ai_presence",
        "seo_strength",
        "authority",
        "performance",
    }


def test_category_mapping_matches_pre_b32_baseline() -> None:
    mapping = PACK.category_mapping()
    assert mapping["content_signals"] == "ai_presence"
    assert mapping["website_presence"] == "seo_strength"
    assert mapping["reviews"] == "authority"
    assert mapping["google_business_presence"] == "performance"
