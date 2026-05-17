-- ============================================================================
-- 004_evidence_derived.sql
-- TruSignalAI Phase 0 substrate — third mutable projection:
-- derived-evidence index.
--
-- Locked references:
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §7   (Event Model)
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §19  (Day 1)
--   - 03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md §A       (Append-only on
--                                                             events only)
--   - 03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md ruling D2 /
--                                                              finding F-H5
--
-- Scope discipline (Day-1 Step 10):
--   - Mutable projection derived from evidence.derived_created events.
--   - Disposable / rebuildable derived state. Events remain the sole
--     canonical source-of-truth.
--   - NO append-only triggers — projections rebuildable from the event
--     log (ruling D2 / finding F-H5).
--   - output_payload IS materialized here. It is PROJECTION SUBSTANCE,
--     not auxiliary metadata. Replay recovers it verbatim from the
--     event payload.
--   - Auxiliary derivation metadata (prompt template id, model
--     parameters, retry count, etc.) stays exclusively in events.payload
--     and is queried via JOIN to events ON created_event_id.
--   - derivation_version is materialized here. It records WHICH version
--     of the derivation logic produced this output and is required for
--     replay-explainability, derivation-evolution tracking, auditability,
--     and scoring reproducibility.
--   - subject_entity_id is a SOFT POINTER (no FK to entities.entity_id).
--   - parent_evidence_ids is a UUID[] of soft pointers (NO FK on
--     elements). ORDER IS PRESERVED end-to-end. Non-empty per Blueprint
--     §10/§11 provenance-DAG invariant: derived evidence must reference
--     one or more parents. Enforced at the Pydantic / emit layer via
--     min_length=1.
--   - No UNIQUE constraint on derivation_version or derivation_type.
--     Multiple legitimate derivations can share either value.
--   - No CHECK constraints beyond NOT NULL. The non-empty string
--     constraints on derivation_type / derivation_version are enforced
--     at the Pydantic / emit layer.
--   - No indexes beyond the primary key. Deferred until a real query
--     pattern emerges.
--
-- Migration transaction discipline:
--   - Wrapped in BEGIN; ... COMMIT; to match 001_events.sql,
--     002_entities.sql, and 003_evidence_raw.sql.
-- ============================================================================

BEGIN;

CREATE TABLE evidence_derived (
    derived_evidence_id        UUID         NOT NULL PRIMARY KEY,
    subject_entity_id          UUID         NULL,
    parent_evidence_ids        UUID[]       NOT NULL,
    derivation_type            TEXT         NOT NULL,
    derivation_version         TEXT         NOT NULL,
    output_payload             JSONB        NOT NULL,
    derived_at_for_projection  TIMESTAMPTZ  NOT NULL,
    created_event_id           UUID         NOT NULL REFERENCES events(event_id),
    projected_at               TIMESTAMPTZ  NOT NULL
);

COMMENT ON TABLE evidence_derived IS
    'Phase 0 mutable derived-evidence projection. Derived from '
    'evidence.derived_created events. NOT append-only — projections are '
    'rebuildable from the event log (ruling D2 / finding F-H5). '
    'output_payload IS projection substance and IS materialized here. '
    'Auxiliary derivation metadata stays in events.payload (query via '
    'JOIN to events ON evidence_derived.created_event_id = events.event_id).';

COMMENT ON COLUMN evidence_derived.subject_entity_id IS
    'Soft pointer to entities.entity_id. Intentionally NOT an FK — '
    'matches the existing evidence_raw.subject_entity_id discipline. '
    'May be NULL for derivations without a specific entity subject.';

COMMENT ON COLUMN evidence_derived.parent_evidence_ids IS
    'UUID[] of soft pointers to parent evidence (raw or derived). '
    'ORDER IS PRESERVED end-to-end through the event payload, JSONB '
    'serialization, and the UUID[] column. Non-empty per Blueprint §10/§11 '
    'provenance-DAG invariant: derived evidence must reference one or more '
    'parents. Enforced at the Pydantic / emit layer via min_length=1. '
    'NO FK on the array elements; provenance is by convention at this layer.';

COMMENT ON COLUMN evidence_derived.derivation_type IS
    'Discriminator string identifying the kind of derivation (e.g. '
    '"summary_extraction", "claim_extraction", "compliance_assertion"). '
    'Free-form at this layer; future projections may constrain.';

COMMENT ON COLUMN evidence_derived.derivation_version IS
    'Opaque version string identifying the derivation logic that produced '
    'this output (e.g. "v1.0.0", "summarizer-2026.05@a3f1b2c"). Required '
    'for replay-explainability, derivation-evolution tracking, '
    'auditability, and scoring reproducibility. Free-form at this layer.';

COMMENT ON COLUMN evidence_derived.output_payload IS
    'JSONB output of the derivation, materialized as projection substance '
    '(NOT auxiliary metadata). Recorded verbatim from the event payload; '
    'replay never re-runs the derivation logic.';

COMMENT ON COLUMN evidence_derived.created_event_id IS
    'FK to events(event_id) of the originating evidence.derived_created '
    'event. Provenance link from this mutable projection back to the '
    'append-only source-of-truth. Auxiliary derivation metadata in '
    'events.payload (JSONB) is recovered via JOIN events ON '
    'events.event_id = evidence_derived.created_event_id.';

COMMENT ON COLUMN evidence_derived.projected_at IS
    'Logical projection time, sourced from event.occurred_at — NOT from '
    'wall-clock. Replay produces byte-identical projection rows.';

COMMIT;
