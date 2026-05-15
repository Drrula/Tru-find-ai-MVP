# Phase 0 — Freeze Boundary

**Status:** Locked 2026-05-14 evening. Pre-build hardening complete.
**Purpose:** Single authoritative source for what Phase 0 contains, does NOT contain, and explicitly defers. Anti-creep enforcement document. If a feature isn't here under EXISTS, it doesn't exist in Phase 0.

---

## A) What EXISTS in Phase 0

### Infrastructure
- One Postgres 15+ database, local Docker-compose deployment.
- One MinIO object store (Docker-compose) for evidence snapshots.
- One Python application: FastAPI + Typer + workers in a single deployable.
- One git repo with the layout from `Phase_0_Execution_Blueprint.md` §5.

### Schema (subset of the full v0.1 spec)
- `events` (append-only)
- `entities`, `entity_attribute_history`, `domains`, `analysts`
- `ontology_versions`, `verticals`, `indicator_definitions`
- `engine_versions`
- `evidence_raw`, `evidence_derived`
- `indicator_observations`
- `analyst_overrides`
- `scoring_runs`, `scoring_run_inputs`

Lookup tables for text-coded columns: NOT enforced via Postgres ENUMs; plain text columns with application-side validation.

### Append-only enforcement
- DB-level triggers reject UPDATE and DELETE on `events` only. This is the canonical and complete append-only enforcement scope for Phase 0, per Blueprint §7 and Day-1 deliverable §19.5; the append-only event log is non-negotiable.
- All other tables — including projection tables such as `entities` and `analysts` — remain mutable derived state in Phase 0. No additional tables or one-way-mutation columns are trigger-enforced as append-only. Any such extension is deferred beyond Phase 0 and requires a separate governance release.

### Indicators (3 only)
- `ACQ_PAGE_PRESENT` (automated). Scrape candidate URLs; present if credible acquisition/partner/join/growth-platform language is found. Boolean output.
- `MULTI_BRAND_DECLARED` (analyst_set). Analyst-set boolean; the observation must include at least one evidence reference or a structured note explaining the source. Replaces the originally-planned MULTI_TLD_OWNERSHIP.
- `VERTICAL_BASE_PRIOR` (config_lookup). Supplies the baseline prior probability for the entity's current vertical attribute. Priors are sourced authoritatively from the engine release YAML (`engine_releases/v0.1.0.yaml` → `vertical_priors`); any `verticals` table prior column is materialized runtime state only, not source of truth.

### Verticals (2 active operational)
- `GARAGE_DOOR` (base prior 0.80)
- `DENTAL_DSO` (base prior 0.70)

The Phase 0 ontology (`ontology_releases/v1.1.0.yaml`) and engine release (`engine_releases/v0.1.0.yaml`) carry 8 verticals in total. The other 6 — `HVAC`, `HOME_SVC_FRANCHISE`, `VETERINARY`, `AUTOMOTIVE`, `INSURANCE`, `WEALTH` — are marked `phase_0: false` and exist for calibration continuity only. `GARAGE_DOOR` and `DENTAL_DSO` are the only active operational Phase 0 verticals.

### Entities (2 only)
- A1 Garage (flagship/complex case; GARAGE_DOOR; ACQ=T, MBD=T expected)
- Aspen Dental (control/clean case; DENTAL_DSO; ACQ=F, MBD=F expected)

### Scoring
- Engine v0.1.0 with locked weights (see `engine_releases/v0.1.0.yaml`).
- Bayesian-logit formula combining vertical prior + indicator log-likelihood ratios.
- Confidence_score = coverage_ratio (observed required Phase 0 indicators ÷ `total_required_phase0_indicators`). The completeness denominator is 3 — all three required Phase 0 indicators (`ACQ_PAGE_PRESENT`, `MULTI_BRAND_DECLARED`, `VERTICAL_BASE_PRIOR`) — per Blueprint §15 and `engine_releases/v0.1.0.yaml`. `VERTICAL_BASE_PRIOR` contributes no log-LR weight but still produces an observation row (retained for provenance and replayability) and counts toward confidence completeness.
- Recommendation tier derived at view time, never stored.

### CLI commands
- entity create / set-vertical / register-domain / show / list
- ontology load
- engine release / show
- evidence ingest / show
- indicators compute / show / set-mbd
- score run / show
- provenance score / observation / evidence
- override apply
- replay
- substrate-tests run

### API endpoints (read-mostly)
- GET /entities/{id}
- GET /entities/{id}/observations
- GET /entities/{id}/scoring-runs
- GET /scoring-runs/{run_id}
- GET /scoring-runs/{run_id}/explain
- GET /provenance/score/{run_id}
- GET /provenance/observation/{obs_id}
- GET /provenance/evidence/{ev_id}/downstream
- GET /candidate-view
- POST /overrides

### Substrate validation tests

The canonical, gating minimum test suite is defined by `Phase_0_Execution_Blueprint.md` §22. All six must pass to exit Phase 0:

1. Append-only event enforcement — insert succeeds, update fails, delete fails
2. Replay determinism — events replay into same projection state
3. Scoring reproducibility — same inputs + same engine version produce same probability
4. Analyst-set indicator flow — analyst observation is recorded as event; evidence/note is preserved
5. A1 vs Aspen discrimination — A1 probability exceeds Aspen by at least 0.30
6. Scope boundary test — no prohibited Phase 0 features introduced

Optional / non-gating extension tests (may exist; do NOT gate Phase 0 exit):

- Provenance reconstruction — full upstream DAG retrievable via API
- Override flow — non-destructive override applies + re-scoring picks up new value
- Confidence transparency — low coverage caps tier regardless of probability

