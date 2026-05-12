"""Mirror-phase bridge between the legacy analyzer and the canonical
persistence stack.

Per docs/phase-b6a-plan.md §4.2 (B.6A.2 adapter) + §4.4 (B.6A.4
orchestrator). This module hosts:

  - SignalObservation (B.6A.2): frozen transport dataclass
  - signal_results_to_observations (B.6A.2): pure adapter
  - BridgeResult (B.6A.4): frozen result triple
  - analyze_and_persist (B.6A.4): async orchestrator

The orchestrator wires the legacy probe layer to the canonical
persistence stack in one call: legacy analyze() once for the
response contract, SIGNALS registry once for the canonical
observations, then Lead + 4 lead_signal + 1 lead_score_snapshot
in a single async-session transaction the CALLER controls.

Mirror-first discipline (per
`feedback_staged_convergence_mirror_first.md` +
`feedback_explainability_first_for_bridges.md`):
  - The legacy `analyze()` in `app/domain/scoring.py` is NOT
    modified. It is called as a black-box public API.
  - The legacy `SIGNALS` registry in `app/domain/signals.py` is NOT
    modified. It is iterated, not mutated.
  - No HTTP route is wired to this module.
  - No startup hook initializes it.
  - No public API re-export from `app.domain.leads.__init__`.
  - The orchestrator is dark code; only tests call it in B.6A.

Option-J SignalResults sourcing (locked 2026-05-11):
  - analyze() runs once for the legacy AnalyzeResponse.
  - SIGNALS runs independently inside the orchestrator for the
    canonical observations.
  - Two SIGNAL runs per call. For deterministic-hash signals,
    free. For `google_business_presence` (real fetch), tests mock
    it; production does not run B.6A code, so double-fetch never
    occurs in production. B.6B convergence resolves the duplication
    naturally when analyze() is retired.

Value-dict shape (locked 2026-05-11, option 2 per
phase-b6a-plan.md §4.2 + the explainability-first directive in
`feedback_explainability_first_for_bridges.md`):

    {
        "score":           float in [0.0, 1.0],   # required (per
                                                  # phase-b5-plan.md
                                                  # §2 #4 -- compute_
                                                  # lead_score reads
                                                  # this key)
        "gap":             str | None,            # legacy gap copy
                                                  # at probe time
        "weight_at_probe": float,                 # legacy pack
                                                  # weight at probe
                                                  # time (NOT the
                                                  # canonical weight)
    }

Persisting `gap` and `weight_at_probe` makes each `lead_signal` row
self-describing for replay + divergence diagnostics: a future
operator (or the B.6A.3 comparator) can reconstruct the legacy
probe state from the persisted observation alone.

The persisted `weight_at_probe` is provenance, NOT a weight the
canonical compute path reads -- canonical reads its weights from
`vertical_lead_signal_weight`. Keeping both pinned to the same
observation makes weight-drift diagnoses trivial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from app.db.models import Lead, LeadScoreSnapshot
from app.db.repositories.lead_repo import LeadRepository
from app.db.repositories.lead_score_snapshot_repo import (
    LeadScoreSnapshotRepository,
)
from app.db.repositories.lead_signal_definition_repo import (
    LeadSignalDefinitionRepository,
)
from app.db.repositories.lead_signal_repo import LeadSignalRepository
from app.db.repositories.vertical_lead_signal_weight_repo import (
    VerticalLeadSignalWeightRepository,
)
from app.domain.leads.recording import record_lead_signal
from app.domain.leads.scoring import compute_lead_score
from app.domain.scoring import analyze
from app.domain.scoring_divergence import (
    ScoreDivergence,
    compute_divergence,
    log_divergence,
)
from app.domain.signals import SIGNALS, SignalResult
from app.schemas import AnalyzeResponse

#: Source identifier stamped on every observation produced by this
#: adapter. Versioned (`:v1`) so a future adapter variant can be
#: distinguished in the lead_signal.source column without renaming.
LEGACY_ANALYZER_SOURCE: str = "legacy_analyzer:v1"


@dataclass(frozen=True)
class SignalObservation:
    """Transport shape: a single legacy SignalResult translated into
    the `(signal_name, value, source)` triple that
    `record_lead_signal` consumes.

    NOT persisted. NOT a public API. Frozen so callers cannot mutate
    after construction; the `value` dict itself is technically still
    mutable (dataclass frozen only prevents attribute reassignment),
    but callers must treat it as immutable. The B.6A.4 orchestrator
    constructs a fresh dict per call and passes it directly to
    `record_lead_signal`.
    """

    signal_name: str
    value: dict[str, Any]
    source: str


def signal_results_to_observations(
    results: list[SignalResult],
) -> list[SignalObservation]:
    """Translate legacy `SignalResult` instances into observation
    triples.

    Pure function: no DB, no I/O, no side effects, no clock reads.
    Order is preserved (output[i] corresponds to input[i]). Empty
    input returns empty output without error.

    Each observation's `value` dict carries the score (required by
    `compute_lead_score._extract_score_value`), the legacy gap copy,
    and the legacy weight at probe time -- see module docstring for
    the locked shape and rationale.

    Raises:
        ValueError: if any `SignalResult.score` is outside [0.0,
            1.0]. Matches the contract `compute_lead_score` expects
            of the persisted `value['score']` per phase-b5-plan.md
            §2 #4. Fail-loud, no silent clamping.
    """
    observations: list[SignalObservation] = []
    for r in results:
        if not (0.0 <= r.score <= 1.0):
            raise ValueError(
                f"SignalResult[{r.name!r}].score = {r.score!r} is "
                f"outside [0.0, 1.0]"
            )
        observations.append(
            SignalObservation(
                signal_name=r.name,
                value={
                    "score": r.score,
                    "gap": r.gap,
                    "weight_at_probe": r.weight,
                },
                source=LEGACY_ANALYZER_SOURCE,
            )
        )
    return observations


# ---------------------------------------------------------------------------
# B.6A.4 — orchestrator
# ---------------------------------------------------------------------------


#: Source string stamped on every Lead created by the bridge.
#: Versioned (`:v1`) so a future bridge variant can be distinguished
#: in the lead.source column without renaming.
BRIDGE_LEAD_SOURCE: str = "bridge:legacy_analyzer:v1"


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BridgeResult:
    """Result triple from a single `analyze_and_persist` call.

    `response` is the legacy AnalyzeResponse, byte-identical to what
    the legacy `analyze()` produced -- the legacy contract is
    preserved exactly. `snapshot` is the canonical persisted
    LeadScoreSnapshot. `divergence` is always populated and emitted
    via `log_divergence` before this BridgeResult is returned.

    Frozen: callers cannot mutate after construction. The dict
    inside `response.gaps` is technically still mutable, but
    treating BridgeResult as immutable is the contract.
    """

    response: AnalyzeResponse
    snapshot: LeadScoreSnapshot
    divergence: ScoreDivergence


async def analyze_and_persist(
    *,
    business_name: str,
    location: str,
    trade: str | None,
    account_id: UUID,
    vertical_id: UUID,
    lead_repo: LeadRepository,
    lead_signal_repo: LeadSignalRepository,
    signal_definition_repo: LeadSignalDefinitionRepository,
    weight_repo: VerticalLeadSignalWeightRepository,
    score_repo: LeadScoreSnapshotRepository,
    logger: Any,
    now_fn: Callable[[], datetime] = _default_now,
) -> BridgeResult:
    """Mirror-phase orchestrator: legacy + canonical in one call.

    Steps (all inside ONE async-session transaction the caller
    controls -- this function does NOT commit):

      1. Build legacy AnalyzeResponse via `analyze(...)`.
      2. Run SIGNALS once via the registry for canonical
         observations (option J locked 2026-05-11).
      3. Adapt SignalResult[] -> SignalObservation[] via the pure
         adapter; out-of-range scores raise here.
      4. Create a new Lead row
         (source=BRIDGE_LEAD_SOURCE, lifecycle_state default).
      5. record_lead_signal x4 -- all-or-nothing. If any raises
         (e.g. lead_signal_definition catalog row missing), the
         caller's session rolls back; record_lead_score is never
         called; no snapshot is staged.
      6. Compute the canonical score via `compute_lead_score`
         (we use compute + manual create instead of the higher-
         level record_lead_score helper because we need the
         intermediate ComputedLeadScore for the divergence
         comparator).
      7. Stage the snapshot via `score_repo.create`.
      8. Read the canonical weights active at `weight_version_at`
         (replay-safe).
      9. compute_divergence(...) and log_divergence(...).
     10. Return BridgeResult (response, snapshot, divergence).

    Exceptions propagate. The orchestrator does NOT swallow errors
    -- the caller controls transaction boundaries and is the one
    that rolls back on failure.

    Args:
        business_name, location, trade: passed through to legacy
            `analyze()`.
        account_id: tenancy root for the new Lead (demo account
            in B.6A).
        vertical_id: vertical FK for the new Lead AND the
            compute_lead_score lookup.
        lead_repo, lead_signal_repo, signal_definition_repo,
            weight_repo, score_repo: explicit repos. Caller
            constructs with the right tenancy scope.
        logger: structlog-style logger with `.debug` / `.info` /
            `.error` methods. Caller binds context (e.g.
            request_id) and passes the bound logger in.
        now_fn: injectable clock for deterministic tests.

    Returns:
        BridgeResult with legacy response, persisted snapshot, and
        the per-call divergence report (already logged).
    """
    # Step 1: legacy response (single source of truth for
    # AnalyzeResponse shape + tier/summary/competitor copy)
    response: AnalyzeResponse = analyze(business_name, location, trade)

    # Step 2: canonical observations. Independent SIGNALS run.
    # Deterministic-hash signals are stable; google_business_presence
    # in tests is mocked. Production never runs this path in B.6A.
    results: list[SignalResult] = [
        signal(business_name, location) for signal in SIGNALS
    ]

    # Step 3: adapt. Raises on out-of-range scores BEFORE any DB
    # write -- fail-fast.
    observations = signal_results_to_observations(results)

    # Step 4: create the Lead. Lead-per-call (no dedupe) per
    # phase-b6a-plan.md §2 decision #3.
    now = now_fn()
    lead: Lead = await lead_repo.create(
        account_id=account_id,
        vertical_id=vertical_id,
        source=BRIDGE_LEAD_SOURCE,
    )

    # Step 5: record each lead_signal. All-or-nothing in the
    # session-transaction sense: any exception aborts before the
    # snapshot stage; caller rolls back.
    for obs in observations:
        await record_lead_signal(
            lead=lead,
            signal_name=obs.signal_name,
            value=obs.value,
            source=obs.source,
            lead_signal_repo=lead_signal_repo,
            signal_definition_repo=signal_definition_repo,
            now_fn=now_fn,
        )

    # Step 6: compute the canonical score. We bypass the
    # record_lead_score helper because we need the intermediate
    # ComputedLeadScore for the divergence comparator (and to
    # avoid recomputing it twice).
    computed = await compute_lead_score(
        lead=lead,
        vertical_id=vertical_id,
        lead_signal_repo=lead_signal_repo,
        weight_repo=weight_repo,
        weight_version_at=now,
        now_fn=now_fn,
    )

    # Step 7: stage the snapshot directly via the repo. Mirrors
    # what record_lead_score does internally; this orchestrator
    # is the specialized caller that retains the ComputedLeadScore.
    snapshot: LeadScoreSnapshot = await score_repo.create(
        lead=lead,
        vertical_id=vertical_id,
        score=computed.score,
        score_breakdown=computed.breakdown,
        inputs=computed.inputs,
        weight_version_at=now,
        computed_at=now,
    )

    # Step 8: read canonical weights at weight_version_at for
    # divergence breakdown (covers observed AND unobserved-but-
    # active signals).
    canonical_weights = await weight_repo.find_all_active_for_vertical(
        vertical_id, at_time=now
    )

    # Step 9: compute + log the divergence. Both sides + provenance
    # in the comparator's hands.
    divergence = compute_divergence(
        legacy_score=response.score,
        legacy_results=results,
        canonical_computed=computed,
        canonical_weights=canonical_weights,
        vertical_id=vertical_id,
        weight_version_at=now,
        lead_id=lead.id,
        snapshot_id=snapshot.id,
    )
    log_divergence(divergence, logger)

    return BridgeResult(
        response=response,
        snapshot=snapshot,
        divergence=divergence,
    )
