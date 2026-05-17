# CURRENT STATE BRIEF — AI Authority Intelligence Lab + TruSignalAI

**Read this first in any new session before doing work.**
**Workspace mount (Cowork):** `C:\Users\luxco\Tru-find-ai-MVP` — request via `mcp__cowork__request_cowork_directory` at the start of every new Cowork thread before reading any artifact.
**Last updated:** 2026-05-17 (Day-1 substrate Steps 2–11 landed; four-projection chain operational; Blueprint §22 Tests 1 + 2 passing live; 124/124 tests; HEAD `fff4543`)

---

## Foundational operating principle

**Intelligence compounds when continuity survives.**

We are building persistent cognitive continuity infrastructure. Filing, memory, ontology, architecture, and prompts are all part of the same intelligence substrate.

---

## Strategic framing (current)

The AI Authority Intelligence Lab is a research, ontology, benchmark, and calibration arm. TruSignalAI is the future platform/infrastructure layer the Lab feeds. TruFind-Legacy-Live is the existing SMB/contractor operational layer (revenue + telemetry).

The category is **AI Authority Infrastructure** / **Recommendation Intelligence** / **Trust Infrastructure** — not SEO tooling, not generic AI consulting, not dashboards. The moat is the authority graph, longitudinal probe history, recommendation observability, benchmark corpus, ontology, calibration, and provenance-linked evidence — built over time, not shipped as a feature.

The validating thesis: operational business reality and AI-visible authority are frequently disconnected in acquisition rollups, franchise systems, multi-location operators, PE-backed service groups, and legacy-brand portfolios. The A1 Garage / Tommy Mello audit is the founding proof-of-concept.

## Working philosophy (locked)

Headline: substrate integrity over substrate maximalism, reality contact over abstraction, continuity is part of the work, anti-cathedral.

## Robbie / Robot Whisperer

Identity layer recognized but on hold during Phase 0 build. No active content production planned until post-Phase-0. Restore when content effort begins.

## Active architecture decisions (locked)

- **Event sourcing as substrate.** Every state change writes to an immutable event log; projection tables are derivable from events.
- **Append-only enforcement at the database level** via PostgreSQL triggers on `events` only — the canonical and complete Phase 0 enforcement scope per Blueprint §7, Day-1 deliverable §19.5, ruling D2, and finding F-H5. All other tables (observations, evidence, scoring_runs, overrides, ontology_versions, engine_versions, and all projection tables) remain mutable derived state; any future extension of trigger-enforced immutability is deferred beyond Phase 0 and requires a separate governance release.
- **Raw evidence and derived evidence are separate tables** with a DAG of `parent_evidence_ids`. Transformations (classifier outputs, NLP, pattern matching, probe responses) have explicit provenance.
- **Ontology version and engine version are tracked separately.** Engine versions bind to an ontology version. This enables honest longitudinal score-change attribution.
- **Scores must be reproducible from stored evidence.** No score is opaque. Provenance API returns full upstream DAG.
- **Analyst overrides are new records/events, never mutations.** Original observations preserved with `invalidated_by_override_id`.
- **Confidence is exposed, not hidden.** Low indicator coverage caps the recommendation tier regardless of probability.
- **Recommendation tier is derived, not stored.** It is a function of latest scoring run + thresholds, computed at view time.
- **Substrate event chain (post-Blueprint-§8 expansion).** `events → entities → evidence_raw → evidence_derived → compliance_state`. Architectural intent: **events → observations → inferences → policy interpretations** — NOT events → enforcement/actions. The substrate records what was claimed; downstream consumers decide what to do with it. compliance_state assertions are replayable historical interpretations under a specific `(policy_id, policy_version)` and evidence context, NOT canonical objective truth. Re-evaluating against today's policy is a different question from what the policy said at assertion time; the substrate preserves both by recording `(policy_id, policy_version, parent_derived_evidence_ids, assertion)` verbatim.
- **Soft-pointer / no-FK-between-mutable-projections discipline.** Every mutable projection's foreign-key surface is restricted to `created_event_id REFERENCES events(event_id)` (provenance to the immutable source-of-truth). Cross-projection pointers (`subject_entity_id`, `parent_evidence_ids`, `parent_derived_evidence_ids`) are **soft pointers**: same UUID column type, but no DB-level FK constraint. This preserves evidence-before-entity / DNC-before-entity workflows and avoids FK-ordering traps during replay. Dangling-reference detection is a downstream auditor concern, not a substrate concern.

