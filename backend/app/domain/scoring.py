"""Scoring orchestrator: runs the signal registry and blends the results.

Per ADR-011 + ADR-048 (B.3.2): the engine is in core; the configuration
(weights, copy, competitor pool, tier thresholds, category mapping,
summary template) comes from the active vertical pack via
`app.vertical.registry`. Future commits (B.3.4) swap the runtime
source from the pack module to `vertical_*` DB rows via repositories;
the engine signature here does not change.

B.6B.1 refactor (2026-05-12): introduced `run_legacy_scoring()` as
the single-source-of-truth runner producing both `AnalyzeResponse`
and the intermediate `SignalResults`. `analyze()` is now a thin
one-liner over the runner. `_blended_score` math moved into
`_compute_blended_score`; `_blended_score` itself remains as a
compatibility shim (per phase-b6b-plan.md §2 decision #8 -- shim
stays for one phase; remove in B.6C+). Behavior byte-identical
to pre-B.6B.
"""

from dataclasses import dataclass
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


def _compute_blended_score(results: list[SignalResult]) -> int:
    """Legacy blended-score math. Behavior byte-identical to the
    pre-B.6B `_blended_score` function (which is now a thin shim
    over this helper -- see below).

    Per phase-b6b-plan.md §4.4: this is the single math seam used
    by `run_legacy_scoring()` (and by the `_blended_score` shim
    until B.6C+ retires the shim)."""
    total_weight = sum(r.weight for r in results) or 1.0
    weighted = sum(r.score * r.weight for r in results)
    return round((weighted / total_weight) * 100)


def _blended_score(results: list[SignalResult]) -> int:
    """Compatibility shim. Remove in B.6C after live shadowing
    stabilizes (per phase-b6b-plan.md §2 decision #8: operational
    certainty > cleanup purity during production-reach phases).

    Delegates unchanged to `_compute_blended_score`. Existing
    callers (none today, but the symbol may be imported by future
    or external code) continue to resolve through this name."""
    return _compute_blended_score(results)


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


@dataclass(frozen=True)
class LegacyScoringResult:
    """Combined return value of `run_legacy_scoring`: the
    user-facing AnalyzeResponse AND the intermediate SignalResults
    that produced it. Frozen so callers cannot mutate after
    construction.

    The dual return enables future callers (e.g. B.6B shadow path
    or B.6C convergence) to share one SIGNAL run between response
    shaping and downstream consumers without re-running probes.
    `analyze()` only consumes `.response`.

    Per phase-b6b-plan.md §4.4.
    """

    response: AnalyzeResponse
    signal_results: list[SignalResult]


def run_legacy_scoring(
    business_name: str,
    location: str,
    trade: str | None = None,
) -> LegacyScoringResult:
    """Single-source-of-truth runner for the legacy scoring
    pipeline. Produces both the user-facing AnalyzeResponse and
    the intermediate `SignalResults` that fed into it.

    Behavior byte-identical to the pre-B.6B body of `analyze()`.
    The refactor is purely structural -- the math, the pack
    resolution, the response shape, and every helper call run in
    the same order with the same arguments. The only change is
    that the intermediate `results` list is now ALSO returned.

    Per phase-b6b-plan.md §4.4 + locked decision #8 (refactor
    creates a seam; no semantic change).
    """
    pack = _get_pack()
    results = [signal(business_name, location) for signal in SIGNALS]
    score = _compute_blended_score(results)
    gaps = [r.gap for r in results if r.gap]
    summary = _build_summary(business_name, score, len(gaps), pack)
    category_scores = _build_category_scores(results, pack)
    competitors = _generate_competitors(business_name, location, score, pack)
    response = AnalyzeResponse(
        score=score,
        gaps=gaps,
        summary=summary,
        category_scores=category_scores,
        competitors=competitors,
        trade=trade,
    )
    return LegacyScoringResult(response=response, signal_results=results)


def analyze(
    business_name: str, location: str, trade: str | None = None
) -> AnalyzeResponse:
    """Public sync API. Signature + return type byte-identical to
    pre-B.6B. Thin wrapper over `run_legacy_scoring`."""
    return run_legacy_scoring(business_name, location, trade).response
