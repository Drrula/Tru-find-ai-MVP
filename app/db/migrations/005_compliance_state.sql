-- ============================================================================
-- 005_compliance_state.sql
-- TruSignalAI Phase 0 (post-Blueprint-§8 expansion) substrate — fourth
-- mutable projection: compliance interpretation layer.
--
-- Locked references (Day-1 substrate discipline carrying forward):
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §7   (Event Model)
--   - 03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md §A       (Append-only on
--                                                             events only)
--   - 03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md ruling D2 /
--                                                              finding F-H5
--
-- ============================================================================
-- DOCTRINE (Day-1 Step 11):
--   compliance_state records POLICY/RISK ASSERTIONS made under a specific
--   policy version and evidence context. Assertions are REPLAYABLE
--   HISTORICAL INTERPRETATIONS, NOT canonical objective truth. The
--   substrate does not enforce policy semantics; it records WHAT was
--   asserted at the time the assertion was made, UNDER WHICH policy
--   version, AGAINST WHICH derived-evidence context. Re-evaluating against
--   today's policy is a DIFFERENT question from what the policy SAID at
--   assertion time, and the substrate preserves both possibilities by
--   recording (policy_id, policy_version, parent_derived_evidence_ids,
--   assertion) verbatim.
-- ============================================================================
--
-- Scope discipline (Day-1 Step 11):
--   - Mutable projection derived from compliance.state_asserted events.
--   - Disposable / rebuildable derived state. Events remain the sole
--     canonical source-of-truth.
--   - NO append-only triggers — projections rebuildable from the event
--     log (ruling D2 / finding F-H5).
--   - assertion IS materialized here. PROJECTION SUBSTANCE — the actual
--     policy/risk claim. Filtering/inspection of assertions is the primary
--     query pattern. Replay recovers it verbatim from the event payload.
--   - parent_derived_evidence_ids is a UUID[] of soft pointers to
--     evidence_derived rows. ORDER IS PRESERVED end-to-end. NON-EMPTY per
--     Step-11 doctrine: compliance assertions must be grounded in at
--     least one derived-evidence parent. Enforced at the Pydantic / emit
--     layer via min_length=1. NO FK on the array elements; provenance is
--     by convention at this layer.
--   - subject_entity_id is a SOFT POINTER (no FK to entities.entity_id) —
--     mirrors evidence_raw.subject_entity_id discipline. NULL allowed
--     for assertions made before the entity exists (e.g. DNC lookup
--     against a phone number whose owning entity has not yet been
--     created in the substrate).
--   - policy_id + policy_version are materialized as query-substantive
--     metadata. Filtering by policy_id and/or policy_version is the
--     primary query pattern for compliance audit and replay-time
--     interpretation reconstruction.
--   - No CHECK constraints beyond NOT NULL. String non-emptiness is
--     enforced at the Pydantic / emit layer.
--   - No UNIQUE constraints. Multiple assertions for the same entity
--     under different policy versions or evidence contexts are
--     legitimate distinct rows.
--   - No indexes beyond the primary key. Deferred until a real query
--     pattern emerges.
--
-- Migration transaction discipline:
--   - Wrapped in BEGIN; ... COMMIT; to match 001/002/003/004.
-- ============================================================================

BEGIN;

CREATE TABLE compliance_state (
    compliance_state_id          UUID         NOT NULL PRIMARY KEY,
    subject_entity_id            UUID         NULL,
    parent_derived_evidence_ids  UUID[]       NOT NULL,
    policy_id                    TEXT         NOT NULL,
    policy_version               TEXT         NOT NULL,
    assertion                    JSONB        NOT NULL,
    asserted_at_for_projection   TIMESTAMPTZ  NOT NULL,
    created_event_id             UUID         NOT NULL REFERENCES events(event_id),
    projected_at                 TIMESTAMPTZ  NOT NULL
);

COMMENT ON TABLE compliance_state IS
    'Phase 0 mutable compliance-state projection. Derived from '
    'compliance.state_asserted events. NOT append-only — projections are '
    'rebuildable from the event log (ruling D2 / finding F-H5). '
    'DOCTRINE: assertions are REPLAYABLE HISTORICAL INTERPRETATIONS under '
    'a specific (policy_id, policy_version) and evidence context — NOT '
    'canonical objective truth. The substrate records what was asserted; '
    'downstream consumers decide what to do with it. Auxiliary evaluator '
    'metadata (runtime, retry count, audit signatures) belongs in '
    'events.payload (query via JOIN to events ON created_event_id).';

COMMENT ON COLUMN compliance_state.subject_entity_id IS
    'Soft pointer to entities.entity_id. Intentionally NOT an FK — mirrors '
    'evidence_raw.subject_entity_id discipline. May be NULL for assertions '
    'made before the entity exists in the substrate (e.g. a DNC lookup '
    'against a phone number whose owning entity has not yet been created).';

COMMENT ON COLUMN compliance_state.parent_derived_evidence_ids IS
    'UUID[] of soft pointers to evidence_derived rows that informed this '
    'assertion. ORDER IS PRESERVED end-to-end through the event payload, '
    'JSONB serialization, and the UUID[] column. Non-empty per Step-11 '
    'substrate doctrine: compliance assertions must be grounded in at '
    'least one derived-evidence parent. Enforced at the Pydantic / emit '
    'layer via min_length=1. NO FK on the array elements; provenance is '
    'by convention at this layer.';

COMMENT ON COLUMN compliance_state.policy_id IS
    'Discriminator string identifying the policy under which this '
    'assertion was made (e.g. "us_dnc_v1", "gdpr_consent", '
    '"hipaa_phi_handling"). Free-form at this layer; future projections '
    'may constrain.';

COMMENT ON COLUMN compliance_state.policy_version IS
    'Version of the policy at the time of assertion (e.g. "1.0.0", '
    '"2024-Q1"). Required for replay-explainability and historical-'
    'interpretation reconstruction: what the policy SAID at assertion '
    'time is preserved verbatim even if the policy itself evolves.';

COMMENT ON COLUMN compliance_state.assertion IS
    'JSONB of the actual policy/risk claim (e.g. '
    '{"compliant": false, "blocker": "phone_on_dnc_list"}). PROJECTION '
    'SUBSTANCE — materialized because filtering and inspection of '
    'assertions is the primary query pattern. Recorded verbatim from the '
    'event payload; replay never re-runs policy evaluation. Auxiliary '
    'evaluator metadata stays in events.payload.';

COMMENT ON COLUMN compliance_state.created_event_id IS
    'FK to events(event_id) of the originating compliance.state_asserted '
    'event. Provenance link from this mutable projection back to the '
    'append-only source-of-truth.';

COMMENT ON COLUMN compliance_state.projected_at IS
    'Logical projection time, sourced from event.occurred_at — NOT from '
    'wall-clock. Replay produces byte-identical projection rows.';

COMMIT;
