# Phase B.5 — Implementation Plan (historical score-state memory primitives)

| Field | Value |
|---|---|
| Status | **Planning DRAFT — pending operator review before B.5.0 commit** |
| Date | 2026-05-11 |
| Scope of B.5 | `lead_score_snapshot` table (append-only, customer-owned, time-series substrate) · `compute_lead_score()` domain function (pure, deterministic — reads stored `lead_signal` + active `vertical_lead_signal_weight`, returns score + breakdown + frozen inputs) · `record_lead_score()` thin helper (compute + persist) · `VerticalLeadSignalWeightRepository.find_all_active_for_vertical()` query method. **Deterministic synthetic test data only.** |
| Out of scope for B.5 | Automated re-scoring · background workers · monitoring loops · score-driven lifecycle transitions · time-decay / windowing in scoring · per-dimension subscores · score-history rollups · AI authority drift analysis (entity inheritance / acquisition fragmentation / recommendation leakage) · Sara memory connection · raw AI-call infrastructure / `ai_probe` table · entity-graph or `entity` abstraction · `/v1/leads/{id}/score` route or any HTTP surface · bulk re-score CLI · real signal probes (LLM / Places / Charlie / 33k-lead ingest) · publisher-based projection of score events · frontend changes |
| Supersedes | none. Extends docs/phase-b-plan.md + phase-b2-plan.md + phase-b3-plan.md + phase-b4-plan.md; inherits every prior phase Lock + ADR. |

---

## 1. Inheritance

Carries forward unchanged:

- B.1 persistence + B.2 auth + B.3 core/vertical separation + B.4 lead persistence primitives.
- All Locked + Blocking ADRs through ADR-048.
- All operating doctrines saved to memory: phase-gating, logical modularity before physical distribution, designed-for-scale-implemented-for-simplicity, inspectability over abstraction, platform identity placeholder, B.4 lead-primitives scope, **Platform Directive v2** (AI authority infrastructure framing — applied quietly, no rewrites).

Specifically load-bearing for B.5:

- **ADR-008** tenancy via `account_id`.
- **ADR-010** immutable + reproducible runs — `lead_score_snapshot` is the lead-scoring analog (frozen inputs + weight version timestamp = replayable).
- **ADR-011** + **ADR-048** verticals-as-data — weights live in `vertical_lead_signal_weight` (B.4.3), not in code.
- **ADR-016** soft-delete on customer-owned data — DOES NOT apply to score snapshots (append-only, like `lead_event` + `lead_signal`).
- **ADR-027** additive-only migrations.
- **ADR-031** repository pattern.
- **ADR-036** lead signals + dimensions + explainability — B.5 reads from the structures B.4.3 laid out.
- **ADR-044** canonical event envelope — B.5 does NOT publish score events (same discipline as B.4.5 recording helpers).
- **ADR-047** customer-owned vs platform-owned — `lead_score_snapshot` is customer-owned + exportable via `/v1/account/export` (future implementation).

New constraints from Andrew's 2026-05-11 directive:

- B.5 is *operational memory infrastructure first*, *adaptive operator intelligence second*, *autonomy much later (if ever)*.
- Historical score-state memory PRIMITIVES only — not autonomous systems.
- Deterministic time-series substrate for future operator intelligence, drift analysis, benchmarking, and explainability — none of those BUILT in B.5; B.5 is what they will read from.

---

## 2. Decisions locked for B.5

