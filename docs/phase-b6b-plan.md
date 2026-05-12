# Phase B.6B — Live Shadow Persistence Under Production Traffic

**Status:** planning locked, implementation pending
**Sub-phase of:** B.6 (Analyzer → canonical persistence convergence)
**Predecessor:** B.6A (validated dark mirror bridge) at `9801196`
**Successor:** B.6C+ (convergence / authority transfer / cleanup)
**Doctrine refs:** `feedback_staged_convergence_mirror_first.md`,
`feedback_explainability_first_for_bridges.md`,
`feedback_phase_gating.md`, `feedback_logical_modularity_first.md`,
`feedback_design_for_scale_implement_for_simplicity.md`

---

## §1 Purpose

B.6B delivers the first production reach for the canonical
persistence bridge, with strict adherence to one objective:

> **"Live shadow persistence under production traffic with zero
> response authority."**

Phase boundaries:

```
B.6A  =  validated dark infrastructure       (complete; 9801196)
B.6B  =  production shadow reach             (this phase)
B.6C+ =  convergence / authority transfer    (future)
```

B.6B IS:
  - runtime survivability validation against real production traffic
  - persistence stability validation under concurrent load
  - observability validation (divergence events, shadow failures)
  - rollback-confidence validation (one-step flag toggle)

B.6B IS NOT:
  - scoring authority transfer (legacy `analyze()` remains the
    sole source of user-facing responses)
  - tenancy rollout (demo account remains the persistence target)
  - source-of-truth migration (vertical_signal_weight legacy
    table untouched; pack LEAD_SIGNAL_WEIGHTS stays empty)
  - convergence completion (BRIDGE_DIVERGENCE_TOLERANCE stays = 1)
  - cleanup phase (out-of-seam refactors deferred to B.6C+)
  - production-visible behavior change (response body / status /
    headers byte-identical with flag in any state)

---

## §2 Decisions locked (2026-05-12)

1. **BackgroundTasks as the seam.** FastAPI `BackgroundTasks`
   runs the shadow path AFTER the response is delivered. Response
   physically cannot be affected by shadow execution; shadow
   failures are post-response side effects.

2. **Own AsyncSession for the shadow path.** Shadow seam acquires
   its OWN session inside the BackgroundTask via
   `_get_sessionmaker()`. The request-scoped session is NOT
   threaded through. Isolates rollback + commit lifecycle;
   prevents cross-contamination of request transaction state.

3. **Feature flag default OFF in all environments.**
   `b6b_shadow_scoring_enabled: bool = Field(default=False)`.
   Production, staging, dev, CI all start OFF. Operator enables
   per-environment via env var.

4. **Flag-OFF invariant is testable, not assumed.** When the flag
   is OFF, tests must prove ALL of the properties in §6.

5. **Hard 5s timeout on shadow execution.** Orchestrator call
   wrapped in `asyncio.wait_for(..., timeout=5)`. Timeout failures
   swallowed, logged at WARNING, shadow session rolled back.
   Request response unaffected.

6. **Logging constraints — absence is signal.** Success events at
   DEBUG; in-tolerance divergence at DEBUG; only out-of-tolerance
   divergence + failure events surface at WARNING/ERROR. No
   "shadow skipped because disabled" log -- flag-OFF silence is
   itself the signal.

7. **Timeout failures are operationally distinct from divergence
   failures.** `bridge.shadow_timeout` (WARNING) is an
   infrastructure incident class. `bridge.score_comparison` at
   ERROR is a scoring incident class. Separate event names; do
   not conflate.

8. **`_blended_score` becomes a compatibility shim, not deleted.**
   Math moves into a new internal `_compute_blended_score()`;
   `_blended_score` remains importable as a one-line shim with
   "remove in B.6C" comment. Operational certainty > cleanup
   purity during production-reach phases.

9. **No schema migration.** B.6B introduces no new alembic
   revision. Rollback never requires `alembic downgrade`.

10. **Demo account remains the persistence target.** Both
    DEMO_ACCOUNT_ID and DEMO_VERTICAL_ID are hard-coded UUID5
    constants matching migration 0020. Real-tenancy resolution
    is a B.6C+ concern.

11. **Lead-per-call discipline preserved.** Every shadow execution
    creates a new Lead row. Demo-account leakage is acknowledged
    discipline -- B.6C+ addresses dedupe.

