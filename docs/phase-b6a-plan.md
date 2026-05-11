# Phase B.6A — Analyzer→Persistence Bridge (Mirror Phase)

**Status:** planning locked, implementation pending
**Sub-phase of:** B.6 (Analyzer → canonical persistence convergence)
**Predecessor:** B.5 (lead score snapshot primitives) at `3152f4a`
**Successor:** B.6B (legacy retirement; analyze() becomes thin wrapper)
**Doctrine refs:** `feedback_design_for_scale_implement_for_simplicity.md`,
`feedback_inspectability_over_abstraction.md`, `feedback_phase_gating.md`,
`feedback_logical_modularity_first.md`

---

## §1 Purpose

B.6A produces the bridge between the legacy in-memory analyzer
(`app/domain/scoring.py:analyze`) and the canonical persistence stack
(`compute_lead_score` + `record_lead_score` + the lead_* tables) under
strict mirror discipline:

  - The legacy analyzer's response contract is **untouched**.
  - The HTTP endpoint that calls it is **untouched**.
  - Every dark code path the bridge introduces is provably-correct
    under synthetic and replay validation BEFORE any production write
    path is wired.
  - Convergence (retiring `_blended_score`, making `analyze` a thin
    wrapper) happens in B.6B, **gated by B.6A's evidence**.

**Primary outcome is NOT "the bridge exists." It is: "we can
confidently explain WHY the legacy and canonical scores agree or
disagree, with row-by-row signal- and weight-provenance attribution."**

If B.6A delivers a working bridge but no explainability surface,
B.6B is blocked. The divergence tooling is co-equal scope with the
orchestrator, not afterthought.

---

## §2 Decisions locked (Andrew, 2026-05-11)

1. **Account context for demo Lead:** hard-coded demo account.
   - Keeps tenancy/auth concerns isolated; reversibility high.
   - Avoids premature account-resolution semantics.
   - Bridge writes go to a single deterministic account row;
     real-account semantics deferred to a later phase.

2. **Vertical resolution:** add `pack_id` (text, nullable) column on
   `vertical` table.
   - Canonical stack wants UUID-backed identity; name resolution is
     fragile and becomes technical debt.
   - Smallest clean normalization step; explicit resolver, no
     "magic by name" conventions.
   - Do NOT generalize beyond what B.6A needs (no pack registry
     refactor, no vertical lifecycle change).

3. **Lead identity per call:** lead-per-call.
   - Dedupe semantics were intentionally deferred in B.4
     (`project_b4_scope_lead_primitives.md`).
   - Each bridge call writes a fresh Lead row; demo rows
     intentionally accumulate (this is a validation substrate, not
     production semantics).
   - Replay/test isolation is cleaner with per-call identity.

4. **Weight parity seeding strategy:** hard-code weights in migration
   body with explicit provenance comments.
   - Migration is a frozen historical bootstrap artifact.
   - Runtime coupling inside migrations is dangerous; reproducibility
     beats DRY purity here.
   - Comment block in migration body cites the pack source-of-truth
     at seed time.

5. **Endpoint touch in B.6A scope:** strict reading.
   - The analyze endpoint is **not modified** in B.6A.
   - Test corpus is the operational validation layer.
   - Live endpoint wiring (with feature flag, fail-safe persistence)
     is an explicit gate decision for B.6A.5 or B.6B once parity
     confidence + divergence tooling + replay guarantees exist.

---

## §3 Out of scope for B.6A

Explicitly NOT in B.6A:

- Modification of `app/domain/scoring.py`, `app/domain/signals.py`,
  or any HTTP route.
- Modification of the `vertical_signal_weight` table (legacy
  pack-level weights). These remain authoritative for the legacy
  analyzer until B.6B.
- Lead dedupe / upsert by (business_name, city).
- Real-tenancy resolution (auth → account_id).
- UI / frontend changes.
- Vertical pack lifecycle (ADR-048) implementation.
- Read APIs for leads / scores / events.
- Background recompute jobs.
- Property-based testing (deferred; corpus-based tests sufficient).
- Removing or renaming `_blended_score` (retirement is B.6B).

