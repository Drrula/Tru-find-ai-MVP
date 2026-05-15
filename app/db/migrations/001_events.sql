-- ============================================================================
-- 001_events.sql
-- TruSignalAI Phase 0 substrate — canonical append-only event log.
--
-- Locked references:
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §7  (Event Model)
--   - 03_PREQUAL_ENGINE/Phase_0_Execution_Blueprint.md §19 (Day 1 Objective,
--                                                            deliverables 4–5)
--   - 03_PREQUAL_ENGINE/Phase_0_Freeze_Boundary.md §A      (Append-only
--                                                            enforcement: events
--                                                            only)
--   - 03_PREQUAL_ENGINE/Phase_0_Governance_Reconciliation.md  ruling D2 /
--                                                              finding F-H5
--
-- Scope discipline:
--   - This migration creates the events table and its append-only triggers
--     ONLY. No projection tables. No indexes beyond PK + UNIQUE. No CHECK
--     constraints beyond what Blueprint §7 implies.
--   - UPDATE, DELETE, and TRUNCATE on events are rejected at the trigger
--     level. TRUNCATE protection extends Blueprint §7's literal UPDATE/DELETE
--     list to honor the "insert-only event log is non-negotiable" rule —
--     row-level UPDATE/DELETE triggers do not fire on TRUNCATE, so a
--     statement-level BEFORE TRUNCATE trigger is required to close that path.
--   - Append-only enforcement applies to events only (D2 / F-H5). Projection
--     tables remain mutable derived state.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- events — the canonical append-only event log. Source of truth.
-- ---------------------------------------------------------------------------
-- Field set is the Blueprint §7 minimum:
--   event_id, sequence_no, event_type, aggregate_type, aggregate_id,
--   payload, schema_version, occurred_at, recorded_at,
--   actor_type, actor_id, causation_id, correlation_id
--
-- UUIDs and timestamps are generated emitter-side (per Governance &
-- Replayability Part B "UUID sourcing rules" and "Timestamp sourcing rules").
-- The DB does NOT default-fill event_id or any timestamp here — that would
-- introduce non-determinism into the replay path.
-- ---------------------------------------------------------------------------

CREATE TABLE events (
    event_id        UUID         NOT NULL PRIMARY KEY,
    sequence_no     BIGSERIAL    NOT NULL UNIQUE,
    event_type      TEXT         NOT NULL,
    aggregate_type  TEXT         NOT NULL,
    aggregate_id    UUID         NOT NULL,
    payload         JSONB        NOT NULL,
    schema_version  TEXT         NOT NULL,
    occurred_at     TIMESTAMPTZ  NOT NULL,
    recorded_at     TIMESTAMPTZ  NOT NULL,
    actor_type      TEXT         NOT NULL,
    actor_id        TEXT         NOT NULL,
    causation_id    UUID,
    correlation_id  UUID
);

COMMENT ON TABLE events IS
    'Phase 0 canonical append-only event log. UPDATE and DELETE are rejected '
    'by triggers. Source of truth per Blueprint §7. Append-only enforcement '
    'scope is strictly this table (ruling D2 / finding F-H5).';

COMMENT ON COLUMN events.sequence_no IS
    'Monotonic ordering key. BIGSERIAL guarantees per-session monotonicity. '
    'Replay MUST ORDER BY sequence_no ASC.';

-- ---------------------------------------------------------------------------
-- Append-only enforcement (per Blueprint §7 + Freeze Boundary §A).
-- Trigger function names contain "append_only" so the startup verification
-- query (Governance & Replayability §"Append-only enforcement validation")
-- matches them via tgname LIKE '%append_only%'.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION events_reject_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'append_only_violation: UPDATE not allowed on events '
        '(event_id=%, sequence_no=%)',
        OLD.event_id, OLD.sequence_no
        USING ERRCODE = 'P0001';
END;
$$;

COMMENT ON FUNCTION events_reject_update() IS
    'Trigger function: rejects all UPDATE statements on events. '
    'P0001 raise per Blueprint §7. Required by Day-1 deliverable §19.5.';

CREATE OR REPLACE FUNCTION events_reject_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'append_only_violation: DELETE not allowed on events '
        '(event_id=%, sequence_no=%)',
        OLD.event_id, OLD.sequence_no
        USING ERRCODE = 'P0001';
END;
$$;

COMMENT ON FUNCTION events_reject_delete() IS
    'Trigger function: rejects all DELETE statements on events. '
    'P0001 raise per Blueprint §7. Required by Day-1 deliverable §19.5.';

CREATE OR REPLACE FUNCTION events_reject_truncate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'append_only_violation: TRUNCATE not allowed on events'
        USING ERRCODE = 'P0001';
END;
$$;

COMMENT ON FUNCTION events_reject_truncate() IS
    'Trigger function: rejects all TRUNCATE statements on events. '
    'Statement-level trigger — TRUNCATE does not fire row-level UPDATE/DELETE '
    'triggers, so this is required to close the insert-only-bypass path.';

CREATE TRIGGER events_append_only_update
    BEFORE UPDATE ON events
    FOR EACH ROW
    EXECUTE FUNCTION events_reject_update();

CREATE TRIGGER events_append_only_delete
    BEFORE DELETE ON events
    FOR EACH ROW
    EXECUTE FUNCTION events_reject_delete();

CREATE TRIGGER events_append_only_truncate
    BEFORE TRUNCATE ON events
    FOR EACH STATEMENT
    EXECUTE FUNCTION events_reject_truncate();

COMMIT;