12. **Three-commit implementation.** B.6B.1 refactor → B.6B.2
    shadow seam → B.6B.3 route wiring. Each independently
    revertable; smoke-test-first between commits.

13. **Controlled canary rollout post-merge.** staging-OFF →
    staging-ON → single-prod-canary → tiny traffic slice →
    broader. Operational sequence; documented but not enforced
    in code.

---

## §3 Out of scope for B.6B

Explicitly NOT in B.6B (each deferred to B.6C+ or a separate
ticket):

- Retiring `_blended_score` outright (kept as compatibility shim)
- Tightening `BRIDGE_DIVERGENCE_TOLERANCE` from 1 → 0
- Populating pack `LEAD_SIGNAL_WEIGHTS` / converging weight
  sources of truth
- Cleanup or deprecation of legacy `vertical_signal_weight` table
- Real-tenancy resolution (auth → account_id resolver)
- Lead dedupe / upsert semantics
- New public API surface (no GET / read endpoints)
- UI changes
- Partial-catalog mutation test (still deferred from B.6A)
- Cleanup refactors outside the wrapper seam in `scoring.py`
- Deploy-to-Staging workflow fix (separate parallel ticket;
  blocker for production rollout, NOT for B.6B code merge)

---

## §4 Architecture

### §4.1 Request lifecycle (the seam)

```
Client → POST /v1/analyses-legacy (or /analyze-business alias)
         │
         ▼
    sync route handler
         │
         ├──── response = analyze(business_name, location, trade)
         │     (legacy, authoritative, byte-identical to pre-B.6B)
         │
         ├──── background_tasks.add_task(
         │         run_shadow_persist_if_enabled,
         │         business_name=..., location=..., trade=...,
         │     )
         │
         └──── return response  ───────────►  Client receives response
                                              (status / headers / body
                                               all byte-identical)

[after response delivered, in same async event loop]
         │
         ▼
    run_shadow_persist_if_enabled
         │
         ├──── if not settings.b6b_shadow_scoring_enabled:
         │         return  (FLAG-OFF FAST PATH: no session,
         │                  no orchestrator, no logs, no side effect)
         │
         ├──── async with _get_sessionmaker() as session:
         │         (OWN session, independent of any request session)
         │
         │         try:
         │             await asyncio.wait_for(
         │                 analyze_and_persist(..., session=...),
         │                 timeout=5,
         │             )
         │             await session.commit()
         │             logger.debug("bridge.shadow_succeeded")
         │
         │         except asyncio.TimeoutError:
         │             logger.warning("bridge.shadow_timeout", ...)
         │             await session.rollback()  # best-effort
         │
         │         except Exception:
         │             logger.warning("bridge.shadow_failed", exc_info=True)
         │             try:
         │                 await session.rollback()
         │             except Exception:
         │                 logger.warning("bridge.shadow_rollback_failed",
         │                                exc_info=True)
         │
         └──── return None  (never raises)
```

### §4.2 New files

| File | Status | Purpose |
|---|---|---|
| `backend/app/domain/bridge_shadow.py` | NEW (B.6B.2) | `run_shadow_persist_if_enabled()` + DEMO_ACCOUNT_ID + DEMO_VERTICAL_ID constants + bounded-timeout wrapper |
| `backend/tests/test_scoring_refactor.py` | NEW (B.6B.1) | Byte-identical parity tests + `_blended_score` shim test |
| `backend/tests/test_bridge_shadow.py` | NEW (B.6B.2) | Flag OFF / ON-success / ON-failure / ON-timeout |
| `backend/tests/test_shadow_routes.py` | NEW (B.6B.3) | HTTP integration via TestClient + dependency_overrides |
| `docs/phase-b6b-plan.md` | This commit (B.6B.0) | Plan doc |

### §4.3 Modified files

| File | Status | Change |
|---|---|---|
| `backend/app/domain/scoring.py` | MODIFY (B.6B.1) | Introduce `LegacyScoringResult` + `run_legacy_scoring()`. Inline `_blended_score` math into new internal `_compute_blended_score()`. Keep `_blended_score()` as a shim returning `_compute_blended_score()`. `analyze()` becomes one-liner. |
| `backend/app/core/config.py` | MODIFY (B.6B.2) | Add `b6b_shadow_scoring_enabled` field. |
| `backend/app/api/v1/analyses_legacy.py` | MODIFY (B.6B.3) | Add `BackgroundTasks` dep; schedule shadow task. |
| `backend/app/main.py` | MODIFY (B.6B.3) | Same wiring on the `/analyze-business` alias. |
| `backend/tests/conftest.py` | MODIFY (B.6B.3) | Add `client_with_db` fixture (TestClient + dependency_overrides). |

