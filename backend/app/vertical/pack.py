"""`VerticalPack` Protocol — the seam between core scoring engine and
vertical configuration.

Per ADR-048 + phase-b3-plan.md §4. A vertical pack is described by
the methods below; the scoring engine reads through this surface
(directly from the pack instance in B.3.2, via repositories backed
by `vertical_*` tables in B.3.4+). Method signatures here are the
load-bearing contract — adding methods later is additive; changing
existing signatures requires a superseding ADR.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VerticalPack(Protocol):
    """A vertical's configuration surface.

    All methods return seed data: pure Python values that describe
    the pack's configuration. The engine reads through these methods
    (or, post-B.3.4, through repositories that read DB rows seeded
    from these methods at deploy time).
    """

    # --- Identity (read as attributes, not callables — matches the
    # pattern of `dataclass`-like Protocols).

    #: Canonical id; maps to source layout under
    #: `app/vertical/packs/<pack_id>/` AND to `vertical.pack_id` in the DB.
    pack_id: str

    #: Human-readable; maps to `vertical.display_name`.
    display_name: str

    #: Bump when the seed-shape changes. Maps to `vertical.schema_version`;
    #: a mismatch between pack value and DB row value triggers a
    #: documented re-seed operation (ADR-048).
    schema_version: int

    # --- Configuration surfaces

    def signal_weights(self) -> dict[str, float]:
        """`signal_name -> weight`. Weight is a non-negative float; the
        scoring engine normalizes by the sum so weights need not total
        1.0. Seed for `vertical_signal_weight` rows."""
        ...

    def copy(self) -> dict[tuple[str, str], str]:
        """`(locale, key) -> text`. Locale = IETF BCP 47 (e.g.
        `'en-US'`). Keys are dot-namespaced (e.g. `'gap.no_website'`,
        `'tier.strong.advice'`). Seed for `vertical_copy` rows. Per
        ADR-046, the schema is locale-keyed even when only one locale
        is populated."""
        ...

    def competitor_pool(self) -> list[str]:
        """Names used to synthesize comparator competitors in the
        response. Locale-bound to the pack's primary locale;
        multi-locale evolution rides with ADR-046 deployment phases.
        Seed for the competitor portion of `vertical_template`."""
        ...

    def tier_thresholds(self) -> list[tuple[int, str]]:
        """`[(min_score, tier_name), ...]` in DESCENDING threshold
        order. The scoring engine selects the first tier whose
        `min_score` the actual score meets or exceeds. Last entry
        should have `min_score == 0` (catch-all). Advice text for
        each tier lives in `copy()` under
        `('<locale>', 'tier.<tier_name>.advice')`. Seed for the tier
        portion of `vertical_template`."""
        ...

    def category_mapping(self) -> dict[str, str]:
        """`signal_name -> presentation_category`. Used by the
        response builder to project per-signal scores into the
        response's `category_scores` object. Presentation-only — does
        NOT affect scoring. Seed for the category portion of
        `vertical_template`."""
        ...