---

## §4 Architecture

### §4.1 New files (all additive)

```
backend/
  alembic/versions/
    0020_add_pack_id_to_vertical.py        # B.6A.1
    0021_seed_demo_account_vertical_catalog.py   # B.6A.1
  app/domain/
    scoring_persistence.py                 # B.6A.2 (adapter)
                                           # B.6A.4 (orchestrator)
    scoring_divergence.py                  # B.6A.3 (comparator + log)
  tests/
    test_signal_adapter.py                 # B.6A.2
    test_scoring_divergence.py             # B.6A.3
    test_analyze_and_persist.py            # B.6A.4
    test_bridge_corpus.py                  # B.6A.5
```

### §4.2 Signal adapter (B.6A.2)

Pure function. No DB, no I/O.

```python
def signal_results_to_observations(
    results: list[SignalResult],
) -> list[SignalObservation]:
    """Translate legacy SignalResult instances into the value-dict
    shape that record_lead_signal + compute_lead_score consume.

    Each SignalObservation carries:
      - signal_name: str (matches lead_signal_definition.name)
      - value: dict[str, Any] with required top-level 'score' key
        (Decimal in [0.0, 1.0]) per phase-b5-plan.md §2 #4
      - source: str (e.g. "legacy_analyzer:v1") for provenance

    Raises ValueError if any score is outside [0.0, 1.0].
    """
```

`SignalObservation` is a frozen dataclass (not persisted; transport
shape only).

### §4.3 Divergence comparator (B.6A.3)

The explainability layer. Two dataclasses + one helper:

```python
@dataclass(frozen=True)
class SignalContributionDiff:
    signal_name: str
    legacy_score: Decimal
    canonical_score: Decimal
    legacy_weight: Decimal       # from pack.signal_weights()
    canonical_weight: Decimal    # from vertical_lead_signal_weight
    legacy_contribution: Decimal
    canonical_contribution: Decimal
    contribution_delta: Decimal  # canonical - legacy


@dataclass(frozen=True)
class ScoreDivergence:
    legacy_score: int                     # legacy _blended_score output
    canonical_score: Decimal              # ComputedLeadScore.score
    delta: int                            # legacy - int(canonical)
    within_tolerance: bool                # abs(delta) <= TOLERANCE
    signal_breakdown: list[SignalContributionDiff]
    weight_version_at: datetime           # canonical replay timestamp
    vertical_id: UUID
    lead_id: UUID | None                  # None if not persisted
    snapshot_id: UUID | None              # None if not persisted


BRIDGE_DIVERGENCE_TOLERANCE: int = 1


def compute_divergence(
    *,
    legacy_results: list[SignalResult],
    legacy_pack_weights: dict[str, Decimal],
    canonical_computed: ComputedLeadScore,
    canonical_weights: list[VerticalLeadSignalWeight],
    vertical_id: UUID,
    lead_id: UUID | None = None,
    snapshot_id: UUID | None = None,
) -> ScoreDivergence:
    """Row-by-row diff. Joins by signal_name. Missing signals on
    either side appear with Decimal('0') on the absent side."""


def explain_divergence(divergence: ScoreDivergence) -> str:
    """Human-readable rendering. Used in test failures, operator
    logs, and future debug endpoints. Multi-line; signal-by-signal."""


def log_divergence(divergence: ScoreDivergence, logger) -> None:
    """Emit a structured log line per ADR-030.

    event = "bridge.score_comparison"
    level = DEBUG if delta == 0
            INFO  if 0 < |delta| <= TOLERANCE
            ERROR if |delta| > TOLERANCE
    """
```

The dataclasses are JSON-serializable (Decimals → strings) so the
log line is queryable per ADR-030 conventions.

### §4.4 Orchestrator (B.6A.4)