## Phase 0 — LOCKED scope

Full lock list: `03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md`.

- One Python deployable, one Postgres database, one repo. No microservices, no UI, no enterprise workflow, no approval system.
- **Three indicators:** `ACQ_PAGE_PRESENT` (auto), `MULTI_BRAND_DECLARED` (analyst-set; replaces MULTI_TLD_OWNERSHIP), `VERTICAL_BASE_PRIOR` (auto).
- **Two entities:** A1 Garage (flagship) + Aspen Dental (control).
- **Engine v0.1.0 locked.** Weights validated against a 10-operator subset (validation record embedded as the `calibration` block in `engine_releases/v0.1.0.yaml`). Discrimination 0.670 (A1 0.990 vs Aspen 0.320) — computed from the locked engine weights against expected A1/Aspen indicator values.
- **Ontology v1.1.0 locked.** YAML at `ontology_releases/v1.1.0.yaml`.
- Pydantic v2 for event payload validation. Postgres ENUMs deferred. Single test analyst.

## Current Phase 0 status

**Day-1 substrate FULLY LANDED (2026-05-15 → 2026-05-17). Four-projection substrate chain operational: `events → entities → evidence_raw → evidence_derived → compliance_state`. Blueprint §22 Test 1 (append-only enforcement, live) + Test 2 (replay determinism across all four projections, live) passing. 124/124 tests passing. HEAD `fff4543`; tag `day-1-step-11-compliance-state-projection-verified`.**

### Builder model (locked 2026-05-14 evening)

- **Claude Code** is the primary implementation engine. Writes the code, runs migrations, builds projectors, runs the substrate tests.
- **User (Andrew)** remains present and available for all major decisions and architectural questions. Final authority on scope, schedule, and any deviation from the locked Phase 0 Execution Blueprint.
- **ChatGPT** acts as senior continuity / system analyst and governance reviewer. Cross-session continuity checks, strategic-context drift detection, pre-execution architectural review. Does NOT write production code.

Implementation discipline: err on the side of caution. Replayability, provenance integrity, append-only enforcement, and deterministic reconstruction are highest priorities. No speculative expansion. No architecture drift. No Phase 1 features in Phase 0.

### Soft (non-blocking) open items

