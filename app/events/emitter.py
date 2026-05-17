"""
app.events.emitter — TruSignalAI Phase 0 single-transaction event emitter.

Scope:
    - Day-1 Step 4 added `emit_entity_created(...)`.
    - Day-1 Step 8 added `emit_evidence_raw_ingested(...)`.
    - Day-1 Step 10 added `emit_evidence_derived_created(...)`.
    - All three functions follow the same shape: generate event_id,
      occurred_at, recorded_at emitter-side; serialize the typed payload
      to JSONB with deterministic key ordering; INSERT one row into the
      events table inside the caller's transaction.
    - The caller owns transaction control (commit / rollback). The emitter
      performs exactly one SQL statement per call: the INSERT. No side
      effects outside the database. No registry, no dispatcher — each
      event type has its own explicit emit function.

Out of scope (deferred to subsequent steps and beyond):
    - Evidence projection / projector (Step 9+).
    - Replay engine module (intentionally absent; replay is proven by
      tests/test_replay_determinism.py, not by a framework).
    - Additional event types beyond the two above.
    - Causation / correlation graph construction beyond passing the IDs.

Replay-determinism contract (Phase_0_Governance_and_Replayability.md Part B):
    - All UUIDs and timestamps are generated HERE, in the emitter, and
      written into the event row. The projector reads them back from the
      row; it never re-derives them. This module is the SOLE generator of
      event_id, occurred_at, and recorded_at for entity.created events.
    - Payload JSON is serialized with `sort_keys=True` so the byte sequence
      handed to JSONB is stable across emits of semantically-identical
      payloads (Mistake #7 prevention). PostgreSQL's JSONB has its own
      internal canonicalization, but stable source bytes matter for any
      future code that hashes or re-emits the original JSON text.

Locked references:
    - Phase_0_Execution_Blueprint.md §7  (events table contract)
    - Phase_0_Execution_Blueprint.md §8  (event-type taxonomy)
    - Phase_0_Execution_Blueprint.md §19 (Day-1 deliverables 6-7)
    - Phase_0_Governance_and_Replayability.md Part B  (replay rules)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import psycopg

from app.events.models import (
    AGGREGATE_TYPE_ENTITY,
    AGGREGATE_TYPE_EVIDENCE,
    EntityCreatedPayload,
    EvidenceDerivedCreatedPayload,
    EvidenceRawIngestedPayload,
    Event,
)


# ---------------------------------------------------------------------------
# Schema versions per event type
# ---------------------------------------------------------------------------
#
# Stored per-event in events.schema_version so future replay can dispatch
# to the correct deserializer at recovery time, even when the codebase has
# moved on. Bump on any structural change to the corresponding payload
# model.
# ---------------------------------------------------------------------------

ENTITY_CREATED_SCHEMA_VERSION: str = "1.0.0"
EVIDENCE_RAW_INGESTED_SCHEMA_VERSION: str = "1.0.0"
EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION: str = "1.0.0"


# ---------------------------------------------------------------------------
# Public emit
# ---------------------------------------------------------------------------


def emit_entity_created(
    conn: psycopg.Connection,
    *,
    payload: EntityCreatedPayload,
    actor_type: str,
    actor_id: str,
    causation_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Event:
    """
    Emit one `entity.created` event for the given payload.

    Generates `event_id`, `occurred_at`, and `recorded_at` here in the
    emitter; persists the resulting Event into the events table; returns
    the populated envelope. The aggregate_id is set to payload.entity_id
    by the entity.* convention (one entity, one aggregate; aggregate_id is
    the entity_id).

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction (psycopg autocommit=False default).
        - The caller is responsible for commit() / rollback(). The emitter
          does neither; this preserves the ability to compose multiple
          emits into one logical write in later days.
    """
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    event = Event(
        event_id=event_id,
        event_type="entity.created",
        aggregate_type=AGGREGATE_TYPE_ENTITY,
        aggregate_id=payload.entity_id,
        payload=payload,
        schema_version=ENTITY_CREATED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type=actor_type,
        actor_id=actor_id,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )

    _insert_event(conn, event)
    return event


def emit_evidence_raw_ingested(
    conn: psycopg.Connection,
    *,
    payload: EvidenceRawIngestedPayload,
    actor_type: str,
    actor_id: str,
    causation_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Event:
    """
    Emit one `evidence.raw_ingested` event for the given payload.

    Generates `event_id`, `occurred_at`, and `recorded_at` here in the
    emitter; persists the resulting Event into the events table; returns
    the populated envelope. The aggregate_id is set to payload.evidence_id
    by the evidence.* convention (one evidence record, one aggregate;
    aggregate_id is the evidence_id). Linkage to an entity, if any, is
    carried in payload.subject_entity_id — NOT in the aggregate graph.

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction (psycopg autocommit=False default).
        - The caller is responsible for commit() / rollback().
    """
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    event = Event(
        event_id=event_id,
        event_type="evidence.raw_ingested",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=payload.evidence_id,
        payload=payload,
        schema_version=EVIDENCE_RAW_INGESTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type=actor_type,
        actor_id=actor_id,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )

    _insert_event(conn, event)
    return event


def emit_evidence_derived_created(
    conn: psycopg.Connection,
    *,
    payload: EvidenceDerivedCreatedPayload,
    actor_type: str,
    actor_id: str,
    causation_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> Event:
    """
    Emit one `evidence.derived_created` event for the given payload.

    Generates `event_id`, `occurred_at`, and `recorded_at` here in the
    emitter; persists the resulting Event into the events table; returns
    the populated envelope. The aggregate_id is set to
    payload.derived_evidence_id by the evidence.* convention (one
    derived-evidence record, one aggregate; aggregate_id is the
    derived_evidence_id). Linkage to one or more PARENT evidence records
    is carried in payload.parent_evidence_ids — NOT in the aggregate
    graph. Linkage to an entity, if any, is carried in
    payload.subject_entity_id.

    Replay-determinism note:
        The derivation logic that produced the output_payload runs
        OUTSIDE this emitter. The emitter records the output verbatim
        with its derivation_version tag. Replay never re-runs the
        derivation; it re-projects the stored output as-is.

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction (psycopg autocommit=False default).
        - The caller is responsible for commit() / rollback().
    """
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    event = Event(
        event_id=event_id,
        event_type="evidence.derived_created",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=payload.derived_evidence_id,
        payload=payload,
        schema_version=EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type=actor_type,
        actor_id=actor_id,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )

    _insert_event(conn, event)
    return event


# ---------------------------------------------------------------------------
# Private: single-statement INSERT into events
# ---------------------------------------------------------------------------


_INSERT_EVENT_SQL: str = """
INSERT INTO events (
    event_id, event_type, aggregate_type, aggregate_id,
    payload, schema_version, occurred_at, recorded_at,
    actor_type, actor_id, causation_id, correlation_id
) VALUES (
    %(event_id)s, %(event_type)s, %(aggregate_type)s, %(aggregate_id)s,
    %(payload)s::jsonb, %(schema_version)s, %(occurred_at)s, %(recorded_at)s,
    %(actor_type)s, %(actor_id)s, %(causation_id)s, %(correlation_id)s
)
"""


def _insert_event(conn: psycopg.Connection, event: Event) -> None:
    """
    INSERT the event row into the events table.

    Payload is JSON-serialized with `sort_keys=True` for byte-stable
    representation (Governance & Replayability Mistake #7). The single
    statement runs inside the caller's transaction; no commit or rollback
    is performed here.
    """
    payload_json = json.dumps(
        event.payload.model_dump(mode="json"),
        sort_keys=True,
    )
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_EVENT_SQL,
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "payload": payload_json,
                "schema_version": event.schema_version,
                "occurred_at": event.occurred_at,
                "recorded_at": event.recorded_at,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "causation_id": event.causation_id,
                "correlation_id": event.correlation_id,
            },
        )