```python
@dataclass(frozen=True)
class BridgeResult:
    response: AnalyzeResponse      # legacy contract preserved
    snapshot: LeadScoreSnapshot    # canonical persisted row
    divergence: ScoreDivergence    # always populated


async def analyze_and_persist(
    *,
    business_name: str,
    location: str,
    trade: str | None,
    account_id: UUID,              # demo account in B.6A
    vertical_id: UUID,             # resolved via pack_id lookup
    lead_repo: LeadRepository,
    lead_signal_repo: LeadSignalRepository,
    signal_definition_repo: LeadSignalDefinitionRepository,
    weight_repo: VerticalLeadSignalWeightRepository,
    score_repo: LeadScoreSnapshotRepository,
    now_fn: Callable[[], datetime] = _default_now,
) -> BridgeResult:
    """Mirror-phase orchestrator: legacy + canonical in one call.

    Steps (all inside one async-session transaction):
      1. Run legacy analyze() to get SignalResult[]
      2. Build legacy AnalyzeResponse (existing logic, unchanged)
      3. Create a new Lead row (lead-per-call, no dedupe)
      4. signal_results_to_observations(...) -> SignalObservation[]
      5. record_lead_signal x4 (all-or-nothing)
      6. record_lead_score(...) -> LeadScoreSnapshot
      7. compute_divergence(...) and log_divergence(...)
      8. Return BridgeResult

    All-or-nothing: if any record_lead_signal raises (missing catalog
    row, ValueError on score), the whole transaction aborts. No
    partial writes.
    """
```

No HTTP wiring. Not called from any prod path in B.6A.

---

## §5 Schema changes

### §5.1 Migration 0020: add `pack_id` column on `vertical`

- Add `pack_id text NULL`.
- Backfill existing `vertical` rows (if any) to
  `settings.default_vertical_pack_id`.
- Add UNIQUE index `ix_vertical_pack_id_unique` on `pack_id`
  (partial: WHERE pack_id IS NOT NULL).
- Keep nullable for now; B.6B may tighten to NOT NULL after the
  full vertical/pack resolution story is decided.

`down_revision = "0019_lead_score_snapshot"`.

### §5.2 Migration 0021: seed demo account + vertical + catalog

Single transaction. Idempotent (uses `INSERT ... ON CONFLICT DO
NOTHING` on natural keys).

Seeds:

- **demo account** (stable UUIDv7 minted from a fixed seed; or use a
  deterministic UUID5 from a namespace + "demo"). Name = "demo".
- **demo vertical** linked to `settings.default_vertical_pack_id`.
  Stable UUID.
- **lead_signal_definition** rows for the 4 legacy signals:
  - `website_presence`
  - `google_business_presence`
  - `content_signals`
  - `reviews`
  Each with `source_kind="computed"`, `contributes_to=["business_visibility"]`,
  `default_enabled=true`, default_weight matching the pack value
  (provenance comment).
- **vertical_lead_signal_weight** rows for the demo vertical, ONE
  row per signal, dimension="overall". Weights hard-coded with
  provenance comment citing the pack source at seed time. `effective_from
  = '2026-05-11 00:00:00+00'`, `effective_to NULL`, `enabled = TRUE`.

`down_revision = "0020_add_pack_id_to_vertical"`.

**Provenance comment block** (template, populated from actual pack at
authoring time):

```
-- Weights mirror the active vertical pack at the time of seeding
-- (B.6A authored 2026-05-11; pack_id = settings.default_vertical_pack_id).
-- DO NOT auto-sync at runtime — see phase-b6a-plan.md §2 decision #4.
-- If pack weights change in vertical_signal_weight before B.6B,
-- re-run this seed OR document the divergence explicitly.
--
-- Source values at seed time:
--   website_presence:           <value>
--   google_business_presence:   <value>
--   content_signals:            <value>
--   reviews:                    <value>
```

### §5.3 What does NOT change

- `vertical_signal_weight` (B.3.3) — legacy pack weights, untouched.
  Authoritative for `analyze()` until B.6B.