1. **A1 Garage flagship deliverables location pending** — two files need manual copy from a prior session once a canonical destination is defined. Not blocking the Phase 0 build.
2. **Validation oracle for engine v0.2** — to be defined when v0.2 is planned (consistent with the GR-4 Option A ruling: future calibration/dataset language remains explicitly undefined until formally materialized). Not blocking the v0.1.0 Phase 0 build.
3. **Reconciliation-doc remaining items** — D3 (canonical release paths), D4 (entity naming: "A1 Garage" vs "AI Garage"), D5 (bare "TSA-FRAG" reference in Freeze Boundary §C + other nonexistent references), D6 (§1 → §5 citation), C2 (Blueprint §§4/5 don't list FastAPI / API module), DR-01…DR-15 drift-risk catalog. Source of truth: `03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md` "Remaining unresolved items". Note: item #1 in that section is partly stale — the F-H4/F-H5 alignment edits to Freeze Boundary §A have already landed (denominator=3; append-only=`events`-only). None of these items affect Day-1 scope.
4. **Plain `Union` → Pydantic `Discriminator` upgrade.** Step-8-flagged deferral. Still defensible at four payload types via the disjoint-required-fields invariant + the Event `model_validator` that enforces type-payload pairing and aggregate_id identity. Re-evaluate when a fifth payload type lands (likely candidate: `entity.attribute_set` per Blueprint §8).
5. **DDL bypass paths.** `DROP TABLE events`, `ALTER TABLE events DROP CONSTRAINT`, `ALTER TABLE events DISABLE TRIGGER` are not blocked by the substrate. Mitigation needs a DML-only application DB role; current docker-compose grants the `trusignal` user effective superuser on its own DB.
6. **Docker Compose `version: "3.9"`** in `docker-compose.yml` is treated as deprecated by Compose v2 (warning on every `docker compose` invocation). One-line removal.
7. **Python ignore patterns missing from `.gitignore`.** `__pycache__/`, `.venv-substrate/`, `*.egg-info/`, `.pytest_cache/` are not in `.gitignore` (template is Node-style). They accumulate as untracked-noise after pytest runs.
8. **Test DB isolation.** Tests use the `trusignal` substrate DB with rollback-based per-test isolation. A dedicated `trusignal_test` DB (or schema) is the future-hygiene direction.
9. **Indexes deferred (anti-cathedral).** No B-tree or GIN indexes on `subject_entity_id`, `content_hash`, `parent_evidence_ids`, `parent_derived_evidence_ids`, `derivation_type` / `derivation_version`, `policy_id` / `policy_version`. Add when concrete query patterns demand.

Technical decisions locked: Postgres 15+, MinIO via docker-compose, Typer for CLI, Pydantic v2.

## Next action

**Substrate at a clean post-Step-11 checkpoint.** Four projection layers live; replay determinism proven byte-stable across all four via single-pass sequence_no-ordered events scan + inline `if/elif/elif/elif` dispatch (no replay framework). 124/124 tests passing. Pushed to `origin/main`.

**No next step authorized yet.** Likely future directions surfaced during the Step-4-to-Step-11 sequence but not authorized:

- Additional Blueprint §8 minimum event types not yet landed: `entity.attribute_set`, `entity.domain_registered`, `ontology.version_loaded`, `engine.version_loaded`, `indicator.observed`, `indicator.analyst_set`, `scoring.run_completed`.
- Post-§8 substrate expansion already underway (compliance_state); natural continuation: indicator-layer or scoring-lineage event types riding on top of the existing chain.
- Substrate-hygiene carry-forward items (see "Soft (non-blocking) open items" #4–#9).
- DDL-level substrate hardening (DML-only DB role).

Any of the above requires explicit executive-operator authorization before implementation.

## Pre-build hardening artifacts (2026-05-14 evening)

- `ontology_releases/v1.1.0.yaml` — locked ontology release
- `engine_releases/v0.1.0.yaml` — locked engine release with validated weights (calibration block embedded)
- `03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md` — explicit Phase 0 scope lock
- `03_PREQUAL_ENGINE/Phase_0_Governance_and_Replayability.md` — governance model + replayability discipline + top-10 replay-breaking mistakes

## Key files to read first in a new session

1. **This file** (`CURRENT_STATE_BRIEF.md`) — current status.
2. **`MASTER_INDEX.md`** — what exists and where (pending materialization).
3. **`03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md`** — implementation reference for the first buildable module.

## Memory (auto-loaded continuity)

The memory index `MEMORY.md` (in the Claude memory directory) loads automatically at the start of every new conversation. Individual memory entries are read on demand when relevant. Phase-0-relevant entries in the current index include `project_phase_0_pivot.md`, `project_two_repo_split.md`, `project_strategic_direction.md`, `project_platform_directive_v2_authority_infrastructure.md`, and `feedback_phase_gating.md`. The full set is enumerated in `MEMORY.md`.

---

## Session log

### 2026-05-15 — Week 1 Build thread opened; Day-1 plan locked; no code yet

- **Reconciliation cross-check:** `Phase_0_Governance_Reconciliation.md` exists at `03_PREQUAL_ENGINE/` and is properly chained via `MASTER_INDEX.md` (Supporting Reconciliation Artifact; #4 in Authority Order; #5 in Replayability Entry Points). No authority-chain amendment required.
- **Day-1-impacting rulings already absorbed:** D2 / F-H5 (append-only = `events` only) and F-H4 / F-M2 (confidence denominator = 3) are present in `Phase_0_Freeze_Boundary.md` §A. The Reconciliation doc's "Remaining unresolved items #1" is partly stale on those two points.
- **Day-1 layout decisions locked:**
  - New `app/` package at repo root, alongside legacy `backend/`. Blueprint §5 layout exactly.
  - Plain numbered SQL migrations under `app/db/migrations/` + minimal Python runner. No Alembic in substrate.
  - Substrate Postgres on host port **5433** (backend already occupies 5432 via `infra/dev/docker-compose.yml`). MinIO on 9000/9001.
- **Continuity edit:** workspace-mount line added at the top of this brief on 2026-05-15 to make Cowork re-entry self-evident.
- **State on disk:** no executable substrate yet. No `app/`, no root `pyproject.toml`, no root `docker-compose.yml`. `git tag phase-0-hardening-complete` still at HEAD.

### 2026-05-15 — Day-1 substrate proof landed (Blueprint §22 Test 1 live PASS)

- **Steps 1-3 executed and verified end-to-end on host.** Substrate runtime operational.
- **Migration applied live:** `bootstrap()` returned `['001_events']` on first run; idempotent on subsequent runs.
- **Append-only triggers verified live** via `pg_trigger` query — all three present and in origin-enabled (`tgenabled = 'O'`) state:
  - `events_append_only_update` (BEFORE UPDATE FOR EACH ROW)
  - `events_append_only_delete` (BEFORE DELETE FOR EACH ROW)
  - `events_append_only_truncate` (BEFORE TRUNCATE FOR EACH STATEMENT)
- **Blueprint §22 Test 1 (Append-only event enforcement) — PASS live.** Smoke tests: `5 passed in 0.37s` covering INSERT-succeeds, UPDATE-rejected, DELETE-rejected, TRUNCATE-rejected, and trigger-presence verification.
- **Append-only enforcement scope:** strictly the `events` table (ruling D2 / finding F-H5). Projection tables remain mutable derived state. TRUNCATE protection extends Blueprint §7's literal UPDATE/DELETE list to close the bypass path.
- **Legacy backend untouched:** verified via `git diff --stat HEAD -- backend/ infra/` returning empty.
- **State on disk:** new files: root `pyproject.toml`, `docker-compose.yml`, `app/` with 7 sub-packages (six empty + `db/` populated), `tests/test_events_append_only.py`. Substrate Postgres on host port 5433 (backend retains 5432). MinIO on 9000/9001.
- **Checkpoint tag:** `day-1-substrate-proof` (created at the closeout commit).

### 2026-05-15 → 2026-05-17 — Day-1 substrate chain fully landed (Steps 4–11)

**Substrate chain (live):** `events → entities → evidence_raw → evidence_derived → compliance_state`. Four mutable projections, one append-only event log, no replay framework.

**Tag chain (linear, no gaps):**
- `day-1-substrate-proof` — `99548b7` — Steps 2 + 3 (events table + append-only triggers + bootstrap)
- `day-1-step-4-emitter-verified` — `147a6de` — Step 4 (Pydantic event model + emitter)
- `day-1-step-5-projection-verified` — `84fe2cf` — Step 5 (entities mutable projection + projector)
- `day-1-step-6-replay-verified` — `5179577` — Step 6 (replay-determinism proof for entities)
- `day-1-step-7-pytest-hygiene-verified` — `5405b5e` — Step 7 (`testpaths = ["tests"]` to scope bare pytest to substrate)
- `day-1-step-8-evidence-hardened` — `3b38564` — Step 8 (`evidence.raw_ingested` event type + emitter + hardening: model_validator enforces type-payload pairing AND aggregate_id ↔ payload identity for all event types)
- `day-1-step-9-evidence-projection-verified` — `838f2de` — Step 9 (`evidence_raw` mutable projection + projector + combined two-projection replay)
- `day-1-step-10-evidence-derived-projection-verified` — `40886cb` — Step 10 (`evidence.derived_created` + `evidence_derived` projection with multi-parent `UUID[]` provenance + three-projection combined replay; pre-commit corrections: `parent_evidence_ids` `min_length=1` per Blueprint §10/§11, `derivation_version` naming consistency)
- **`day-1-step-11-compliance-state-projection-verified` — `fff4543`** (HEAD) — Step 11 (`compliance.state_asserted` + `compliance_state` projection; new `app/compliance/` sub-package; four-projection combined replay; doctrine: replayable historical interpretations, not objective truth)

**Architectural invariants now structurally enforced:**
- Append-only enforcement strictly on `events` (D2 / F-H5). Trigger-protected against UPDATE, DELETE, TRUNCATE. FK refusal from each projection's `created_event_id` reinforces TRUNCATE refusal independently.
- Replay-determinism contract per Governance & Replayability Part B: all UUIDs and timestamps emitter-supplied; projectors are pure functions of `(event.payload, event.event_id, event.occurred_at)`; no `datetime.now`, `uuid.uuid4`, `random`, `os.environ`, `open(`, `requests`, `httpx` in any projector — verified by static source-grep tests embedded in each projector test file.
- `json.dumps(sort_keys=True, default=str)` for all JSONB serialization (Mistake #7 prevention).
- `frozen=True, extra="forbid"` on all payloads and the Event envelope.
- Pydantic `model_validator` on `Event` enforces type-payload pairing AND `aggregate_id == payload.<identity_field>` for all four event types.
- Multi-parent provenance: `parent_evidence_ids` (evidence_derived) and `parent_derived_evidence_ids` (compliance_state) are `UUID[]` with order preservation end-to-end (emit → JSONB → SELECT → projection); non-empty enforced via Pydantic `min_length=1` per Blueprint §10/§11 / Step-11 doctrine.
- Soft-pointer / no-FK between mutable projections (see Active architecture decisions, locked).
- Replay-dispatch is inline `if/elif/.../elif` over event_type — no registry, no dispatcher, no replay engine, no framework. Manual maintenance contract carried in WARNING-comment docstrings on each per-type replay helper and at the dispatch point of the combined replay test.

**Verified live:**
- 124/124 tests pass via both `python -m pytest -v` (testpaths-scoped) and `python -m pytest tests/ -v` (explicit path).
- Combined four-projection replay-determinism test (`test_replay_rebuilds_all_four_projections_after_combined_wipe`): emit interleaved entity → raw → derived → compliance events spanning the full chain, snapshot all four projection hashes, DELETE all four projections, replay via single sequence_no-ordered pass with four-way inline dispatch, re-snapshot all four → byte-equal hashes confirmed.
- Append-only enforcement live: INSERT allowed; UPDATE / DELETE / TRUNCATE rejected (P0001 + FK planner refusal).
- Schema-pin tests live on all three mutable projections asserting expected column sets and the absence of auxiliary `metadata` columns (event-payload-only access pattern).

**Scope discipline preserved across all eight steps:**
- Legacy `backend/` untouched (verified at each commit via `git diff HEAD -- backend/ infra/ docs/ 03_PREQUAL_ENGINE/ ontology_releases/ engine_releases/`).
- No DNC enforcement / compliance state machine / scoring / indicators / reporting / Sara / UI / automation / replay-framework / registry / dispatcher code introduced.
- One executive-operator-approved Blueprint §5 expansion: new `app/compliance/` sub-package (8th, beyond the locked 7). All other code respects Blueprint §5's locked layout.
- All commits reference the Blueprint sections they implement; each step landed as its own commit + annotated tag.

### Next-session resume (post-Step-11, post-push)

1. Mount `C:\Users\luxco\Tru-find-ai-MVP` via `mcp__cowork__request_cowork_directory`.
2. Read this brief end-to-end.
3. Confirm substrate state on host:
   - `docker compose ps` — both `trusignal-postgres` and `trusignal-minio` should be Up (healthy). If not: `docker compose up -d` then wait ~10 s.
   - `.\.venv-substrate\Scripts\Activate.ps1`
   - `$env:TRUSIGNAL_DATABASE_URL = "postgresql://trusignal:trusignal@localhost:5433/trusignal"`
   - `python -c "from app.db import connection; print(connection.bootstrap())"` → expect `[]` (idempotent; substrate already bootstrapped through migration 005).
   - `python -m pytest -v` → expect `124 passed`.
4. Verify tag chain: `git log --oneline --decorate -n 10` should show all eight `day-1-step-*` tags landing in order from Step 6 (oldest) through Step 11 (HEAD).
5. **No next step is authorized at this checkpoint.** Wait for executive-operator direction. When direction comes, the established discipline carries over:
   - Plan reviewed before implementation.
   - Per-step audit before commit/tag.
   - Inline `if/elif` replay dispatch only (no framework).
   - Source-grep guards for any new projector.
   - `min_length=1` for any new provenance-pointer array per Blueprint §10/§11 spirit.
   - Soft pointers between mutable projections; FK only to `events`.
   - `frozen=True, extra="forbid"` on all new payloads.
   - Substrate doctrine: events → observations → inferences → policy interpretations. Not events → enforcement / actions.
   - Carry-forward deferrals (above) get addressed when the executive operator authorizes a hygiene-only commit window.
6. No commits without authorization. Daily closeout before sign-off.
