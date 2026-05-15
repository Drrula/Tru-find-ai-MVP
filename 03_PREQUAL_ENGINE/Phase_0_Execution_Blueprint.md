# Phase 0 Execution Blueprint — TruSignalAI Prequalification Engine

**Status:** Authoritative Phase 0 implementation blueprint
**Phase:** Week 1 substrate build
**Primary builder:** Claude Code
**Oversight:** User + ChatGPT continuity analyst
**Core rule:** If uncertain, stop and ask. Do not guess on substrate, replayability, provenance, schema, or scoring.

---

## 1. Purpose

Phase 0 exists to prove the smallest working TruSignalAI substrate.

It is not the final platform.
It is not a UI product.
It is not a multi-agent system.
It is not an enterprise SaaS layer.

Phase 0 proves that the system can:

- write append-only events
- rebuild projection state deterministically
- preserve provenance
- separate raw and derived evidence
- run simple scoring reproducibly
- support analyst-set indicators
- run one automated indicator path
- expose confidence honestly
- operate from CLI without UI

The goal is substrate integrity, not feature breadth.

---

## 2. Locked Phase 0 Scope

### Exists in Phase 0

- One Python deployable
- One Postgres database
- MinIO object storage for local evidence blobs
- CLI-driven workflow
- Append-only event log
- Deterministic projectors
- Basic entity registry
- Basic ontology loader
- Basic engine release loader
- Evidence raw table
- Evidence derived table
- Indicator observations
- Analyst-set indicator path
- Scoring run table
- Replay test scaffold
- Three Phase 0 indicators:
  - `ACQ_PAGE_PRESENT`
  - `VERTICAL_BASE_PRIOR`
  - `MULTI_BRAND_DECLARED`

### Does not exist in Phase 0

- UI
- React
- dashboards
- customer-facing reports
- multi-agent orchestration
- vector search
- embeddings
- enterprise workflow
- approval system
- multi-tenant architecture
- authentication beyond local development assumptions
- real-time scoring
- probe orchestration
- external LLM comparison system
- large ontology expansion
- more than the locked Phase 0 indicators

### Explicitly removed from Phase 0

`MULTI_TLD_OWNERSHIP` is removed from Phase 0.

Reason:
It introduces unnecessary WHOIS/DNS/scraping fragility before the substrate itself has been proven.

Replacement:
`MULTI_BRAND_DECLARED`

This is an analyst-set indicator and validates human evidence/provenance/override flow without adding external-data instability.

---

## 3. Phase 0 Entities

Initial benchmark entities:

1. **A1 Garage**
   - flagship/complex case
   - expected high prequalification probability
2. **Aspen Dental**
   - control/clean case
   - expected materially lower prequalification probability

Additional operators may be used only for calibration documentation, not implementation expansion.

---

## 4. Technology Choices

Use:

- Python 3.11+
- Postgres 15+
- MinIO via docker-compose for local object storage
- Pydantic v2
- Typer for CLI
- psycopg for Postgres access
- pytest for tests
- ruff for linting
- mypy where practical
- Playwright + httpx for automated page fetches

Do not introduce additional infrastructure without approval.

---

## 5. Repo Structure Target

Create only what Phase 0 needs.

```text
/
  docker-compose.yml
  pyproject.toml
  README.md
  app/
    __init__.py
    db/
      __init__.py
      connection.py
      migrations/
    events/
      __init__.py
      models.py
      emitter.py
      replay.py
    entities/
      __init__.py
      commands.py
      projectors.py
    ontology/
      __init__.py
      loader.py
    evidence/
      __init__.py
      storage.py
      hashing.py
    indicators/
      __init__.py
      acq_page_present.py
      analyst_set.py
    scoring/
      __init__.py
      engine.py
    cli.py
  03_PREQUAL_ENGINE/
    Phase_0_Execution_Blueprint.md
    Phase_0_Freeze_Boundary.md
    Phase_0_Governance_and_Replayability.md
  ontology_releases/
    v1.1.0.yaml
  engine_releases/
    v0.1.0.yaml
  tests/
    test_events_append_only.py
    test_replay_determinism.py
    test_scoring_reproducibility.py
```

