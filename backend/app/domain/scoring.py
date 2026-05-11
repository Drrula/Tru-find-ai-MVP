"""Scoring orchestrator: runs the signal registry and blends the results.

Per ADR-011 + ADR-048 (B.3.2): the engine is in core; the configuration
(weights, copy, competitor pool, tier thresholds, category mapping,
summary template) comes from the active vertical pack via
`app.vertical.registry`. Future commits (B.3.4) swap the runtime
source from the pack module to `vertical_*` DB rows via repositories;
the engine signature here does not change.
"""

from hashlib import md5

from app.core.config import get_settings
from app.schemas import AnalyzeResponse, CategoryScores, Competitor
from app.domain.signals import SIGNALS, SignalResult
from app.vertical.db_pack import get_active_pack
from app.vertical.pack import VerticalPack
from app.vertical.registry import UnknownPackError

_DEFAULT_LOCALE = "en-US"


def _get_pack() -> VerticalPack:
    """Resolve the active vertical pack.

    `app.vertical.db_pack.get_active_pack` returns the DB-backed pack
    when the FastAPI lifespan populated the cache at startup (per
    ADR-048 stage "DB-runtime"); otherwise falls back to the
    source-module pack via the registry. Test contexts that bypass
    `app.main` get the source-module fallback automatically.

    Defensive: if neither cache nor registry has the pack (configuration
    error), call `load_default_packs()` once and retry.
    """
    pack_id = get_settings().default_vertical_pack_id
    try:
        return get_active_pack(pack_id)
    except UnknownPackError:
        from app.vertical import load_default_packs

        load_default_packs()
        return get_active_pack(pack_id)


def _blended_score(results: list[SignalResult]) -> int:
    total_weight = sum(r.weight for r in results) or 1.0
    weighted = sum(r.score * r.weight for r in results)
    return round((weighted / total_weight) * 100)


def _resolve_tier(score: int, thresholds: list[tuple[int, str]]) -> str:
    """Select the first tier whose `min_score` is met. Thresholds expected
    in DESCENDING order with a `(0, ...)` catch-all last."""
    for min_score, tier_name in thresholds:
        if score >= min_score:
            return tier_name
    return "unknown"  # defensive — should not occur with a well-formed pack


def _build_summary(
    business_name: str, score: int, gap_count: int, pack: VerticalPack
) -> str:
    copy = pack.copy()
    tier = _resolve_tier(score, pack.tier_thresholds())
    advice = copy.get((_DEFAULT_LOCALE, f"tier.{tier}.advice"), "")
    gap_clause = (
        copy[(_DEFAULT_LOCALE, "summary.gap_count")].format(count=gap_count)
        if gap_count
        else copy[(_DEFAULT_LOCALE, "summary.no_gaps")]
    )
    template = copy[(_DEFAULT_LOCALE, "summary.template")]
    return template.format(
        business_name=business_name,
        tier=tier,
        score=score,
        gap_clause=gap_clause,
        advice=advice,
    )


def _build_category_scores(
    results: list[SignalResult], pack: VerticalPack
) -> CategoryScores:
    mapping = pack.category_mapping()
    by_category = {
        mapping[r.name]: round(r.score * 100)
        for r in results
        if r.name in mapping
    }
    # Target category names are fixed by the response schema; future
    # verticals needing different categories require a schema change.
    return CategoryScores(
        ai_presence=by_category.get("ai_presence", 0),
        seo_strength=by_category.get("seo_strength", 0),
        authority=by_category.get("authority", 0),
        performance=by_category.get("performance", 0),
    )


def _generate_competitors(
    business_name: str, location: str, score: int, pack: VerticalPack
) -> list[Competitor]:
    seed = int(
        md5(
            f"{business_name.lower().strip()}|{location.lower().strip()}|competitors".encode()
        ).hexdigest(),
        16,
    )
    pool = list(pack.competitor_pool())
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
    pack = _get_pack()
    results = [signal(business_name, location) for signal in SIGNALS]
    score = _blended_score(results)
    gaps = [r.gap for r in results if r.gap]
    summary = _build_summary(business_name, score, len(gaps), pack)
    category_scores = _build_category_scores(results, pack)
    competitors = _generate_competitors(business_name, location, score, pack)
    return AnalyzeResponse(
        score=score,
        gaps=gaps,
        summary=summary,
        category_scores=category_scores,
        competitors=competitors,
        trade=trade,
    )