- `vertical_template`, `vertical_signal_definition`,
  `lead_event_definition`, all existing leads/lead_signals/
  lead_events/lead_score_snapshot tables — untouched.

---

## §6 Sub-phase breakdown

Six commits after this plan doc. Each commit is independently
revertable. Smoke-test-first, verify-before-commit, stop between.

| Sub-phase | Scope | Smoke gate |
|---|---|---|
| **B.6A.0** | This plan doc | doc renders; references resolve |
| **B.6A.1** | Migrations 0020 + 0021 | alembic upgrade+downgrade clean; demo rows queryable; full backend test suite green |
| **B.6A.2** | `signal_results_to_observations` + unit tests | new tests pass; existing suite green |
| **B.6A.3** | Divergence comparator + log helper + unit tests | dataclass round-trip tests pass; existing suite green |
| **B.6A.4** | `analyze_and_persist` orchestrator + integration tests | orchestrator round-trip writes Lead + 4 LeadSignals + 1 LeadScoreSnapshot in one transaction; existing suite green |
| **B.6A.5** | Test corpus (50 synthetic inputs across 4 signal ranges + "Joe Pizza, Brooklyn, NY" baseline) + replay test | all corpus assertions pass within TOLERANCE=1; replay test passes (snapshot recomputes to identical score) |

Phase closure summary (no code commit) after B.6A.5: verification
pass, update memory with B.6A-complete + B.6B-pending status.

---

## §7 Divergence tooling spec (explainability-first scope)

Per Andrew's directive: "the highest-value outcome is not 'the bridge
exists' — it is 'we can confidently explain WHY the two systems agree
or disagree.'" This section drives B.6A.3 and is referenced by
B.6A.4 and B.6A.5.

### §7.1 What must be answerable

For any single `analyze_and_persist` call, after the fact, an
operator (or test failure output) must be able to answer:

1. What did each side compute? (legacy_score, canonical_score, delta)
2. Per signal, what was the legacy contribution? canonical contribution?
3. Per signal, did the weight differ? Did the score differ? Both?
4. What weight_version_at was used? What weights were active then?
5. Was the result within tolerance? (boolean — drives log severity)
6. If persisted: which Lead / snapshot rows back this?

All six are surfaced by `ScoreDivergence` + `SignalContributionDiff`.

### §7.2 Three consumers

- **Test failures:** `explain_divergence` renders multi-line diff
  that pytest dumps on assertion failure. Reading the test output
  alone tells the engineer which signal misbehaved.
- **Structured log:** `log_divergence` emits one event per call per
  ADR-030. Queryable across whatever volume the test corpus
  generates.
- **Future debug endpoint (deferred):** when read APIs land, a
  diagnostic endpoint can call `compute_divergence` against any
  stored snapshot + the legacy analyzer to re-explain after the
  fact. Not built in B.6A.

### §7.3 Tolerance semantics

- `BRIDGE_DIVERGENCE_TOLERANCE = 1` — accounts for int rounding
  vs Decimal quantize boundary cases.
- Mirror phase (B.6A) tolerance stays at 1.
- Convergence phase (B.6B) MAY tighten to 0 once legacy is retired
  and there is a single source of truth. Single-constant change.

---

## §8 Test surface

### §8.1 Unit tests

- `test_signal_adapter.py`: SignalResult → SignalObservation shape;
  boundary scores (0.0, 0.5, 1.0); reject score outside [0,1];
  source/provenance fields populated.
- `test_scoring_divergence.py`: comparator joins by signal_name;
  missing-on-either-side cases; tolerance boundary; log severity
  selection; explain_divergence formatting.

### §8.2 Integration tests

- `test_analyze_and_persist.py`:
  - happy path: writes 1 Lead + 4 LeadSignals + 1 LeadScoreSnapshot
    in one transaction; returns populated BridgeResult.
  - all-or-nothing: simulated catalog miss raises; no Lead, no
    LeadSignals, no snapshot left behind.
  - divergence populated: BridgeResult.divergence has all 4 signals
    in breakdown; delta within tolerance for the seed weights.