If the existing repo has different legacy structure, do not delete or rewrite legacy code without approval.

---

## 6. Replayability Rules

Replayability is load-bearing.

Projectors must be deterministic.

Absolute rules

- No projector may call now().
- No projector may call datetime.now().
- No projector may call uuid4().
- No projector may call random().
- No projector may generate values not present in the event payload.
- All timestamps written to projections must come from event payloads.
- All UUIDs written to projections must come from event payloads.
- Projection state must be rebuildable from the event log alone.
- Any non-determinism is a blocking issue.

If normal implementation convenience conflicts with replayability, replayability wins.

---

## 7. Event Model

The event log is the source of truth.

Every state-changing operation writes an event first.

Projection tables are derived from events.

Events table minimum fields

- event_id UUID primary key
- sequence_no bigint unique monotonic
- event_type text not null
- aggregate_type text not null
- aggregate_id UUID not null
- payload jsonb not null
- schema_version text not null
- occurred_at timestamptz not null
- recorded_at timestamptz not null
- actor_type text not null
- actor_id text not null
- causation_id UUID nullable
- correlation_id UUID nullable

Append-only enforcement

Events must not be updated.
Events must not be deleted.

Postgres triggers must prevent:

- UPDATE on events
- DELETE on events

Insert-only event log is non-negotiable.

---

## 8. Initial Event Types

Phase 0 begins with only the event types needed.

Minimum Day 1 / Week 1 event types:

- entity.created
- entity.attribute_set
- entity.domain_registered
- ontology.version_loaded
- engine.version_loaded
- evidence.raw_ingested
- evidence.derived_created
- indicator.observed
- indicator.analyst_set
- scoring.run_completed

Do not add event types unless required for Phase 0 proof.

---

## 9. Core Projection Tables

Phase 0 projection tables may include:

- entities
- entity_attribute_history
- domains
- ontology_versions
- verticals
- indicator_definitions
- engine_versions
- evidence_raw
- evidence_derived
- indicator_observations
- analyst_overrides
- scoring_runs
- scoring_run_inputs

Projection tables must be rebuildable from events.

Do not treat projection tables as source of truth.

---

## 10. Evidence Model

Raw evidence and derived evidence must remain separate.

### Raw evidence

Represents original collected material.

Examples:

- fetched HTML
- source URL content
- analyst-supplied source document
- page snapshot metadata

Fields should support:

- evidence UUID
- entity UUID
- source URI
- content hash
- storage URI
- retrieval timestamp from event payload
- metadata
- originating event ID

### Derived evidence

Represents transformation output.

Examples:

- classifier output
- pattern match
- extracted acquisition language
- normalized evidence note

Fields should support:

- derived evidence UUID
- parent evidence IDs
- transformation type
- transformation version
- output payload
- originating event ID

Derived evidence must reference parent evidence.

No derived evidence should exist without provenance.

---

## 11. Provenance DAG

Evidence lineage must be traceable.

Raw evidence has no parent.
Derived evidence references one or more parents.
Indicator observations reference evidence.
Scoring runs reference indicator observations.

The intended provenance chain is:

```text
raw evidence
  -> derived evidence
    -> indicator observation
      -> scoring run input
        -> scoring run
```

Phase 0 does not need a polished provenance API.

It does need data shaped so the DAG can be traversed later.

---

## 12. Ontology Versioning

Ontology releases are versioned separately from engine releases.

Phase 0 ontology release:

ontology_releases/v1.1.0.yaml

The ontology defines:

- verticals
- indicators
- indicator roles
- indicator expected evidence
- indicator computation mode

Engine versions bind to ontology versions.

Do not hard-code ontology definitions directly into scoring logic if avoidable.

---

## 13. Engine Versioning

Phase 0 engine release:

engine_releases/v0.1.0.yaml

Engine release defines:

- bound ontology version
- vertical priors
- indicator log-likelihood ratios
- confidence rules
- tier thresholds

Scoring must be reproducible from:

- engine version
- ontology version
- entity state
- observed indicators
- evidence references

No learned parameters in Phase 0.

---

## 14. Phase 0 Indicators

### 14.1 VERTICAL_BASE_PRIOR

Purpose:
Provides baseline prior probability by vertical.

Mode:
lookup/config-driven

Source:
engine release YAML

Example priors:

- GARAGE_DOOR: 0.80
- DENTAL_DSO: 0.70
- HVAC: 0.90
- HOME_SVC_FRANCHISE: 0.85
- VETERINARY: 0.85
- AUTOMOTIVE: 0.60
- INSURANCE: 0.60
- WEALTH: 0.60

This indicator contributes the prior, not an additional log-likelihood ratio.

### 14.2 ACQ_PAGE_PRESENT

Purpose:
Detects whether the operator publicly presents acquisition, partnership, joining, or growth-platform language.

Mode:
automated

Initial implementation:
Fetch selected candidate pages using httpx/Playwright.

Candidate page patterns may include:

- /acquisitions
- /partners
- /partner-with-us
- /join-us
- /sell-your-business
- /growth
- /about
- /news
- /press

Signal:
Present if credible acquisition/partner/join/growth-platform language is found.

Phase 0 tuned weights:

- present: +1.2
- absent: -0.6

Caution:
This is a moderate signal, not definitive proof.
False positives and edge cases are expected.

### 14.3 MULTI_BRAND_DECLARED

Purpose:
Captures whether the operator publicly or analyst-verifiably declares multiple brands, locations, groups, partner companies, acquired operators, or platform portfolio structure.

Mode:
analyst-set

Why Phase 0 uses this:
It validates analyst workflow, evidence provenance, and manual indicator flow without introducing WHOIS/DNS complexity.

Signal:
Analyst sets true/false based on cited evidence.

Evidence requirement:
An analyst-set observation must include at least one evidence reference or a structured note explaining the source.

Phase 0 tuned weights:

- present: +2.0
- absent: -1.0

Caution:
Present is a strong positive signal.
Absent is moderately negative but not absolute.

---

## 15. Scoring Formula

Use Bayesian-logit style scoring.

```text
prior_logit = ln(vertical_prior / (1 - vertical_prior))
posterior_logit = prior_logit + sum(indicator_log_lr_values)
prequal_probability = sigmoid(posterior_logit)
```

Where:

```text
sigmoid(x) = 1 / (1 + exp(-x))
```

Confidence:

```text
confidence = observed_indicators / total_required_phase0_indicators
```

For Phase 0:

```text
total_required_phase0_indicators = 3
```

Required indicators:

- VERTICAL_BASE_PRIOR
- ACQ_PAGE_PRESENT
- MULTI_BRAND_DECLARED

---

## 16. Tier Rules

Initial Phase 0 tier rules:

- flagship_candidate
  - probability >= 0.90
  - confidence >= 0.80
- full_audit_candidate
  - probability >= 0.70
  - confidence >= 0.60
- light_review
  - probability >= 0.50
- watchlist
  - probability >= 0.25
- ignore
  - probability < 0.25

Recommendation tier is derived from scoring run output and thresholds.

Do not store recommendation tier as permanent source-of-truth state.

---

## 17. Calibration Lock

Phase 0 v0.1.0 calibration was manually validated against 10 operators.

Important validation points:

- A1 Garage scored high as flagship candidate.
- Aspen Dental scored materially lower as control.
- A1 vs Aspen discrimination exceeded required threshold.
- Mariner-style hybrid case routed to light review rather than false flagship.
- Missing MULTI_BRAND_DECLARED lowers confidence and prevents premature flagship tier.

This is directionally validated calibration, not statistical finality.

---

## 18. Week 1 Goal

Week 1 proves the substrate can survive first contact with implementation.

Success means:

- append-only events work
- updates/deletes are blocked
- event emitter works
- one projection can be built from events
- replay scaffold exists
- deterministic constraints are respected
- repo structure is established
- Day 1 proof is reviewed before Day 2 expansion

---

## 19. Day 1 Objective

Day 1 objective:
Create the first working substrate proof.

