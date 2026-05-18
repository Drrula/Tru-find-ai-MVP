# Phase 0 — Governance & Replayability Discipline

**Status:** Pre-build governance lock. Read before Week 1 starts.
**Last revised:** 2026-05-17

This file defines two things that must be agreed before code is written: (1) who decides what and how drift is prevented, and (2) the engineering invariants that make event-sourced replay actually work. Both are load-bearing. Skipping either creates the failure modes the readiness review flagged.

---

## Part A — Implementation Governance

### Role model

Three roles. The user is Andrew unless explicitly delegated.

| Role | Held by | Authority |
|---|---|---|
| **Executive operator** | User (Andrew) | Strategic decisions. Final say on scope, schedule, escalations, and any architectural change. |
| **Senior continuity / system analyst** | ChatGPT session(s) acting in continuity-analyst mode | Cross-session continuity checks. Strategic-context drift detection. Pre-execution architectural review. Does NOT write production code. |
| **Implementation worker** | Claude/Cowork (this thread or successor implementation thread) | Code-writing, schema migrations, indicator implementations, CLI/API construction, test writing. Operates within scope defined by the executive operator and architecturally approved by the continuity analyst. |

### Decision boundaries

**Executive operator decides (no implementation without approval):**
- Phase scope changes (e.g., adding/removing an indicator, changing entities)
- Engine version releases (v0.1.0 → v0.2.0)
- Ontology version releases (v1.1.0 → v1.2.0)
- Any deviation from the locked Phase 0 Execution Blueprint
- Adding new dependencies or tools
- Cloud provider / hosting decisions

**Continuity analyst decides:**
- Whether a proposed architectural change preserves substrate integrity
- Whether new artifacts qualify as load-bearing or philosophy inflation
- Whether a session is drifting from established strategic context
- Recommendation: "approve" / "request revision" / "escalate to executive operator"

**Implementation worker decides (within scope):**
- Tactical code structure within a package (e.g., function decomposition)
- Variable naming, internal data structures
- Test fixture composition
- Error message wording
- Whether to use httpx vs requests (within blueprint constraints)
- Local refactoring that does not change schema, events, or formula

### Escalation paths

| Trigger | Escalation |
|---|---|
| Implementation worker hits an architectural ambiguity | Escalate to continuity analyst before coding around it |
| Continuity analyst sees scope creep | Escalate to executive operator with explicit "I think this expands scope, ok?" |
| Substrate test fails repeatedly | Implementation worker → continuity analyst → executive operator if the failure suggests a design flaw vs an implementation bug |
| Calibration drift suspected (e.g., engine v0.1 produces unexpected results on new operator) | Implementation worker pauses scoring expansion → continuity analyst reviews → executive operator approves either weight recalibration or new engine version release |

### Canonical-source discipline

When two tools or two views of substrate state disagree in a way that would affect a corrective action — file restoration, `git reset`, schema repair, projection rebuild, or any other write that "fixes" the apparent state — confirm canonical state before acting.

*Canonical authorities for Phase 0 substrate state:*

- **Filesystem state.** The host filesystem reachable from the executive operator's terminal. Sandbox, container, and mount views that disagree with the host are non-canonical.
- **Git state.** `git status`, `git log`, and `git diff` on the host. Sandbox / container git views that disagree are non-canonical.
- **Projection state.** Deterministic replay from the `events` table at the relevant commit SHA per Part B. Apparent projection divergence is non-canonical until replay confirms.

This doctrine gates corrective action only. Diagnostic activity (read-only inspection, log review, side-by-side comparison) proceeds normally. Escalation reuses the existing role-model paths; no new escalation mechanism is introduced.

### Drift safeguards

These are concrete enforcement mechanisms, not aspirations:

1. **Every code commit must reference the Phase 0 Execution Blueprint section it implements.** If a commit doesn't map to a blueprint section, it requires explicit scope-extension approval.
2. **Schema migrations require continuity analyst review before merge.** This is the highest-risk change category.
3. **Engine release YAML changes require executive operator approval.** Calibration drift hides in here.
4. **No new module without architectural review.** Blueprint §5 locks the `app/` package layout to **7 sub-packages**: `db`, `events`, `entities`, `ontology`, `evidence`, `indicators`, `scoring` (plus the top-level `app/` package and the `cli.py` module). Adding an 8th sub-package requires explicit approval.
5. **Substrate test failures pause new feature work.** If Test 1 (Append-only event enforcement), Test 2 (Replay determinism), or Test 3 (Scoring reproducibility) — the three substrate-integrity tests per Blueprint §22 — fail, the team stops adding features until they pass. Tests 4 (Analyst-set indicator flow), 5 (A1 vs Aspen discrimination), and 6 (Scope boundary test) can be addressed in parallel with other work. Provenance reconstruction, override flow, and confidence transparency are non-gating extension tests (per C5 / reconciled FB) and do not halt feature work.
6. **No new philosophy files during Phase 0.** No new continuity philosophy. Filing discipline only.

### Continuity update discipline

When any of the following happens, the corresponding update is part of the work, not housekeeping:

| Change | Required update |
|---|---|
| New artifact created | Add row to `MASTER_INDEX.md` |
| Active state changes (phase transition, decision locked) | Update `CURRENT_STATE_BRIEF.md` |
| Architectural decision changes | Update or supersede the relevant `.md` file in the canonical Phase 0 directory (`03_PREQUAL_ENGINE/`) |
| Engine version released | Update `engine_releases/v0.X.Y.yaml` with calibration_validation block |
| Ontology version released | New `ontology_releases/vX.Y.Z.yaml` file; do NOT mutate prior versions |
| New session opens | Read `CURRENT_STATE_BRIEF.md` first |

### Ontology change control

Ontology releases are append-only:
- v1.1.0 is the locked Phase 0 release
- v1.2.0 will be the next release (no scope locked; recalibration target dataset to be defined when v1.2 is planned)
- A change to an indicator's `computation_spec` MUST be released as a new ontology version, NOT a modification of an existing version
- New verticals, new indicators, new archetypes can be added as ontology version bumps
- Removing an indicator requires a major version bump (v1.x → v2.0)

### Scoring version control

Engine releases are append-only:
- v0.1.0 is the locked Phase 0 release
- v0.2.0 will require either calibration recalibration against the v1.2 dataset (when defined) OR a formula change
- Weight changes alone get a minor version bump (v0.1.0 → v0.1.1) and require executive operator approval
- Formula changes require a major version bump (v0.X.X → v0.(X+1).0) and require continuity analyst architectural review before approval

### Replay failure handling

When Test 2 (Replay determinism) fails:

1. **Do not "fix" by patching projection tables.** The projection tables are not the truth; the event log is.
2. **Identify the non-deterministic projector.** Common culprits in Part B below.
3. **Fix the projector code.** Add deterministic input sourcing (event payload, not `now()`).
4. **Truncate projections again and re-replay.** Repeat until bit-identical state is achieved.
5. **If a projector cannot be made deterministic without changing the event payload schema:** the event schema is wrong. Either add the missing field to the event payload (and emit new events going forward) OR change the projection logic to derive the missing field from existing event fields.
6. **Never silently accept a "close enough" replay.** Hash comparisons are exact-match.

### Append-only enforcement validation

After every schema migration, run this check:
```sql
SELECT tgname, tgrelid::regclass, tgenabled
FROM pg_trigger
WHERE tgname LIKE '%append_only%';
```
Verify the expected triggers exist and are enabled. Add this as a startup check in the application bootstrap.

If any append-only trigger is missing or disabled at startup: refuse to start. Loud failure, not silent degradation.

---

## Part B — Replayability Discipline

The readiness review identified replayability as the highest practical risk. These rules make Test 2 (Replay determinism) actually pass.

### The replayability invariant

**Replaying the event log from sequence_no=1 to the current sequence_no must produce projection tables that are bit-identical to the live projection tables.**

If this invariant ever breaks, the event log has stopped being the truth, and the entire substrate thesis fails.

### Deterministic projector rules

A projector is a function that consumes an event and writes (only INSERTs) to projection tables. Five rules:

1. **Pure function of the event.** Given the same event, the projector must produce the same output every time. No external state reads from outside the database (no `now()`, no env vars, no random).
2. **All write values come from the event payload OR from prior projection state.** If the projector needs a timestamp, the event payload contains it. If the projector needs a UUID, the event payload contains it. The projector must NEVER call `gen_random_uuid()` or `now()`.
3. **Idempotent on the same event.** Re-applying the same event must be a no-op (or produce identical results). Use `ON CONFLICT DO NOTHING` for the projection's primary keys.
4. **Strictly sequential.** Projectors process events in `sequence_no` order. Out-of-order processing is forbidden during replay.
5. **No side effects outside the projection database.** Projectors do not write to MinIO, do not call APIs, do not log to external systems. Side effects are the emitter's responsibility, not the projector's.

### UUID sourcing rules

All UUIDs needed by projectors MUST come from the event payload, not be generated by the projector.

**Right pattern:**
```python
# Emitter (writes the event):
event_id = uuid.uuid4()
observation_id = uuid.uuid4()  # Generated at emission time
emit_event(
    event_type="observation.recorded",
    aggregate_id=observation_id,
    payload={
        "observation_id": observation_id,  # In payload!
        "entity_id": entity_id,
        ...
    }
)

# Projector (consumes the event):
def project_observation_recorded(event):
    payload = event.payload
    insert_into("indicator_observations", {
        "observation_id": payload["observation_id"],  # From payload
        ...
    })
```

**Wrong pattern (BREAKS REPLAY):**
```python
# WRONG — projector generates UUID:
def project_observation_recorded(event):
    observation_id = uuid.uuid4()  # NON-DETERMINISTIC
    insert_into("indicator_observations", {"observation_id": observation_id, ...})
```

### Timestamp sourcing rules

All timestamps needed by projectors MUST come from the event payload, not generated by the projector.

**Right pattern:**
```python
# Emitter:
occurred_at = datetime.now(UTC)
emit_event(
    event_type="entity.created",
    payload={"entity_id": ..., "created_at_for_projection": occurred_at, ...},
    occurred_at=occurred_at
)

# Projector:
def project_entity_created(event):
    payload = event.payload
    insert_into("entities", {
        "created_event_id": event.event_id,
        "projected_at": event.occurred_at,  # From event, not now()
        ...
    })
```

**Wrong pattern:**
```python
# WRONG — projector calls now():
def project_entity_created(event):
    insert_into("entities", {"projected_at": datetime.now(), ...})  # NON-DETERMINISTIC
```

### Ordering guarantees

- `sequence_no` is a `bigserial` UNIQUE NOT NULL column on the events table. PostgreSQL guarantees monotonic generation.
- **The emitter must INSERT the event in a single transaction.** Do not split event creation across transactions.
- **The projector must process events in strict sequence_no order during replay.** Use `ORDER BY sequence_no ASC`.
- **During live operation, projectors process events as they arrive.** A future evolution may batch, but for Phase 0, one event at a time in order.

### Event payload requirements

Every event payload must contain:

1. The full state-change information needed to project it. If the projector needs field X to write to a table, X must be in the payload.
2. Pre-generated UUIDs for any new rows being created.
3. Logical timestamps that will appear in the projection (e.g., `created_at_for_projection`, `valid_from`).
4. Foreign key references to other aggregates (entity_id, indicator_id, etc.).
5. The complete value being recorded (not a delta against an unspecified prior state).

Payloads should NOT contain:
- Computed values that depend on time of computation (e.g., "current age" — store birth date instead)
- References to mutable external systems (e.g., "current weather" — meaningless on replay)
- Anything that requires re-running expensive computation to reconstruct (e.g., classifier outputs — those go in evidence_derived, not in observation events)

### Anti-mutation safeguards