### §4.4 Wrapper structure (B.6B.1)

```python
# app/domain/scoring.py

@dataclass(frozen=True)
class LegacyScoringResult:
    response: AnalyzeResponse
    signal_results: list[SignalResult]


def _compute_blended_score(results: list[SignalResult]) -> int:
    """Legacy blended-score math, inlined (was _blended_score).
    Behavior byte-identical to the pre-B.6B function."""
    total_weight = sum(r.weight for r in results) or 1.0
    weighted = sum(r.score * r.weight for r in results)
    return round((weighted / total_weight) * 100)


def _blended_score(results: list[SignalResult]) -> int:
    """Compatibility shim. Remove in B.6C after live shadowing
    stabilizes. Per phase-b6b-plan.md §2 decision #8: operational
    certainty > cleanup purity during production-reach."""
    return _compute_blended_score(results)


def run_legacy_scoring(
    business_name: str,
    location: str,
    trade: str | None = None,
) -> LegacyScoringResult:
    """Single-source-of-truth runner for legacy scoring. Produces
    both AnalyzeResponse and intermediate SignalResults so future
    callers can share one SIGNAL run."""
    pack = _get_pack()
    results = [signal(business_name, location) for signal in SIGNALS]
    score = _compute_blended_score(results)
    gaps = [r.gap for r in results if r.gap]
    summary = _build_summary(business_name, score, len(gaps), pack)
    category_scores = _build_category_scores(results, pack)
    competitors = _generate_competitors(business_name, location, score, pack)
    return LegacyScoringResult(
        response=AnalyzeResponse(
            score=score, gaps=gaps, summary=summary,
            category_scores=category_scores, competitors=competitors,
            trade=trade,
        ),
        signal_results=results,
    )


def analyze(
    business_name: str,
    location: str,
    trade: str | None = None,
) -> AnalyzeResponse:
    """Public sync API. Signature + return type byte-identical to
    pre-B.6B. Thin wrapper over `run_legacy_scoring`."""
    return run_legacy_scoring(business_name, location, trade).response
```

### §4.5 Shadow seam (B.6B.2)

```python
# app/domain/bridge_shadow.py (NEW)

import asyncio
import uuid

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import _get_sessionmaker
# ...repos + analyze_and_persist imports

DEMO_ACCOUNT_ID: UUID = uuid.uuid5(
    uuid.NAMESPACE_DNS, "trufindai.demo.account"
)
DEMO_VERTICAL_ID: UUID = uuid.uuid5(
    uuid.NAMESPACE_DNS,
    "trufindai.demo.vertical.local_business_ai_visibility",
)
SHADOW_TIMEOUT_SECONDS: float = 5.0

_logger = get_logger("app.domain.bridge_shadow")


async def run_shadow_persist_if_enabled(
    *,
    business_name: str,
    location: str,
    trade: str | None,
) -> None:
    """Fire-and-forget shadow persistence.

    Invariants (per phase-b6b-plan.md §6):
      - Returns None always; never raises.
      - When flag is OFF, returns immediately after a single bool
        check. NO session, NO orchestrator, NO logs, NO side
        effects of any kind.
      - When flag is ON, acquires its OWN session, runs the B.6A.4
        orchestrator inside a 5s timeout, swallows all exceptions,
        logs structured events for divergence + failures only.

    Called from FastAPI BackgroundTasks AFTER the response is
    delivered. Cannot affect the response under any circumstance.
    """
    if not get_settings().b6b_shadow_scoring_enabled:
        return  # FLAG-OFF FAST PATH (see §6)

    async with _get_sessionmaker()() as session:
        try:
            await asyncio.wait_for(
                analyze_and_persist(
                    business_name=business_name,
                    location=location,
                    trade=trade,
                    account_id=DEMO_ACCOUNT_ID,
                    vertical_id=DEMO_VERTICAL_ID,
                    lead_repo=LeadRepository(session, DEMO_ACCOUNT_ID),
                    lead_signal_repo=LeadSignalRepository(session, DEMO_ACCOUNT_ID),
                    signal_definition_repo=LeadSignalDefinitionRepository(session, None),
                    weight_repo=VerticalLeadSignalWeightRepository(session, None),
                    score_repo=LeadScoreSnapshotRepository(session, DEMO_ACCOUNT_ID),
                    logger=_logger,
                ),
                timeout=SHADOW_TIMEOUT_SECONDS,
            )
            await session.commit()
            _logger.debug(
                "bridge.shadow_succeeded",
                business_name=business_name,
                location=location,
            )
        except asyncio.TimeoutError:
            _logger.warning(
                "bridge.shadow_timeout",
                business_name=business_name,
                location=location,
                timeout_seconds=SHADOW_TIMEOUT_SECONDS,
            )
            await _safe_rollback(session)
        except Exception:
            _logger.warning(
                "bridge.shadow_failed",
                business_name=business_name,
                location=location,
                exc_info=True,
            )
            await _safe_rollback(session)


async def _safe_rollback(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except Exception:
        _logger.warning(
            "bridge.shadow_rollback_failed", exc_info=True
        )
```

