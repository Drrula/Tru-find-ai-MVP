"""
Visibility signals.

Each signal is a pure function:
    (business_name, location) -> SignalResult

Per ADR-011 + ADR-048 (B.3.2): signal probes observe the data
deterministically; the per-vertical `weight` + the user-facing `gap`
copy come from the active vertical pack (resolved via
`app.vertical.registry`). The signal probe is the SCORING primitive;
the pack is the CONFIGURATION.

`SignalResult` shape stays unchanged (name, score, weight, gap) so
downstream consumers (the scoring engine, the existing tests in
test_signals.py) are insulated from where the per-vertical values
come from. Only the SOURCE of `weight` + `gap` changed.

To plug in a real data source later (Google Places API, web scraper,
LLM, etc.), replace the body of the signal function. The scoring
layer does not need to change; the pack contract does not change.
"""

from dataclasses import dataclass
from hashlib import md5
from typing import Any

from app.clients.google_business import fetch_google_business
from app.core.config import get_settings
from app.vertical.pack import VerticalPack
from app.vertical.registry import UnknownPackError, lookup

_DEFAULT_LOCALE = "en-US"


@dataclass
class SignalResult:
    name: str
    # Normalized 0.0–1.0 score for this signal.
    score: float
    # Relative importance in the final blended score (from the active pack).
    weight: float
    # Human-readable gap if the signal is weak; None if the business looks
    # healthy on this dimension (resolved from pack copy at probe time).
    gap: str | None


def _get_pack() -> VerticalPack:
    """Resolve the active vertical pack from the registry.

    Defensive fallback: if the pack isn't registered (test contexts
    that bypass `app.main`), call `load_default_packs()` to trigger
    side-effect registration, then retry.
    """
    pack_id = get_settings().default_vertical_pack_id
    try:
        return lookup(pack_id)
    except UnknownPackError:
        from app.vertical import load_default_packs

        load_default_packs()
        return lookup(pack_id)


def _gap(pack: VerticalPack, key: str, **format_args: Any) -> str | None:
    """Resolve a gap-copy template from the pack and apply format args.

    Returns the formatted string, or None if the key is missing from
    the pack's copy table (defensive — operators see the missing key
    via logs in a future hardening pass; for now, behave as 'no gap').
    """
    template = pack.copy().get((_DEFAULT_LOCALE, f"gap.{key}"))
    if template is None:
        return None
    return template.format(**format_args)


def _deterministic_hash(business_name: str, location: str, salt: str) -> int:
    """Stable pseudo-random value in [0, 99] so the same input returns the same mock result."""
    key = f"{business_name.lower().strip()}|{location.lower().strip()}|{salt}".encode()
    return int(md5(key).hexdigest(), 16) % 100


def website_presence(business_name: str, location: str) -> SignalResult:
    # TODO: replace with a real lookup (e.g. domain check, Google search, LLM probe).
    pack = _get_pack()
    has_website = _deterministic_hash(business_name, location, "website") > 30
    return SignalResult(
        name="website_presence",
        score=1.0 if has_website else 0.0,
        weight=pack.signal_weights().get("website_presence", 0.0),
        gap=None if has_website else _gap(pack, "no_website"),
    )


def google_business_presence(business_name: str, location: str) -> SignalResult:
    """
    Score the business's Google presence using real-shaped data from the client.

    Rules:
      - No listing            → score 0.0 (major penalty, kills the full 30% weight)
      - <10 reviews           → multiplicative penalty
      - rating > 4.5          → boost
      - rating < 4.0          → penalty
    """
    pack = _get_pack()
    weight = pack.signal_weights().get("google_business_presence", 0.0)

    data = fetch_google_business(business_name, location)

    if not data.exists:
        return SignalResult(
            name="google_business_presence",
            score=0.0,
            weight=weight,
            gap=_gap(pack, "no_listing"),
        )

    # Baseline for any verified listing.
    score = 0.7

    if data.rating > 4.5:
        score += 0.2  # boost
    elif data.rating < 4.0:
        score -= 0.2

    if data.review_count < 10:
        score *= 0.6  # multiplicative penalty for thin social proof

    score = max(0.0, min(1.0, score))

    # Issue substrings are still English-only inline here; per ADR-046 +
    # phase-b3-plan.md §10, fully locale-keyed sub-issue templates are
    # deferred until non-`'en-US'` locales activate.
    issues: list[str] = []
    if data.review_count < 10:
        issues.append(f"only {data.review_count} reviews")
    if data.rating < 4.0:
        issues.append(f"average rating {data.rating:.1f}")

    gap = (
        _gap(pack, "weak_listing", issues=" and ".join(issues))
        if issues
        else None
    )

    return SignalResult(
        name="google_business_presence",
        score=score,
        weight=weight,
        gap=gap,
    )


def content_signals(business_name: str, location: str) -> SignalResult:
    # TODO: replace with content audit (blog posts, schema.org markup, AI-generated summary quality).
    pack = _get_pack()
    raw = _deterministic_hash(business_name, location, "content")
    score = raw / 100.0
    if score >= 0.7:
        gap = None
    elif score >= 0.4:
        gap = _gap(pack, "content_thin")
    else:
        gap = _gap(pack, "content_almost_none")
    return SignalResult(
        name="content_signals",
        score=score,
        weight=pack.signal_weights().get("content_signals", 0.0),
        gap=gap,
    )


def reviews(business_name: str, location: str) -> SignalResult:
    # TODO: replace with real review aggregation (Google, Yelp, Trustpilot).
    pack = _get_pack()
    raw = _deterministic_hash(business_name, location, "reviews")
    score = raw / 100.0
    if score >= 0.7:
        gap = None
    elif score >= 0.4:
        gap = _gap(pack, "reviews_modest")
    else:
        gap = _gap(pack, "reviews_very_few")
    return SignalResult(
        name="reviews",
        score=score,
        weight=pack.signal_weights().get("reviews", 0.0),
        gap=gap,
    )


# Registry of signals to evaluate. Add or swap entries here when introducing new data sources.
SIGNALS = [
    website_presence,
    google_business_presence,
    content_signals,
    reviews,
]