| # | Question | Locked answer |
|---|---|---|
| 1 | What is the substrate? | A new append-only `lead_score_snapshot` table that records the result of one scoring computation at one point in time. Schema in §5. |
| 2 | Append-only contract | No `updated_at`, no `deleted_at`. The "current" score for a lead is the latest row (ORDER BY computed_at DESC + id DESC for tie-break, matching the `lead_signal.find_current` pattern from B.4.3). |
| 3 | Ownership classification | Customer-owned per ADR-047 — exportable via `/v1/account/export` once implementation lands. Reflects in the B.3.7 stub's documented contents in a future commit (not in B.5 itself — keep the surface change scoped). |
| 4 | `lead_signal.value` shape | B.5 documents the convention: `lead_signal.value` is a JSONB object with a top-level `'score'` key carrying a numeric in `[0.0, 1.0]`. `compute_lead_score` raises `ValueError` if a referenced signal observation lacks that key — no silent fallback. Future signal probes (real LLM / Places, in later phases) follow this contract. |
| 5 | What if no weights are configured? | `compute_lead_score` returns `(Decimal("0"), {"reason": "no_weights_configured", "signals": []}, {})` explicitly. No NaN, no exception. Tested with the B.4.6 reference pack's empty `lead_signal_weights()` state. |
| 6 | What if a weight exists but no observation? | The signal is **excluded** from the weighted sum — missing observations don't drag the score down, only observed signals contribute. `breakdown` records which weights had no observation under a `"unobserved": [...]` key. |
| 7 | Multi-dimension aggregation | B.5 aggregates across ALL `vertical_lead_signal_weight.dimension` values into a single overall score. `breakdown` records per-dimension contributions in a `"dimensions": {dim_name: {...}}` substructure so future per-dimension subscores can be added without re-running the compute. Per-dimension subscores in the response shape land when business logic demands them. |
| 8 | Score precision | `lead_score_snapshot.score` is `numeric(5,2)`, range `[0.00, 100.00]`. `compute_lead_score` uses `Decimal` arithmetic throughout (matches LOCK §2.4 + ADR-036 `numeric(5,2)` convention). |
| 9 | Score formula | `score = (Σ weight × signal_value) / Σ weight × 100`, where `weight` and `signal_value` are Decimals. Same shape as the existing business-scoring `_blended_score` in `app/domain/scoring.py` — preserves architectural symmetry. |
| 10 | `weight_version_at` semantics | Timestamp used to resolve "active" rows in `vertical_lead_signal_weight` (rows where `effective_from <= weight_version_at AND (effective_to IS NULL OR effective_to > weight_version_at)`). Defaults to `now_fn()` in `compute_lead_score`; pass explicitly for reproducing a past score from history. Stored on `lead_score_snapshot` so re-running the same `weight_version_at` + frozen `inputs` produces the same score (ADR-010 replay semantics). |
| 11 | Persistence | `compute_lead_score` does NOT persist. `record_lead_score` is a thin helper that calls compute + writes the snapshot row via repo. Mirrors B.4.5's `record_lead_event` / `record_lead_signal` shape exactly. |
| 12 | `publish_event` in `record_lead_score` | **No.** Same discipline as B.4.5 recording helpers — the helper does ONE thing (compute + write). Callers who want a structured log line emit `publish_event(...)` themselves. No hidden side-effects. |
| 13 | No automatic re-scoring | `compute_lead_score` + `record_lead_score` are explicit operator/test invocations only. NOT triggered by signal observation, weight change, or lifecycle transition. Future automation lives in a separate phase, behind explicit operator action. |
| 14 | No score-driven lifecycle transitions | B.5 does NOT modify `lead.lifecycle_state` based on score thresholds. The score is a READ-ONLY observation. Operator-driven transitions (B.4.4 `transition`) can be informed by score reads but B.5 never auto-transitions. |
| 15 | Naming — `lead_score_snapshot` vs generalized `entity_score_snapshot` | **Stays `lead_score_snapshot` for B.5.** Per Platform Directive v2: "do NOT rebuild existing system unnecessarily." The `lead*` lineage is the substrate this builds on. A future phase that introduces an `entity` abstraction may add `entity_score_snapshot` as a sibling (additive, not a rename). |
| 16 | Tests | Mock-only `AsyncSession` (per the locked B.X pattern). Deterministic synthetic data. No real-DB integration. Baseline `analyze('Joe Pizza','Brooklyn, NY').score == 60` preserved (B.5 touches lead-scoring only; business-scoring path unchanged). |
| 17 | Frontend | No expansion. B.5 is backend-only. |

---

## 3. Architecture after B.5

```
backend/app/
├── db/
│   ├── models/
│   │   ├── lead_score_snapshot.py     # NEW (B.5.1)
│   │   └── __init__.py                 # extended re-export
│   └── repositories/
│       ├── lead_score_snapshot_repo.py # NEW (B.5.1)
│       └── vertical_lead_signal_weight_repo.py  # MODIFIED (B.5.2)
│           # adds find_all_active_for_vertical(vertical_id)
├── domain/leads/
│   ├── scoring.py                      # NEW (B.5.2) — compute_lead_score
│   ├── recording.py                    # MODIFIED (B.5.3) — adds record_lead_score
│   ├── lifecycle.py                    # unchanged
│   ├── events.py                       # unchanged
│   └── __init__.py                     # extended re-export
└── ... (all other layers unchanged)
```