### §4.6 Route integration (B.6B.3)

```python
# app/api/v1/analyses_legacy.py (MODIFY)

from fastapi import APIRouter, BackgroundTasks

from app.domain.bridge_shadow import run_shadow_persist_if_enabled
from app.domain.scoring import analyze
from app.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


def run_analysis(payload: AnalyzeRequest) -> AnalyzeResponse:
    return analyze(payload.business_name, payload.location, payload.trade)


@router.post("/analyses-legacy", response_model=AnalyzeResponse, tags=["analyses"])
def analyses_legacy(
    payload: AnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> AnalyzeResponse:
    response = run_analysis(payload)
    background_tasks.add_task(
        run_shadow_persist_if_enabled,
        business_name=payload.business_name,
        location=payload.location,
        trade=payload.trade,
    )
    return response
```

Same pattern applied to the back-compat `/analyze-business` alias
in `main.py`.

---

## §5 Sub-phase breakdown

Four commits after this plan doc. Each independently revertable.
Smoke-test-first, verify-before-commit, stop between for explicit
confirmation (B.6A cadence).

| Sub-phase | Scope | Smoke gate |
|---|---|---|
| **B.6B.0** | This plan doc | doc renders; references resolve |
| **B.6B.1** | `scoring.py` refactor (`run_legacy_scoring` + `LegacyScoringResult` + `_compute_blended_score` + `_blended_score` shim + `analyze()` one-liner) + parity tests | existing 714 tests stay green (byte-identical behavior); new tests assert response equality across baseline + corpus; `_blended_score` import still resolves |
| **B.6B.2** | `bridge_shadow.py` (NEW) + settings flag + shadow unit tests | new tests pass; flag-OFF early return verified; flag-ON success / failure / timeout paths verified; full suite green |
| **B.6B.3** | Route wiring (both endpoints) + `conftest.py` TestClient fixture + HTTP integration tests | HTTP test: flag OFF → byte-identical response + zero DB rows added + zero BackgroundTask scheduling overhead; flag ON → byte-identical response + demo-account lead + 4 signals + 1 snapshot present; existing 714+ tests stay green |

Phase closure (no code commit) after B.6B.3: verification pass +
memory update marking B.6B complete + B.6C direction TBD.

---

## §6 Flag-OFF invariant

When `b6b_shadow_scoring_enabled=false`, the system MUST guarantee
the following nine properties. **All are testable; tests must
prove each, not assume any.**

1. **Zero orchestrator execution.** `analyze_and_persist` is not
   called. Assert via mock spy / patch.
2. **Zero DB writes.** Lead / lead_signal / lead_score_snapshot
   row counts unchanged before and after the request. Assert
   via `SELECT count(*)` deltas under `db_session`.
3. **Zero connection acquisition.** The runtime sessionmaker is
   not invoked. Assert via spy on `_get_sessionmaker` or its
   return value's `__call__`.
4. **Zero sessionmaker invocation.** Stronger form of #3 -- the
   `_get_sessionmaker()` factory itself is not called.
5. **Zero async task scheduling.** Background-task work allocation
   does not occur. Even though the route calls
   `background_tasks.add_task(run_shadow_persist_if_enabled, ...)`,
   the function's first action is a single bool check + return,
   so the persistence pipeline never starts. **§11 records the
   stronger assertion that the BackgroundTasks queue length
   remains effectively zero in terms of allocated work**: the
   scheduled task runs to completion in one bool-check.
