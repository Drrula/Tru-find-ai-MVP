"""
Visibility signals.

Each signal is a pure function:
    (business_name, location) -> SignalResult

To plug in a real data source later (Google Places API, web scraper, LLM, etc.),
replace the body of the signal function. The scoring layer does not need to change.
"""

from dataclasses import dataclass
from hashlib import md5

from app.clients.google_business import fetch_google_business


@dataclass
class SignalResult:
    name: str
    # Normalized 0.0–1.0 score for this signal.
    score: float
    # Relative importance in the final blended score.
    weight: float
    # Human-readable gap if the signal is weak; None if the business looks healthy on this dimension.
    gap: str | None


def _deterministic_hash(business_name: str, location: str, salt: str) -> int:
    """Stable pseudo-random value in [0, 99] so the same input returns the same mock result."""
    key = f"{business_name.lower().strip()}|{location.lower().strip()}|{salt}".encode()
    return int(md5(key).hexdigest(), 16) % 100


def website_presence(business_name: str, location: str) -> SignalResult:
    # TODO: replace with a real lookup (e.g. domain check, Google search, LLM probe).
    has_website = _deterministic_hash(business_name, location, "website") > 30
    return SignalResult(
        name="website_presence",
        score=1.0 if has_website else 0.0,
        weight=0.30,
        gap=None if has_website else "No website detected — create a simple branded site with your services and location.",
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
    data = fetch_google_business(business_name, location)

    if not data.exists:
        return SignalResult(
            name="google_business_presence",
            score=0.0,
            weight=0.30,
            gap="No Google Business Profile found — claim and verify a listing to appear on Maps and local search.",
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

    issues: list[str] = []
    if data.review_count < 10:
        issues.append(f"only {data.review_count} reviews")
    if data.rating < 4.0:
        issues.append(f"average rating {data.rating:.1f}")

    gap = (
        "Google Business Profile is weak — "
        + " and ".join(issues)
        + ". Build review velocity and respond to feedback to lift local rankings."
    ) if issues else None

    return SignalResult(name="google_business_presence", score=score, weight=0.30, gap=gap)


def content_signals(business_name: str, location: str) -> SignalResult:
    # TODO: replace with content audit (blog posts, schema.org markup, AI-generated summary quality).
    raw = _deterministic_hash(business_name, location, "content")
    score = raw / 100.0
    if score >= 0.7:
        gap = None
    elif score >= 0.4:
        gap = "Content is thin — add service pages, FAQs, and location-specific landing pages to improve discoverability."
    else:
        gap = "Almost no indexable content — publish core service pages and structured data so AI assistants can cite you."
    return SignalResult(name="content_signals", score=score, weight=0.20, gap=gap)


def reviews(business_name: str, location: str) -> SignalResult:
    # TODO: replace with real review aggregation (Google, Yelp, Trustpilot).
    raw = _deterministic_hash(business_name, location, "reviews")
    score = raw / 100.0
    if score >= 0.7:
        gap = None
    elif score >= 0.4:
        gap = "Review volume is modest — ask recent customers for Google reviews to build social proof."
    else:
        gap = "Very few reviews — set up an automated review-request flow; reviews are a top-3 ranking factor for local search."
    return SignalResult(name="reviews", score=score, weight=0.20, gap=gap)


# Registry of signals to evaluate. Add or swap entries here when introducing new data sources.
SIGNALS = [
    website_presence,
    google_business_presence,
    content_signals,
    reviews,
]