### §8.3 Corpus tests (B.6A.5)

- `test_bridge_corpus.py`:
  - baseline: `("Joe Pizza", "Brooklyn, NY")` — legacy `score == 60`
    preserved; canonical within tolerance.
  - 50 synthetic `(business_name, city)` inputs covering signal
    score ranges (varied deterministic-hash seeds); assert
    `|legacy_int - int(canonical)| <= TOLERANCE` for all.
  - replay: persist a snapshot, re-run `compute_lead_score` with
    stored `inputs` + `weight_version_at`, assert equality (delta=0,
    not just within tolerance — replay is exact).
  - partial-catalog fail: drop one weight row, call orchestrator,
    assert canonical excludes that signal AND legacy includes it AND
    divergence is logged at ERROR (fail-safe in the orchestrator;
    test asserts behavior).

### §8.4 Baseline preservation

The existing baseline `analyze('Joe Pizza','Brooklyn, NY').score == 60`
MUST remain green throughout all 6 sub-phases. The bridge is dark
code; it cannot affect this assertion.

---

## §9 Open items deferred to B.6B

1. Retire `_blended_score`.
2. Refactor `analyze()` into a thin wrapper over
   `analyze_and_persist`.
3. Wire HTTP endpoint to canonical persistence path (feature flag,
   fail-safe).
4. Tighten `BRIDGE_DIVERGENCE_TOLERANCE` to 0 once legacy retired.
5. Tighten `vertical.pack_id` to NOT NULL.
6. Decide whether `vertical_signal_weight` (legacy pack weights)
   table is deprecated, dropped, or repurposed.
7. Real-tenancy resolution (replace demo account).
8. Lead dedupe / upsert semantics.

Each item is one or more B.6B sub-phases. None are in B.6A scope.

---

## §10 Rollback story

B.6A is fully dark code with two migrations:

- Code-only revert (B.6A.2 → B.6A.5): `git revert` removes the new
  files. No production path depends on them. Tests are additive.
  Migrations are unaffected.
- Migration revert: `alembic downgrade -2` drops the seed rows
  (0021 downgrade) and removes the `pack_id` column (0020
  downgrade). Existing vertical/account/lead rows are untouched.
- Full phase revert: code revert + alembic downgrade -2. Repo
  returns to `3152f4a`-equivalent state.

If B.6A.5 corpus tests reveal unfixable divergence: the bridge
stays as latent infrastructure; B.6B is blocked until the
divergence is understood. No prod path was touched, so nothing
breaks; only the convergence plan is paused.

---

## §11 References

**ADRs:**
- ADR-010 (immutable + reproducible runs)
- ADR-011 (signal probes + pack-level config)
- ADR-030 (structured logging)
- ADR-036 (lead signals + dimensions + explainability)
- ADR-044 (deferred event publisher)
- ADR-047 (customer-owned vs platform-owned classification)
- ADR-048 (vertical pack lifecycle)

**Prior phases:**
- B.3.2/B.3.3 — `vertical_signal_weight` (legacy pack weights)
- B.4.2 — lead_event tables + recording
- B.4.3 — `vertical_lead_signal_weight` (lead-scoring weights)
- B.4.4 — lifecycle state machine
- B.4.5 — `record_lead_event` + `record_lead_signal` helpers
- B.5.1 — `lead_score_snapshot` table + repo
- B.5.2 — `compute_lead_score` pure compute primitive
- B.5.3 — `record_lead_score` helper

**Memory:**
- `project_strategic_direction.md`
- `project_platform_directive_v2_authority_infrastructure.md`
- `project_b4_scope_lead_primitives.md`
- `feedback_design_for_scale_implement_for_simplicity.md`
- `feedback_inspectability_over_abstraction.md`
- `feedback_phase_gating.md`
- `feedback_logical_modularity_first.md`