6. **Zero divergence logging.** `bridge.score_comparison`,
   `bridge.shadow_*` events do not fire. Assert via captured
   structlog events.
7. **Byte-identical response body.** AnalyzeResponse[flag=off]
   == AnalyzeResponse[flag=on=mocked-to-skip] for the same input.
   Assert with `response.body == reference_body`.
8. **Identical HTTP status codes.** 200 in both cases.
9. **Identical HTTP headers.** Headers added by the framework
   (content-type, content-length, etc.) match across flag
   states. Assert with `set(response.headers.keys()) ==
   set(reference.headers.keys())` and `response.headers[k] ==
   reference.headers[k]` for each.

The invariant proves not merely "no persistence" but "no hidden
runtime cost or side effect of any kind."

---

## §7 Logging surface

All events use the structlog logger
`app.domain.bridge_shadow` (or, for divergence events emitted
from inside the orchestrator, `app.domain.scoring_persistence` /
`app.domain.scoring_divergence`). Severity ladder:

| Event | Severity | Source | When |
|---|---|---|---|
| `bridge.score_comparison` | DEBUG | scoring_divergence.log_divergence | delta == 0 |
| `bridge.score_comparison` | INFO | scoring_divergence.log_divergence | 0 < \|delta\| ≤ BRIDGE_DIVERGENCE_TOLERANCE (boundary case) |
| `bridge.score_comparison` | ERROR | scoring_divergence.log_divergence | \|delta\| > BRIDGE_DIVERGENCE_TOLERANCE (real drift) |
| `bridge.shadow_succeeded` | DEBUG | bridge_shadow | shadow path completed cleanly |
| `bridge.shadow_timeout` | WARNING | bridge_shadow | shadow exceeded 5s timeout |
| `bridge.shadow_failed` | WARNING | bridge_shadow | shadow raised non-timeout exception |
| `bridge.shadow_rollback_failed` | WARNING | bridge_shadow | session rollback raised after shadow failure |

**Operational classification of failure types:**

- `bridge.shadow_timeout` is an **operational incident** (DB
  slowness, connection pool exhaustion, network degradation).
  Investigate infrastructure, not scoring.
- `bridge.score_comparison` at ERROR is a **scoring incident**
  (real divergence between legacy and canonical). Investigate
  the bridge, seed weights, or signal probes.

These are different incident classes and must remain separated
in event names + dashboards.

**No event is emitted for the flag-OFF path.** Per decision #6:
absence of any `bridge.*` event for a request IS the signal
that the flag is OFF.

---

## §8 Rollout gates

**Code-side gates (CI / merge):**

| Gate | Sub-phase |
|---|---|
| 714 existing tests pass after `scoring.py` refactor | B.6B.1 |
| `_blended_score` shim still importable; same int return | B.6B.1 |
| Byte-identical response: corpus inputs through `analyze()` produce identical AnalyzeResponse before/after refactor | B.6B.1 |
| Flag-OFF invariant: all nine §6 properties asserted by tests | B.6B.2 + B.6B.3 |
| Flag-ON success path: orchestrator called once; DB rows written; logs emitted at correct severities | B.6B.2 |
| Flag-ON timeout path: `bridge.shadow_timeout` at WARNING; session rolled back; no exception propagated | B.6B.2 |
| HTTP integration: TestClient calls return byte-identical body + status + headers for flag OFF and flag ON | B.6B.3 |
| Baseline `analyze('Joe Pizza','Brooklyn,NY').score == 60` preserved | every commit |

**Operational gates (post-merge, before broad enable):**

1. **Staging deploy works.** Deploy-to-Staging workflow is
   green. (Orthogonal ticket; blocker for production rollout,
   NOT for B.6B code merge.)
2. **Connection-pool baseline.** Capture pool metrics in staging
   BEFORE enabling shadow mode: active connections, idle
   connections, wait time, leaked connections (over a 10-15min
   window with representative traffic).
3. **Enable in staging.** Flag ON in staging only. Watch the
   same connection-pool metrics for 10-15 min. Validate:
   - Pool stability (no growth without bound)
   - No connection leakage (idle returns to baseline after
     traffic settles)
   - No starvation under canary load (no waits)
4. **Inspect logs.** Look for unexpected `bridge.shadow_failed`
   / `bridge.shadow_timeout` / `bridge.score_comparison` at
   ERROR. Zero out-of-tolerance divergence events is the
   confidence signal.
5. **Single-instance prod canary.** One instance, flag ON.
   Continue connection-pool + log monitoring.
