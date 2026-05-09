"""Scoring orchestrator: runs the signal registry and blends the results."""

from hashlib import md5

from app.schemas import AnalyzeResponse, CategoryScores, Competitor
from app.signals import SIGNALS, SignalResult

# Map internal signal names to the four presentation categories the
# Results Page renders. This is a presentation mapping, not a scoring change —
# weights and signal logic are untouched.
SIGNAL_TO_CATEGORY = {
    "content_signals": "ai_presence",
    "website_presence": "seo_strength",
    "reviews": "authority",
    "google_business_presence": "performance",
}

COMPETITOR_POOL = [
    "TopRank Local",
    "PrimeFind Pros",
    "Visible Edge",
    "FirstPage Co.",
    "Apex Listings",
    "BrightSearch",
]


def _blended_score(results: list[SignalResult]) -> int:
    total_weight = sum(r.weight for r in results) or 1.0
    weighted = sum(r.score * r.weight for r in results)
    return round((weighted / total_weight) * 100)


def _build_summary(business_name: str, score: int, gap_count: int) -> str:
    if score >= 80:
        tier = "strong"
        advice = "Maintain momentum and focus on incremental improvements."
    elif score >= 50:
        tier = "moderate"
        advice = "A few targeted fixes could meaningfully lift discoverability."
    else:
        tier = "weak"
        advice = "Significant visibility work is needed before AI assistants and search engines will reliably surface this business."
    gap_clause = f"{gap_count} gap(s) identified." if gap_count else "No major gaps detected."
    return f"{business_name} has a {tier} AI visibility profile (score {score}/100). {gap_clause} {advice}"


def _build_category_scores(results: list[SignalResult]) -> CategoryScores:
    by_category = {
        SIGNAL_TO_CATEGORY[r.name]: round(r.score * 100)
        for r in results
        if r.name in SIGNAL_TO_CATEGORY
    }
    return CategoryScores(
        ai_presence=by_category.get("ai_presence", 0),
        seo_strength=by_category.get("seo_strength", 0),
        authority=by_category.get("authority", 0),
        performance=by_category.get("performance", 0),
    )


def _generate_competitors(business_name: str, location: str, score: int) -> list[Competitor]:
    seed = int(
        md5(f"{business_name.lower().strip()}|{location.lower().strip()}|competitors".encode()).hexdigest(),
        16,
    )
    pool = list(COMPETITOR_POOL)
    names: list[str] = []
    s = seed
    for _ in range(3):
        names.append(pool.pop(s % len(pool)))
        s //= max(len(pool), 1) or 1
        if s == 0:
            s = seed
    bumps: list[int] = []
    s = seed
    for _ in range(3):
        bumps.append(5 + (s % 11))  # +5..+15
        s //= 11
        if s == 0:
            s = seed >> 1
    return [Competitor(name=n, score=min(100, score + b)) for n, b in zip(names, bumps)]


def analyze(business_name: str, location: str, trade: str | None = None) -> AnalyzeResponse:
    results = [signal(business_name, location) for signal in SIGNALS]
    score = _blended_score(results)
    gaps = [r.gap for r in results if r.gap]
    summary = _build_summary(business_name, score, len(gaps))
    category_scores = _build_category_scores(results)
    competitors = _generate_competitors(business_name, location, score)
    return AnalyzeResponse(
        score=score,
        gaps=gaps,
        summary=summary,
        category_scores=category_scores,
        competitors=competitors,
        trade=trade,
    )