Key invariants after B.5:

- `lead_score_snapshot` is append-only — BaseRepository.soft_delete refuses on it (no `deleted_at`).
- `compute_lead_score` is a PURE function: same `weight_version_at` + same frozen `inputs` → same score, every time.
- `record_lead_score` is the ONLY way score snapshots are written in B.5+ code (the repo's `create` is the underlying primitive but the helper consolidates the catalog-style validation + the now_fn stamping).
- No code path triggers `compute_lead_score` / `record_lead_score` automatically. Every call is explicit.
- The public surface from `app.domain.leads` extends to: `LIFECYCLE_STATES`, `LIFECYCLE_TRANSITION_EVENT_TYPE`, `transition`, `record_lead_event`, `record_lead_signal`, **`compute_lead_score`**, **`record_lead_score`**.

---

## 4. Domain layer

### `app/domain/leads/scoring.py` (B.5.2)

```python
async def compute_lead_score(
    *,
    lead: Lead,
    vertical_id: UUID,
    lead_signal_repo: LeadSignalRepository,
    weight_repo: VerticalLeadSignalWeightRepository,
    weight_version_at: datetime | None = None,
    now_fn: Callable[[], datetime] = _default_now,
) -> ComputedLeadScore:
    """Pure, deterministic. Reads stored signals + active weights;
    returns (score, breakdown, inputs).

    Same inputs (frozen) + same weight_version_at + same scoring
    logic -> same score. ADR-010 replay semantics.

    Does NOT persist. Caller decides whether to write a snapshot
    via record_lead_score.
    """
```

Returns a `ComputedLeadScore` dataclass (or NamedTuple) with three fields:
- `score: Decimal` — 0..100, 2dp
- `breakdown: dict` — full audit of how the score was computed (per-signal contributions, per-dimension contributions, weights used, total weight, unobserved signals)
- `inputs: dict` — frozen copy of the signal observations consulted (`signal_name → {value, observed_at, source}`)

### `app/domain/leads/recording.py` (B.5.3 — extends B.4.5 module)

```python
async def record_lead_score(
    *,
    lead: Lead,
    vertical_id: UUID,
    lead_signal_repo: LeadSignalRepository,
    weight_repo: VerticalLeadSignalWeightRepository,
    score_repo: LeadScoreSnapshotRepository,
    weight_version_at: datetime | None = None,
    now_fn: Callable[[], datetime] = _default_now,
) -> LeadScoreSnapshot:
    """Compute + persist a lead's score in one explicit call.

    Calls compute_lead_score, then writes a lead_score_snapshot row
    via score_repo.create. Returns the staged snapshot row. No
    publish_event (callers emit canonical envelope separately if
    they want a structured log line).
    """
```

Same shape as `record_lead_event` / `record_lead_signal` — thin wrapper around the compute primitive + the repo write, with `now_fn` injectable for determinism.

---

## 5. Schema design (`lead_score_snapshot`)

```sql
lead_score_snapshot (
  id                    uuid PK,
  account_id            uuid NOT NULL REFERENCES account(id),
  lead_id               uuid NOT NULL REFERENCES lead(id),
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  score                 numeric(5,2) NOT NULL
                        CHECK (score BETWEEN 0 AND 100),
  score_breakdown       jsonb NOT NULL,
  weight_version_at     timestamptz NOT NULL,
  inputs                jsonb NOT NULL,
  computed_at           timestamptz NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now()
)
INDEX (lead_id, computed_at DESC)            -- "latest score for this lead"
INDEX (account_id, vertical_id, computed_at DESC)  -- account-wide score history
```

Customer-owned per ADR-047. Append-only (NO `updated_at`, NO `deleted_at`).

### `score_breakdown` shape

```json
{
  "total_weight": "1.000",
  "weighted_sum": "0.600",
  "score": "60.00",
  "signal_contributions": [
    {
      "signal_name": "lead_quality_score",
      "dimension": "lead_quality",
      "value": "0.5",
      "weight": "0.3",
      "contribution": "0.150"
    }
  ],
  "dimensions": {
    "lead_quality": {
      "weighted_sum": "0.600",
      "total_weight": "1.000"
    }
  },
  "unobserved": [
    {"signal_name": "...", "dimension": "...", "weight": "..."}
  ]
}
```

All numerics serialized as **strings** in JSONB so Decimal precision is preserved through the JSONB round-trip (matches the existing pattern in `vertical_template.config_json` for numerics that round-trip through JSON).

### `inputs` shape

```json
{
  "signals": {
    "lead_quality_score": {
      "value": {"score": 0.5, "details": {...}},
      "observed_at": "2026-05-10T12:00:00+00:00",
      "source": "google_business"
    }
  }
}
```

Frozen copy of the signal observations consulted. Replay-safe: re-running `compute_lead_score` with the same `weight_version_at` + the same active weight rows + the same observations would produce the same score.

---

## 6. Hard rules for B.5+ commits

Carries forward all 12 rules from B.4 §8 unchanged, plus:

13. **`lead_score_snapshot` is append-only.** No UPDATE paths. The repo exposes `create` + named query helpers (`find_current_for_lead`, `find_history_for_lead`, `find_for_account_vertical`) and NO mutators.
14. **`compute_lead_score` is pure.** Same inputs → same output. No I/O outside the repo reads it's given. No `now()` calls except via the injected `now_fn`. No `random()`. No external network.
15. **`record_lead_score` is the recording helper.** Mirrors B.4.5: catalog-validation-then-write + clock stamping. No publish_event, no orchestration, no side-effects beyond the explicit repo write.

---

## 7. Sub-task breakdown

Each sub-task is one commit, verify-then-commit per the locked rule. Chunked staging per `feedback_git_add_in_chunks.md`.

| Sub | Title | Files | Verifies |
|---|---|---|---|
| **B.5.0** | Phase B.5 planning doc | `docs/phase-b5-plan.md` (this file) | Docs-only. Plan exists; future commits trace to it. No code change. Backend + frontend tests still pass at the B.4.6 baseline (550). |
| **B.5.1** | `lead_score_snapshot` table + model + repo (the persistence primitive) | Migration `0019_lead_score_snapshot.py` · `backend/app/db/models/lead_score_snapshot.py` (+ `__init__.py` re-export) · `backend/app/db/repositories/lead_score_snapshot_repo.py` · `backend/tests/test_lead_score_snapshot_model.py` · `backend/tests/test_lead_score_snapshot_repo.py` · `backend/tests/test_migration_chain.py` (head 0018 → 0019) | Migration chains. ORM matches §5 column-for-column. APPEND-ONLY contract enforced by absent `updated_at`/`deleted_at`. Customer-owned (account_id present, tenancy filter active). Repo exposes explicit named methods: `create`, `find_current_for_lead`, `find_history_for_lead`, `find_for_account_vertical`. Inherited `soft_delete` raises NotImplementedError. |
| **B.5.2** | `compute_lead_score` + `VerticalLeadSignalWeightRepository.find_all_active_for_vertical` (the compute primitive) | `backend/app/db/repositories/vertical_lead_signal_weight_repo.py` (extend with `find_all_active_for_vertical`) · `backend/app/domain/leads/scoring.py` (new — `compute_lead_score` + `ComputedLeadScore` result type) · `backend/app/domain/leads/__init__.py` (re-export) · `backend/tests/test_lead_signal_repos.py` (extend with `find_all_active_for_vertical` tests) · `backend/tests/test_lead_scoring.py` (new — `compute_lead_score` behavior + edge cases) | `find_all_active_for_vertical` returns rows where `effective_to IS NULL` (matches `find_active` semantics from B.4.3). `compute_lead_score` is pure, deterministic, idempotent on same inputs. Decimal arithmetic throughout. Edge cases: empty weights → `(0, "no_weights_configured", {})`, missing observation → signal excluded from weighted sum, `value['score']` missing → ValueError (no silent fallback). Reference pack with `lead_signal_weights() == {}` returns `(0, ...)` cleanly. |
| **B.5.3** | `record_lead_score` helper + public surface | `backend/app/domain/leads/recording.py` (extend with `record_lead_score`) · `backend/app/domain/leads/__init__.py` (re-export) · `backend/tests/test_lead_recording.py` (extend with `record_lead_score` tests) | Thin helper: `compute_lead_score(...)` → `score_repo.create(...)` with score/breakdown/inputs from the compute result + `computed_at = now_fn()`. Returns the staged `LeadScoreSnapshot`. NO publish_event (asserted via `recording_publisher.events == []`, matching the B.4.5 discipline guard). Same `now_fn` injection for deterministic testing. |

**4 commits total (planning + 3 implementation). Each independently revertible.**

---

## 8. What B.5 explicitly does NOT do (in addition to §7 hard rules)

- No automated re-scoring on signal observation. `record_lead_score` is operator-explicit.
- No background workers, no async event-bus expansion, no queues.
- No score-driven `lead.lifecycle_state` mutations. Score is read-only.
- No time-decay / windowing in `compute_lead_score`. `find_current` reads the latest observation per signal; decay is a future commit when the right shape is known.
- No per-dimension subscores in the response. Breakdown captures per-dimension contributions for future analysis but the score is single-valued in B.5.
- No score recomputation when weights change. Operator triggers re-score explicitly when needed.
- No `/v1/leads/{id}/score` route or any HTTP surface for lead scoring. Future phase adds it.
- No bulk re-score endpoint or CLI.
- No publisher-based projection of score events (ADR-044 deferral continues).
- No AI authority drift analysis. The `lead_score_snapshot` time-series is the SUBSTRATE drift analysis would eventually use; the analysis logic itself is a future phase.
- No Sara memory connection. Sara is post-B.5.
- No raw AI-call infrastructure / `ai_probe` table. Comes when actual AI calls land.
- No entity / authority-node / citation-source / narrative-signal tables. Per Platform Directive v2, those are anticipated but require real AI calls + entity-graph relationships, not appropriate for B.5.
- No frontend changes.
- No new infrastructure. Single FastAPI + single Postgres unchanged.

---

## 9. Cross-phase implications activated by B.5

When B.5 lands:

- **Lead scores become memorable.** Every operator invocation of `record_lead_score` writes an immutable row capturing what the score was, why (breakdown), and on what inputs (frozen). The time-series accumulates organically as operators (or future automation) score leads.
- **Replay is possible.** A snapshot row + the historical `vertical_lead_signal_weight` rows it referenced (via `weight_version_at`) + the frozen `inputs` reproduces the exact score deterministically. This is the foundation for explainability, audit, and drift analysis.
- **The lead-scoring path mirrors the business-scoring path architecturally.** Both go: stored signals + per-vertical weights → blended numeric score. Business scoring is sync + cache-backed (B.3.4); lead scoring is async (DB-backed) but pure. A future engineer reading either reads the same shape.
- **Customer export gains another exportable surface.** `/v1/account/export` `contents_when_implemented` will eventually list `lead_score_snapshot` rows alongside `lead`, `lead_event`, `lead_signal` (deferred — surface change in a future small commit).
- **Future operator intelligence has a substrate.** Drift analysis, benchmarking, explainability, monitoring — all read from `lead_score_snapshot` rows + `lead_signal` history + `vertical_lead_signal_weight` history. B.5 produces the rows; future phases interpret them.

---

## 10. Pre-flight items for Andrew (between now and `proceed B.5.1`)

- [ ] Confirm the 17 decisions in §2 (or override any). Highest-leverage to flag:
  - #4 — `lead_signal.value['score']` convention (B.5 introduces, future probes follow)
  - #5 — Empty weights → `(Decimal("0"), "no_weights_configured", {})` (no exception)
  - #6 — Missing observations → excluded from weighted sum (don't drag the score)
  - #7 — Multi-dimension aggregation (single overall score; per-dimension in breakdown only)
  - #15 — Naming stays `lead_score_snapshot` (no premature `entity_score_snapshot`)
- [ ] Confirm sub-task ordering in §7 (or rebundle).
- [ ] Operator-side: nothing required for B.5.0. B.5.1 lands migration 0019; operator runs `alembic upgrade head` before any staging deploy.

---

## 11. Sign-off / next gate

| Action | Requires |
|---|---|
| Commit this plan | `commit B.5.0` |
| Push | `push B.5.0` |
| Begin B.5.1 (lead_score_snapshot table + model + repo) | `proceed B.5.1` |
| Override any decision in §2 or §7 | reply with override + revised `proceed B.5.0-amend` |

No auto-proceed beyond this planning commit.