6. **Tiny traffic slice.** Gradual expansion (e.g. 1% → 5% →
   25%) by environment / instance fleet share, monitoring
   metrics at each step.
7. **Broader shadowing.** Only after canary + slice show
   stability.

**Rollback at any gate is one-step**: env var flip + app
restart. No code revert required for operational rollback.

---

## §9 Rollback paths

| Trigger | Action | Time to revert | DB impact |
|---|---|---|---|
| Shadow behavior degrades production | `B6B_SHADOW_SCORING_ENABLED=false` + app restart | < 1 minute | None. Pending BackgroundTasks complete; new requests skip. |
| Need full code removal | `git revert <B.6B.3>` (then `.2`, `.1` if needed) | minutes | None. No schema change to revert. |
| Scoring refactor broke `analyze()` | `git revert <B.6B.1>` | minutes | None. |

**Rollback validation**:
- After flag toggle: query `SELECT count(*) FROM lead WHERE source = 'bridge:legacy_analyzer:v1' AND created_at > <toggle-time>` and verify count stays flat across subsequent requests.
- After git revert: re-run HTTP integration tests; baseline `analyze()` still scores 60.
- After full revert: repo returns to `9801196`-equivalent state.

**No migration rollback at any level.** B.6B is schema-free.

---

## §10 Risk register

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| Shadow exception leaks to response | HIGH | LOW | BackgroundTasks runs post-response; outer try/except in shadow seam catches all (incl. TimeoutError) |
| `_blended_score` refactor changes scoring math by accident | MEDIUM | LOW | B.6B.1 parity tests assert byte-identical AnalyzeResponse across corpus; existing 714 tests catch regressions |
| Shadow session contaminates request session | MEDIUM | LOW | Locked decision #2: own session via `_get_sessionmaker()`; no threading from request |
| **BackgroundTask accumulation during DB degradation/outage** | **HIGH** | **MEDIUM (under outage)** | **Bounded 5s timeout + graceful shutdown timeout + own-session isolation + canary rollout discipline + instant feature-flag rollback. This is the primary operational concurrency risk introduced by B.6B.** |
| Connection pool exhaustion under shadow load | MEDIUM | MEDIUM (under traffic) | Own-session per shadow call closes connection on context exit (NullPool-like effect for shadow); §8 operational gate requires pool metrics validation before broad enable |
| Demo account row count grows unbounded | MEDIUM | HIGH (when flag ON) | Acknowledged. Lead-per-call is B.6A discipline; B.6C+ addresses dedupe. Operator can truncate demo account safely. |
| DB write load when flag ON | MEDIUM | HIGH (when ON) | One Lead + 4 LeadSignals + 1 Snapshot per request. Acceptable for canary; reconsider at production scale. Tied to canary rollout sequence. |
| Logging volume | LOW | MEDIUM | DEBUG-level success events are filtered out by INFO+ log levels in staging/production. Only WARNING+ surfaces in operational logs. |
| Pending BackgroundTasks on app shutdown | MEDIUM | LOW | FastAPI awaits in-flight tasks during graceful shutdown; uvicorn `--timeout-graceful-shutdown` controls window; 5s shadow timeout ensures fast drain |
| Flag toggle race (concurrent requests during deploy) | LOW | LOW | Each request reads settings once via `get_settings()` (lru_cached); no race condition within a request |
| Refactored `analyze()` becomes async or changes signature accidentally | MEDIUM | LOW | B.6B.1 explicitly preserves `def analyze(business_name, location, trade=None) -> AnalyzeResponse`; signature test guards this |

---

## §11 Test plan