These are the trigger-enforced and convention-enforced safeguards in Phase 0. The trigger-enforced scope (#1) reflects the canonical Phase 0 enforcement boundary per Blueprint §7, Day-1 deliverable §19.5, ruling D2, and finding F-H5. The convention-enforced safeguards (#3, #4) protect projection state without trigger enforcement.

1. **Database-level triggers** reject UPDATE and DELETE on `events` only. This is the canonical and complete append-only enforcement scope for Phase 0 (per Blueprint §7 and Day-1 deliverable §19.5). Trigger presence and enabled state are verified at application startup; missing or disabled triggers cause loud refusal to start.

2. **No additional trigger-enforced append-only tables or one-way-mutation columns exist in Phase 0.** Per ruling D2 / finding F-H5, projection tables — including `entities`, `analysts`, `entity_attribute_history`, `indicator_observations`, `domains`, and the rest of the schema — remain mutable derived state in Phase 0. Any extension of trigger-enforced immutability beyond `events` (including potential future one-way-mutation columns such as `entity_attribute_history.valid_until`, `indicator_observations.invalidated_by_override_id`, or `domains.soft_deleted`) is **deferred beyond Phase 0** and requires a separate governance release; it must not be silently introduced.

3. **Application-level write discipline:** every state change goes through the event emitter. There is one write path. Direct INSERTs outside the event emitter are forbidden (review-rejectable). Convention-enforced, not trigger-enforced.

4. **DB role separation:** the application's role has DML rights (INSERT) but no DDL or trigger-management rights. Migration scripts use a separate role.

### TOP 10 implementation mistakes most likely to break replay in Week 1

Structured for fast reference during code review. Why each breaks replay, how to detect, how to prevent.

**#1 — `now()` / `datetime.now()` inside a projector.**
- *Why it breaks replay:* The projector writes a wall-clock timestamp on replay that doesn't match the original projection. Row hashes diverge. Test 2 fails.
- *How to detect:* `grep -r 'datetime.now\|time.now\|now()' app/` after any projection code change. Any hit inside a `project_*` function is a bug.
- *How to prevent:* Projectors take an `event` argument and ONLY read fields from `event.payload` and `event.occurred_at`. Code review enforces no `now()` inside projectors. Add a lint rule if practical.

**#2 — Generating UUIDs inside a projector.**
- *Why it breaks replay:* New UUIDs on replay don't match original FK references in downstream tables.
- *How to detect:* `grep -r 'uuid.uuid4\|gen_random_uuid' app/` outside the emitter package. Any hit in projection code is a bug.
- *How to prevent:* Emitter generates ALL UUIDs needed by the event. Payload carries them. Projectors read them from the payload.

**#3 — Migration scripts that temporarily disable triggers and forget to re-enable.**
- *Why it breaks replay:* During the disabled window, a write can occur that bypasses append-only enforcement. Replay reveals state divergence with no event to explain it.
- *How to detect:* Application startup check runs `SELECT tgname FROM pg_trigger WHERE tgname LIKE '%append_only%'` and verifies every expected trigger is present and enabled. Fail loud at boot.
- *How to prevent:* Migrations that need to disable triggers must re-enable them in the same transaction. Code review on every migration touching trigger state.

**#4 — Direct INSERTs to projection tables outside the event emitter.**
- *Why it breaks replay:* The inserted row isn't in the event log. Replay deletes it (no event reconstructs it). Confusion ensues.
- *How to detect:* Code review on any PR that touches a projection table outside the projector function. Search for `INSERT INTO` in non-projector code.
- *How to prevent:* DB role separation. Application role can only write through the event emitter's transaction. Direct DML to projection tables happens only in projectors triggered by events.

**#5 — Caching observation values in the scoring service.**
- *Why it breaks replay:* Cache hit returns a stale value; the score uses it; replay produces different result because cache isn't part of the substrate.
- *How to detect:* Test 2 fails subtly — scores differ between original run and replay run for the same entity.
- *How to prevent:* No caching in Phase 0 scoring. Direct DB reads only. Performance is fine at v0 volumes.

**#6 — Floating-point arithmetic with non-deterministic ordering.**
- *Why it breaks replay:* `sum(weights.values())` may produce slightly different results across Python versions or platforms due to ordering. Sigmoid outputs differ at the 6th decimal.
- *How to detect:* Test 2 fails with tiny float deltas in `prequal_probability`.
- *How to prevent:* Sort indicators by code before summing. Use `Decimal` if precision matters more than performance (Phase 0 doesn't need it). Always use `sorted(indicators.items())` rather than `indicators.items()`.

**#7 — JSON serialization order in payloads.**
- *Why it breaks replay:* `json.dumps(dict)` may serialize keys in insertion order, which can vary. The serialized JSON written to `events.payload` (or any jsonb column derived from it) differs between original write and replay.
- *How to detect:* Row hashes differ on jsonb columns. Comparison shows identical content but different serialization.
- *How to prevent:* `json.dumps(..., sort_keys=True)` everywhere a dict gets serialized for storage. Or store sorted lists of tuples instead of dicts.

**#8 — Event payload schema drift breaking backward compatibility.**
- *Why it breaks replay:* Developer adds a new required field to a Pydantic event model. Old events lack the field. Replay of pre-change events fails Pydantic validation.
- *How to detect:* Replay crashes when it hits an event from before the schema change. Loud, but only at replay time.
- *How to prevent:* New event fields are always Optional with sensible defaults. Old fields are never renamed or removed (deprecate via new event type instead). Add a CI check that replays a captured fixture event log through current code.

**#9 — Out-of-band external state reads in projectors.**
- *Why it breaks replay:* Projector reads from env vars, config files, or external APIs. The external state at replay time differs from the state at original projection time.
- *How to detect:* Code review. Look for `os.environ`, file reads, HTTP calls inside `project_*` functions.
- *How to prevent:* Projectors are pure functions of `(event, current_db_state)`. If a projector needs config (e.g., a vertical prior), the config value must be in the event payload OR be read from another projection table whose state at this `sequence_no` is well-defined.

**#10 — Non-idempotent projectors (double-applying the same event creates duplicate rows).**
- *Why it breaks replay:* Replay re-applies every event. If a projector creates a row each time it sees an event (instead of `ON CONFLICT DO NOTHING` or equivalent), replay produces duplicate rows and primary key violations.
- *How to detect:* Replay fails with `IntegrityError: duplicate key`. Or worse, silently produces more rows than the original projection had.
- *How to prevent:* Every INSERT in a projector uses `ON CONFLICT (pk_columns) DO NOTHING` (or equivalent). Test: apply the same event twice in a row and verify the projection is unchanged after the second application.

### Quick reference

| # | Mistake | Detection method |
|---|---|---|
| 1 | `now()` in projector | grep |
| 2 | UUID generation in projector | grep |
| 3 | Disabled trigger not re-enabled | startup check |
| 4 | Direct INSERT outside emitter | code review + DB role separation |
| 5 | Cache in scoring service | Test 2 deltas |
| 6 | Non-deterministic float sum order | Test 2 deltas |
| 7 | Unsorted JSON serialization | jsonb hash diff |
| 8 | Pydantic schema drift | replay crash |
| 9 | External state read in projector | code review |
| 10 | Non-idempotent projector | duplicate key on replay |

### What to do on Day 1 to test the discipline

Before writing any indicator code, write one event type end-to-end with full replay test. Recommended event: `entity.created`.

- Emit the event.
- Project to `entities` table.
- Snapshot row hash.
- TRUNCATE entities.
- Replay the one event.
- Verify identical row hash.

If this 30-minute test passes, the project is on solid replayability footing (this is the Day-1 prototype of canonical Test 2 — Replay determinism per Blueprint §22). If it fails on Day 1, fix the root cause immediately — it will fail the same way on Day 30 if not fixed now.

---

## Summary — what governance and discipline together prevent

The readiness review surfaced three highest-risk failure modes. Governance and replayability discipline together address all three:

1. **Substrate drift** (scoring weights silently shift, ontology fragments over time) — prevented by ontology/engine version append-only releases + executive approval for changes.
2. **Replay failure** (projections diverge from events; the "events are the truth" thesis breaks) — prevented by deterministic projector rules + UUID/timestamp sourcing + the Day-1 replay test.
3. **Implementation drift** (code expands beyond Phase 0 scope; cathedral re-grows) — prevented by commit-to-blueprint-section requirement + frozen philosophy/continuity additions during Phase 0 + module-count lock.

These are not optional. They are the operating system that makes Phase 0 actually substrate-valid rather than substrate-flavored.