Day 1 deliverables:

1. Repo structure created according to this blueprint
2. docker-compose.yml with Postgres 15+ and MinIO
3. pyproject.toml with required dependencies
4. Initial migration for events table
5. Append-only trigger on events
6. Pydantic v2 event model foundation
7. Minimal event emitter
8. Smoke test:
   - insert event succeeds
   - update event fails
   - delete event fails
9. Initial replay test scaffold

Do not move to Day 2 until Day 1 proof is working and reviewed.

---

## 20. Day 1 Stop Conditions

Stop and ask before proceeding if:

- expected docs are missing
- repo layout conflicts with existing B-phase structure
- migration location is unclear
- event schema conflicts with existing database assumptions
- UUID/timestamp sourcing is unclear
- append-only trigger behavior is uncertain
- test setup requires a shortcut
- implementation would require inventing substrate details

---

## 21. Week 1 Suggested Sequence

Day 1

- repo/document reconciliation
- docker-compose
- pyproject
- events table migration
- append-only trigger
- event model
- event emitter
- append-only smoke test
- replay test scaffold

Day 2

- entity registry tables
- entity event types
- entity projectors
- basic CLI entity commands

Day 3

- ontology loader
- engine loader
- YAML release ingestion
- version tables

Day 4

- evidence raw ingestion
- content hashing
- MinIO storage integration
- evidence raw event path

Day 5

- derived evidence path
- ACQ_PAGE_PRESENT initial implementation
- indicator observation event path

Day 6

- MULTI_BRAND_DECLARED analyst-set flow
- scoring engine
- scoring run event

Day 7

- A1 + Aspen end-to-end
- replay test
- scoring reproducibility test
- Day 1–7 review
- no Phase 2 planning

This sequence may slip.
Replayability must not slip.

---

## 22. Minimum Test Suite

Phase 0 tests should include:

- Append-only event enforcement
  - insert succeeds
  - update fails
  - delete fails
- Replay determinism
  - events replay into same projection state
- Scoring reproducibility
  - same inputs + same engine version produce same probability
- Analyst-set indicator flow
  - analyst observation is recorded as event
  - evidence/note is preserved
- A1 vs Aspen discrimination
  - A1 probability exceeds Aspen by at least 0.30
- Scope boundary test
  - no prohibited Phase 0 features introduced

---

## 23. Implementation Governance

Claude Code may implement.
Claude Code may not silently change architecture.

User remains executive operator.
ChatGPT remains senior continuity/system analyst.

Any uncertainty in the following areas requires pause:

- schema
- event model
- replayability
- provenance
- scoring
- ontology
- engine config
- migration strategy
- scope boundary

No commits until review unless explicitly authorized.

---

## 24. Commit Discipline

Work in small steps.

After each meaningful step, report:

- what changed
- files created/edited
- tests run
- pass/fail status
- unresolved questions
- whether Phase 0 boundary remains intact

Do not bundle unrelated changes.

Do not mix documentation materialization with code implementation unless explicitly approved.

---

## 25. Anti-Cathedral Rules

Do not add architecture because it feels future-useful.
Do not add abstractions before Phase 0 proves the substrate.
Do not create modules that are only theoretical.
Do not build for enterprise scale yet.
Do not add systems to manage systems.

If it does not help prove the Phase 0 substrate, it does not exist yet.

---

## 26. Current Implementation Position

Before Day 1 implementation begins, the authoritative repo artifacts must exist:

- 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md
- 03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md
- 03_PREQUAL_ENGINE/Phase_0_Governance_and_Replayability.md
- ontology_releases/v1.1.0.yaml
- engine_releases/v0.1.0.yaml
- CURRENT_STATE_BRIEF.md
- MASTER_INDEX.md

This blueprint is the first artifact being materialized.

No coding begins until the required artifact set is sufficiently present and reconciled.

---

## 27. Final Rule

The system should prefer a cautious pause over a confident guess.

Substrate truth matters more than speed.
Replayability matters more than convenience.
Provenance matters more than polish.

Phase 0 succeeds only if the foundation can be trusted.