| # | Test | File | Assertion |
|---|---|---|---|
| 1 | `run_legacy_scoring` returns `LegacyScoringResult(response, signal_results)` | test_scoring_refactor.py | shape + types |
| 2 | `run_legacy_scoring` produces byte-identical response across 10 corpus inputs vs. captured pre-refactor baselines | test_scoring_refactor.py | parity |
| 3 | `_blended_score` shim still importable + same int return | test_scoring_refactor.py | shim contract |
| 4 | `_compute_blended_score` produces identical output to legacy `_blended_score` formula | test_scoring_refactor.py | math parity |
| 5 | `analyze()` signature unchanged: `(str, str, str|None=None) -> AnalyzeResponse` | test_scoring_refactor.py | signature stability |
| 6 | Settings flag `b6b_shadow_scoring_enabled` defaults to False; reads from env | test_core_config.py (extend) | flag contract |
| 7 | Flag OFF → `run_shadow_persist_if_enabled` returns None immediately; sessionmaker NOT invoked | test_bridge_shadow.py | invariant §6.3, §6.4 |
| 8 | Flag OFF → no orchestrator call; no DB writes; no log events | test_bridge_shadow.py | invariant §6.1, §6.2, §6.6 |
| 9 | Flag ON success → orchestrator called once; commit issued; `bridge.shadow_succeeded` at DEBUG | test_bridge_shadow.py | success path |
| 10 | Flag ON, orchestrator raises non-timeout → `bridge.shadow_failed` at WARNING with exc_info; rollback issued | test_bridge_shadow.py | failure path |
| 11 | Flag ON, orchestrator exceeds 5s → `bridge.shadow_timeout` at WARNING; no `bridge.shadow_failed`; rollback issued | test_bridge_shadow.py | timeout path |
| 12 | Flag ON, rollback itself raises → `bridge.shadow_rollback_failed` at WARNING; no exception propagates | test_bridge_shadow.py | nested failure |
| 13 | `run_shadow_persist_if_enabled` returns None in all paths (success, failure, timeout) | test_bridge_shadow.py | invariant |
| 14 | HTTP route flag OFF → response body byte-identical to pre-B.6B baseline | test_shadow_routes.py | invariant §6.7 |
| 15 | HTTP route flag OFF → response status == 200; headers identical | test_shadow_routes.py | invariant §6.8, §6.9 |
| 16 | HTTP route flag OFF → zero DB rows added (Lead / lead_signal / lead_score_snapshot count deltas all zero) | test_shadow_routes.py | invariant §6.2 |
| 17 | **HTTP route flag OFF → no async work allocated: BackgroundTasks queue contains the scheduled task but the task runs to completion as a single bool check + return; no orchestrator side-effect of any kind. Assertion proves no hidden runtime cost.** | **test_shadow_routes.py** | **invariant §6.5** |
| 18 | HTTP route flag ON → response body byte-identical to flag OFF | test_shadow_routes.py | byte-identical contract |
| 19 | HTTP route flag ON → demo-account lead + 4 lead_signal rows + 1 lead_score_snapshot row present | test_shadow_routes.py | shadow effect |
| 20 | HTTP route flag ON, orchestrator forced to raise → response still 200 + byte-identical; shadow_failed logged | test_shadow_routes.py | response-isolation |
| 21 | `/analyze-business` back-compat alias wires shadow correctly | test_shadow_routes.py | alias parity |
| 22 | Connection pool: shadow's own-session closes on context exit; multiple sequential requests do not leak | test_bridge_shadow.py or test_shadow_routes.py | own-session contract |

**~22 new tests.** Combined with current 714 → expect ~736 backend
after B.6B.3 lands (some existing tests may need trivial updates
to import paths if `_blended_score` import location changes, but
the shim ensures this is rare).

---

## §12 References

**ADRs:**
- ADR-002 (Postgres + asyncpg)
- ADR-005 (analyze endpoint contract; back-compat preserved
  through at least Phase B)
- ADR-008 (tenancy via account_id; demo account discipline)
- ADR-010 (replay determinism; preserved by orchestrator)
- ADR-018 (session secret / cookies; not touched in B.6B)
- ADR-030 (structured logging; severity ladder)
- ADR-031 (repository pattern; shadow seam constructs repos)
- ADR-036 (lead signals + dimensions; observation shape preserved)
- ADR-047 (customer-owned vs platform-owned classification)

**Prior phases:**
- B.5 — lead_score_snapshot primitives
- B.6A — mirror-phase bridge (assembled + dark + corpus-validated)
- B.6A.5 — real-DB test fixtures (corpus + replay rely on this;
  B.6B's shadow integration tests inherit the same fixture
  surface)

**Memory:**
- `project_strategic_direction.md`
- `project_platform_directive_v2_authority_infrastructure.md`
- `project_phase_b6a_complete.md`
- `feedback_staged_convergence_mirror_first.md`
- `feedback_explainability_first_for_bridges.md`
- `feedback_design_for_scale_implement_for_simplicity.md`
- `feedback_inspectability_over_abstraction.md`
- `feedback_phase_gating.md`
- `feedback_logical_modularity_first.md`
- `feedback_powershell_safer_commands.md`
