"""
app.evidence.projectors — TruSignalAI Phase 0 raw-evidence projector.

Day-1 Step 9 scope:
    - Project evidence.raw_ingested events into the evidence_raw projection.
    - Pure function of (event.payload, event.event_id, event.occurred_at).
    - Single INSERT with ON CONFLICT (evidence_id) DO NOTHING — projecting
      the same event twice is a no-op (idempotence).
    - The caller owns transaction control. The projector performs exactly
      one SQL statement: the INSERT. No reads from the events table.
    - Metadata is NOT copied into the projection — payload metadata stays
      exclusively in events.payload (JSONB), recoverable via JOIN to
      events ON created_event_id when needed.

Replay-determinism contract (Phase_0_Governance_and_Replayability.md Part B):
    - The projector NEVER reads the wall clock, NEVER generates fresh
      identifiers, NEVER reads env vars, NEVER touches local files, NEVER
      makes network calls. Every value written to evidence_raw is derived
      from the event tuple supplied by the caller. Replay over the same
      event log produces byte-identical projection rows.
    - projected_at is sourced from event.occurred_at, NOT from a fresh
      clock read at projection time.

Out of scope (do NOT add here):
    - Metadata column or metadata copy logic.
    - Reads from the events table.
    - Replay engine, dispatcher, registry, or any cross-projection
      orchestration. Each projector is its own narrow function.
    - DNC / compliance / scoring / indicator / reporting code.
    - Storage backend code (MinIO, S3, filesystem). storage_uri is opaque.

Locked references:
    - Phase_0_Execution_Blueprint.md §19 (Day 1 deliverables)
    - Phase_0_Governance_and_Replayability.md Part B (replay-determinism)
    - Phase_0_Freeze_Boundary.md §A (projections mutable, events append-only)
"""

from __future__ import annotations

import psycopg

from app.events.models import Event


# ---------------------------------------------------------------------------
# Private: single-statement INSERT into evidence_raw
# ---------------------------------------------------------------------------

_INSERT_EVIDENCE_RAW_SQL: str = """
INSERT INTO evidence_raw (
    evidence_id, subject_entity_id, source_uri, source_type,
    content_hash, storage_uri, observed_at_for_projection,
    created_event_id, projected_at
) VALUES (
    %(evidence_id)s, %(subject_entity_id)s, %(source_uri)s, %(source_type)s,
    %(content_hash)s, %(storage_uri)s, %(observed_at_for_projection)s,
    %(created_event_id)s, %(projected_at)s
)
ON CONFLICT (evidence_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------


def project_evidence_raw_ingested(conn: psycopg.Connection, event: Event) -> None:
    """
    Project one evidence.raw_ingested Event into the evidence_raw projection.

    Row columns derived from the event:
        evidence_id                 ← event.payload.evidence_id
        subject_entity_id           ← event.payload.subject_entity_id (nullable)
        source_uri                  ← event.payload.source_uri
        source_type                 ← event.payload.source_type
        content_hash                ← event.payload.content_hash
        storage_uri                 ← event.payload.storage_uri
        observed_at_for_projection  ← event.payload.observed_at_for_projection
        created_event_id            ← event.event_id  (provenance FK)
        projected_at                ← event.occurred_at  (NOT wall-clock)

    Idempotence: ON CONFLICT (evidence_id) DO NOTHING. Re-projecting the
    same event leaves the existing row untouched.

    Metadata is intentionally NOT copied to evidence_raw. The originating
    event row in events.payload (JSONB) carries the full payload including
    metadata; consumers query it via:
        JOIN events ON events.event_id = evidence_raw.created_event_id

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction.
        - The caller is responsible for commit() / rollback().
    """
    payload = event.payload
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_EVIDENCE_RAW_SQL,
            {
                "evidence_id": payload.evidence_id,
                "subject_entity_id": payload.subject_entity_id,
                "source_uri": payload.source_uri,
                "source_type": payload.source_type,
                "content_hash": payload.content_hash,
                "storage_uri": payload.storage_uri,
                "observed_at_for_projection": payload.observed_at_for_projection,
                "created_event_id": event.event_id,
                "projected_at": event.occurred_at,
            },
        )
