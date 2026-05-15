# MASTER_INDEX.md

## Purpose

This file is the canonical Phase 0 index for the truSignalAI substrate.

It does not create new governance, ontology, execution logic, or architectural authority.

It indexes the materialized Phase 0 hardening artifacts, preserves authority order, and defines where future work must look before acting.

---

## Phase 0 Artifact Set

### Required Blueprint §26 Artifacts

1. `03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md`
2. `03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md`
3. `03_PREQUAL_ENGINE/Phase_0_Governance_and_Replayability.md`
4. `ontology_releases/v1.1.0.yaml`
5. `engine_releases/v0.1.0.yaml`
6. `CURRENT_STATE_BRIEF.md`
7. `MASTER_INDEX.md`

### Supporting Reconciliation Artifact

- `03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md`

This supporting artifact records the reconciliation passes required to align the Phase 0 governance layer without expanding the Blueprint §26 required set.

---

## Authority Order

Future work must preserve the following authority order:

1. Frozen Blueprint / Phase 0 Execution Blueprint
2. Freeze Boundary
3. Governance & Replayability
4. Governance Reconciliation
5. Current State Brief
6. Ontology release
7. Engine release
8. This Master Index

If conflict appears, lower-authority artifacts must not override higher-authority artifacts.

Contradictions must be stopped, surfaced, and reconciled minimally.

---

## Freeze Boundary

The freeze boundary is authoritative for determining what may and may not change during substrate stabilization.

No artifact may introduce new Phase 0 scope, phantom structures, implied systems, or unstated execution behavior.

Permitted work is limited to:

- indexing existing artifacts,
- preserving current authority order,
- recording materialized state,
- supporting replayability,
- and enabling Day-1 substrate proof.

---

## Replayability Entry Points

For future review or replay, begin in this order:

1. `CURRENT_STATE_BRIEF.md`
2. `03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md`
3. `03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md`
4. `03_PREQUAL_ENGINE/Phase_0_Governance_and_Replayability.md`
5. `03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md`
6. `ontology_releases/v1.1.0.yaml`
7. `engine_releases/v0.1.0.yaml`
8. `MASTER_INDEX.md`

---

## Materialization Status

| Artifact | Status |
|---|---|
| `03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md` | materialized |
| `03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md` | materialized + reconciled |
| `03_PREQUAL_ENGINE/Phase_0_Governance_and_Replayability.md` | materialized + reconciled |
| `03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md` | materialized supporting artifact |
| `ontology_releases/v1.1.0.yaml` | materialized |
| `engine_releases/v0.1.0.yaml` | materialized |
| `CURRENT_STATE_BRIEF.md` | materialized + reconciled |
| `MASTER_INDEX.md` | materialized |

---

## Closure Condition

Phase 0 hardening is complete when this file is materialized and reconciled without introducing new scope.

Completion of this index means the Phase 0 substrate is ready for Day-1 substrate proof.

---

## Non-Expansion Rule

This file must not be used to:

- add new ontology objects,
- add new engine behavior,
- reinterpret frozen governance,
- create new required artifacts,
- rename authority layers,
- or reopen settled reconciliation rulings.

It is an index only.

---

## Day-1 Handoff

Day-1 substrate proof must begin from the materialized Phase 0 set listed above.

Any Day-1 execution must first verify:

1. authority order is preserved,
2. freeze boundary is respected,
3. ontology and engine releases are present,
4. current state is replayable,
5. contradictions are stopped rather than patched,
6. and no phantom structure has been introduced.