### Release artifacts (already locked)
- `ontology_releases/v1.1.0.yaml`
- `engine_releases/v0.1.0.yaml`

---

## B) What DOES NOT EXIST in Phase 0

These are explicitly out of scope. Adding any of these during Phase 0 requires executive operator approval AND a scope-extension justification.

### Infrastructure absences
- No production deployment. Local Docker only.
- No CI/CD pipeline beyond a basic `pytest` invocation locally.
- No staging environment.
- No load balancing, no horizontal scaling, no replication.
- No backup or disaster recovery procedures.
- No monitoring or alerting infrastructure.
- No log aggregation service.
- No APM or tracing.

### Module absences
- No microservices. Modules are Python packages in one deployable, not independent services.
- No Snapshot Lineage Service (deferred to Phase 1).
- No Candidate View as a separate module (it's a query/function).
- No Override Recorder as a separate module (it's a handler in the overrides package).
- No Provenance Graph Service as a separate module (it's read-only API routes).

### Schema absences
- No `archetypes` table.
- No `probe_templates` table.
- No `probe_executions` table.
- No `entity_snapshots` table.
- No `sub_brands` table.
- No partitioning on any table.
- No GIN indexes on uuid[] columns (deferred until performance demands).
- No materialized views.
- No multi-tenant columns (no `tenant_id` anywhere).

### Feature absences
- **No UI of any kind.** No React, no Streamlit, no Jupyter notebooks for demo, no admin panel.
- No cross-LLM probe orchestration. No probes at all in Phase 0.
- No ML-learned weights. All weights are analyst-set.
- No agent orchestration. No multi-agent systems.
- No notification system. No alerting. No webhooks.
- No real-time scoring. Batch-only.
- No scheduled re-scoring. Manual trigger via CLI only.
- No bulk operations (no bulk entity import, no bulk scoring).
- No operator engagement / outreach tooling.
- No external authentication. Single hardcoded API key for the one analyst.
- No vector index, embeddings, or semantic search.
- No cold storage or archival tier.
- No customer-facing reports.

### Indicator absences
- No fourth or fifth indicator. Three only.
- No additional active operational verticals beyond GARAGE_DOOR and DENTAL_DSO. (The ontology and engine releases carry 6 further `phase_0: false` verticals for calibration continuity; these are not operationally active in Phase 0.)
- No archetype detection running in Phase 0.

### Workflow absences
- No approval workflow for overrides. Single analyst, single approval.
- No analyst authority levels. One analyst, one permission set.
- No assignment workflow. No analyst inboxes. No reviewer queues.

### Engine absences
- No engine v0.2. Engine v0.1.0 is the only released version.
- No A/B comparison between engine versions in Phase 0.
- No formula changes after lock. The Bayesian-logit formula in engine v0.1.0 is final for Phase 0.

### Continuity absences
- No new philosophy files during Phase 0.
- No additional prompts archived during Phase 0 unless explicitly approved.
- No new memory entries unless they capture a load-bearing project shift (not minor adjustments).

---

## C) What is DEFERRED to Phase 1+

These are real future work items. They're not abandoned — they're sequenced after substrate proof.

### Deferred to Phase 1
- MULTI_TLD_OWNERSHIP indicator (re-introduced as a supporting signal for MULTI_BRAND_DECLARED, not standalone).
- Snapshot Lineage Service module + `entity_snapshots` table.
- Additional indicators (RETENTION_LANGUAGE LLM classifier, M&A velocity from feed, multi-state brand variation).
- Activation of additional operational verticals (HVAC, VETERINARY, AUTOMOTIVE, etc.). These already exist in the ontology and engine releases as `phase_0: false` calibration-continuity entries; Phase 1 promotes selected ones to active operational status.
- Cross-engine-version score comparison endpoints.
- Approval workflow for overrides (when 2+ analysts exist).
- Scheduled re-scoring (cron-style).

### Deferred to Phase 2+
- Cross-LLM probe orchestration (belongs to the full TSA-FRAG scoring engine, conceptually distinct from prequalification).
- Probe templates and probe_executions tables.
- RETENTION_LANGUAGE classifier with held-out validation set.
- Real-time scoring triggered by external events.
- Public-facing API authentication (OAuth, JWT).
- Customer dashboards (if/when commercialization begins).

### Deferred to Phase 3+
- ML-learned weight recalibration (logistic regression once labeled-data volume permits).
- Inter-service event bus (Kafka/NATS) if message volume justifies.
- Table partitioning by aggregate_type.
- Cold storage / archival policies.
- Vector index for semantic operator similarity.
- Multi-tenant architecture (if commercialization requires).

### Deferred indefinitely (re-evaluate annually)
- Production-grade UI / dashboard.
- Notification system.
- Operator engagement tooling.
- Agent orchestration.

---

## Boundary enforcement

When Phase 0 is in progress and a new request arrives ("can we also add X?"), apply this filter:

1. Is X in section A (EXISTS)? → Already in scope. Continue.
2. Is X in section B (DOES NOT EXIST)? → Reject unless executive operator approves a scope extension.
3. Is X in section C (DEFERRED)? → Acknowledge it's planned for the right phase. Document in `CURRENT_STATE_BRIEF.md` under "Open questions" if the timing is unclear. Do NOT build during Phase 0.

The default answer to "can we add this to Phase 0?" is NO. Justifying YES requires a written explanation of why the substrate cannot be validated without it.

---

## Phase exit criteria

Phase 0 exits when all six canonical substrate tests (`Phase_0_Execution_Blueprint.md` §22) pass. Not when "the platform is complete." Not when "the dashboard looks good." Not when "we have more entities."

The exit gate is six green tests on one minimal substrate-validated system. Then Phase 1 begins.
