# CURRENT STATE BRIEF — AI Authority Intelligence Lab + TruSignalAI

**Read this first in any new session before doing work.**
**Workspace mount (Cowork):** `C:\Users\luxco\Tru-find-ai-MVP` — request via `mcp__cowork__request_cowork_directory` at the start of every new Cowork thread before reading any artifact.
**Last updated:** 2026-05-15 (Day-1 substrate proof landed; Blueprint §22 Test 1 passing live)

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

## Phase 0 — LOCKED scope

Full lock list: `03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md`.

- One Python deployable, one Postgres database, one repo. No microservices, no UI, no enterprise workflow, no approval system.
- **Three indicators:** `ACQ_PAGE_PRESENT` (auto), `MULTI_BRAND_DECLARED` (analyst-set; replaces MULTI_TLD_OWNERSHIP), `VERTICAL_BASE_PRIOR` (auto).
- **Two entities:** A1 Garage (flagship) + Aspen Dental (control).
- **Engine v0.1.0 locked.** Weights validated against a 10-operator subset (validation record embedded as the `calibration` block in `engine_releases/v0.1.0.yaml`). Discrimination 0.670 (A1 0.990 vs Aspen 0.320) — computed from the locked engine weights against expected A1/Aspen indicator values.
- **Ontology v1.1.0 locked.** YAML at `ontology_releases/v1.1.0.yaml`.
- Pydantic v2 for event payload validation. Postgres ENUMs deferred. Single test analyst.

## Current Phase 0 status

**Day-1 substrate proof LANDED (2026-05-15). Blueprint §22 Test 1 passing live. Append-only event substrate operational.**

### Builder model (locked 2026-05-14 evening)

- **Claude Code** is the primary implementation engine. Writes the code, runs migrations, builds projectors, runs the substrate tests.
- **User (Andrew)** remains present and available for all major decisions and architectural questions. Final authority on scope, schedule, and any deviation from the locked Phase 0 Execution Blueprint.
- **ChatGPT** acts as senior continuity / system analyst and governance reviewer. Cross-session continuity checks, strategic-context drift detection, pre-execution architectural review. Does NOT write production code.

Implementation discipline: err on the side of caution. Replayability, provenance integrity, append-only enforcement, and deterministic reconstruction are highest priorities. No speculative expansion. No architecture drift. No Phase 1 features in Phase 0.

### Soft (non-blocking) open items

1. **A1 Garage flagship deliverables location pending** — two files need manual copy from a prior session once a canonical destination is defined. Not blocking the Phase 0 build.
2. **Validation oracle for engine v0.2** — to be defined when v0.2 is planned (consistent with the GR-4 Option A ruling: future calibration/dataset language remains explicitly undefined until formally materialized). Not blocking the v0.1.0 Phase 0 build.
3. **Reconciliation-doc remaining items** — D3 (canonical release paths), D4 (entity naming: "A1 Garage" vs "AI Garage"), D5 (bare "TSA-FRAG" reference in Freeze Boundary §C + other nonexistent references), D6 (§1 → §5 citation), C2 (Blueprint §§4/5 don't list FastAPI / API module), DR-01…DR-15 drift-risk catalog. Source of truth: `03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md` "Remaining unresolved items". Note: item #1 in that section is partly stale — the F-H4/F-H5 alignment edits to Freeze Boundary §A have already landed (denominator=3; append-only=`events`-only). None of these items affect Day-1 scope.

Technical decisions locked: Postgres 15+, MinIO via docker-compose, Typer for CLI, Pydantic v2.

## Next action

**Open the implementation thread: `TruSignalAI Phase 0 — Week 1 Build`.**

In that thread, begin Day 1 substrate proof:
1. Repo bootstrap (pyproject.toml, docker-compose.yml with Postgres 15 + MinIO).
2. Migration 001: `events` table + append-only trigger function + trigger.
3. Smoke test: insert event, verify INSERT works; attempt UPDATE/DELETE, verify exceptions raised.
4. `app/events/` package: emitter function, Pydantic model for `entity.created`.
5. `app/entities/` package: projector for `entity.created`, projection to `entities` table.
6. The 30-minute Day-1 replay test: emit `entity.created` → project to `entities` → snapshot row hash → TRUNCATE entities → replay the event → verify identical row hash.

If the Day-1 replay test passes, Day 1 is complete and replayability discipline is on solid footing. If it fails, fix the root cause before any further work.

This thread (current) is the pre-build hardening thread. Closed.

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

### Next-session resume

1. Mount `C:\Users\luxco\Tru-find-ai-MVP` via `mcp__cowork__request_cowork_directory`.
2. Read this brief end-to-end.
3. Bring substrate services up: `docker compose up -d`; verify health with `docker compose ps`. Activate the substrate venv: `.\.venv-substrate\Scripts\Activate.ps1`.
4. Confirm substrate state still valid: `python -c "from app.db import connection; print(connection.bootstrap())"` should return `[]` (idempotent — substrate already bootstrapped).
5. **Resume at Day-1 Step 4:** Pydantic event-model foundation + emitter.
   - `app/events/models.py` — base `Event` envelope (matches Blueprint §7 events-table fields) + first concrete payload model `EntityCreatedPayload` (entity_id, name, vertical, created_at_for_projection). All UUIDs and timestamps emitter-supplied per Governance & Replayability Part B "UUID sourcing rules" and "Timestamp sourcing rules".
   - `app/events/emitter.py` — single-transaction INSERT into `events`; JSON payload serialized with `sort_keys=True` (Governance Mistake #7 prevention).
   - Smoke test: emit one `entity.created` event for **A1 Garage Doors** (the canonical archetype per Blueprint §3 and the user's testing instruction). Verify row appears in `events`.
6. Then Day-1 Steps 5-7: entity projector (`app/entities/projectors.py`) + migration 002 (`entities` mutable projection) → 30-minute replay test (`tests/test_replay_determinism.py`) → Day-1 checkpoint report.
7. No commits until authorized. Daily closeout before sign-off.
