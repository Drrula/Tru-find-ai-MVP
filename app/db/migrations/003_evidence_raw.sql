-- ============================================================================
-- 003_evidence_raw.sql
-- TruSignalAI Phase 0 substrate — second mutable projection: raw-evidence index.
--
-- Locked references:
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §7   (Event Model)
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §19  (Day 1)
--   - 03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md §A       (Append-only on
--                                                             events only)
--   - 03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md ruling D2 /
--                                                              finding F-H5
--
-- Scope discipline (Day-1 Step 9):
--   - First mutable projection derived from evidence.raw_ingested events.
--   - Disposable / rebuildable derived state. Events remain the sole
--     canonical source-of-truth.
--   - NO append-only triggers on evidence_raw — projections are
--     rebuildable from the event log (ruling D2 / finding F-H5).
--   - NO metadata column. Payload metadata stays exclusively in
--     events.payload (JSONB) and is queried via JOIN to events ON
--     created_event_id when needed. This keeps the projection narrow
--     and the schema commitment minimal.
--   - subject_entity_id is a SOFT POINTER (no FK to entities.entity_id)
--     so that evidence captured before entity creation remains
--     structurally expressible at this layer.
--   - content_hash is intentionally NON-UNIQUE — duplicate observations
--     of the same content (retries, repeated fetches) are legitimate
--     distinct rows; deduplication is a future semantic question, not a
--     projection-layer concern.
--   - No CHECK constraints beyond NOT NULL. The 64-lowercase-hex
--     content_hash invariant is enforced at the Pydantic / emit layer
--     (EvidenceRawIngestedPayload.content_hash regex), which raises
--     before any SQL is touched.
--   - No indexes beyond the primary key. Premature indexing is deferred
--     until a real query pattern emerges.
--
-- Migration transaction discipline:
--   - Wrapped in BEGIN; ... COMMIT; to match 001_events.sql and
--     002_entities.sql. The migration runner in app/db/connection.py
--     also calls conn.commit() after this file runs; the in-file COMMIT
--     keeps each migration's DDL atomically self-contained.
-- ============================================================================

BEGIN;

CREATE TABLE evidence_raw (
    evidence_id                 UUID         NOT NULL PRIMARY KEY,
    subject_entity_id           UUID         NULL,
    source_uri                  TEXT         NOT NULL,
    source_type                 TEXT         NOT NULL,
    content_hash                TEXT         NOT NULL,
    storage_uri                 TEXT         NOT NULL,
    observed_at_for_projection  TIMESTAMPTZ  NOT NULL,
    created_event_id            UUID         NOT NULL REFERENCES events(event_id),
    projected_at                TIMESTAMPTZ  NOT NULL
);

COMMENT ON TABLE evidence_raw IS
    'Phase 0 mutable raw-evidence projection. Derived from '
    'evidence.raw_ingested events. NOT append-only — projections are '
    'rebuildable from the event log (ruling D2 / finding F-H5). '
    'Payload metadata is NOT copied here; query it via JOIN to events.payload '
    'ON evidence_raw.created_event_id = events.event_id.';

COMMENT ON COLUMN evidence_raw.subject_entity_id IS
    'Soft pointer to entities.entity_id. Intentionally NOT an FK so that '
    'evidence captured before entity creation (e.g. a lookup on a phone '
    'number before the entity exists) remains expressible. Future '
    'tightening to FK is out of Step-9 scope.';

COMMENT ON COLUMN evidence_raw.content_hash IS
    'SHA-256 of the raw observed content. Intentionally NON-UNIQUE — '
    'two legitimate ingestions of the same content (retry, repeated fetch) '
    'are valid distinct evidence rows. Format (64 lowercase hex chars) is '
    'enforced at the Pydantic / emit layer, not here.';

COMMENT ON COLUMN evidence_raw.created_event_id IS
    'FK to events(event_id) of the originating evidence.raw_ingested event. '
    'Provenance link from this mutable projection back to the append-only '
    'source-of-truth. The originating events.payload (JSONB) carries the '
    'full envelope including metadata; recover it via '
    'JOIN events ON events.event_id = evidence_raw.created_event_id.';

COMMENT ON COLUMN evidence_raw.projected_at IS
    'Logical projection time, sourced from event.occurred_at — NOT from '
    'wall-clock. Replay produces byte-identical projection rows.';

COMMIT;
