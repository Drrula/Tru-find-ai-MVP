-- ============================================================================
-- 002_entities.sql
-- TruSignalAI Phase 0 substrate — first mutable projection table.
--
-- Locked references:
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §7  (Event Model)
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §19 (Day 1 Objective,
--                                                            deliverables 6–7)
--   - 03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md §A      (Append-only
--                                                            enforcement: events
--                                                            only — projections
--                                                            remain mutable)
--   - 03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md ruling D2 /
--                                                              finding F-H5
--
-- Scope discipline:
--   - This migration creates the entities projection table ONLY.
--   - NO append-only triggers on entities. Projections are rebuildable
--     derived state; mutability is required so replay can rebuild them
--     from the event log (Governance & Replayability Part B).
--   - NO scoring columns, NO indicator columns, NO reporting fields,
--     NO replay-tracking tables. Day-1 Step 5 scope is exactly this
--     six-column entities table and nothing more.
--   - created_event_id is a FK to events(event_id) — the projection row
--     is provenance-linked to the originating event, so any row can be
--     traced back to the append-only source of truth.
-- ============================================================================

BEGIN;

CREATE TABLE entities (
    entity_id                  UUID         NOT NULL PRIMARY KEY,
    name                       TEXT         NOT NULL,
    vertical                   TEXT         NOT NULL,
    created_at_for_projection  TIMESTAMPTZ  NOT NULL,
    created_event_id           UUID         NOT NULL REFERENCES events(event_id),
    projected_at               TIMESTAMPTZ  NOT NULL
);

COMMENT ON TABLE entities IS
    'Phase 0 first mutable projection. Derived from entity.created events. '
    'No append-only triggers — projections are rebuildable from the event log '
    '(ruling D2 / finding F-H5). Provenance is preserved via created_event_id.';

COMMENT ON COLUMN entities.created_at_for_projection IS
    'Logical entity-creation time, copied verbatim from the originating '
    'entity.created event payload. The projector NEVER recomputes this — '
    'replay determinism (Governance & Replayability Part B, Mistake #1).';

COMMENT ON COLUMN entities.created_event_id IS
    'FK to events(event_id) of the originating entity.created event. '
    'Provenance link from mutable projection back to append-only source.';

COMMENT ON COLUMN entities.projected_at IS
    'Logical projection time, sourced from event.occurred_at — NOT from '
    'wall-clock. Replay produces byte-identical projection rows.';

COMMIT;
