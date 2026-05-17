"""
app.evidence.projectors — TruSignalAI Phase 0 raw-evidence projector.

Scope:
    - Day-1 Step 9 added `project_evidence_raw_ingested` for the
      evidence_raw projection (raw observation ingestion).
    - Day-1 Step 10 added `project_evidence_derived_created` for the
      evidence_derived projection (outputs of transformation steps over
      existing evidence).
    - Both functions follow the same shape: pure function of
      `(event.payload, event.event_id, event.occurred_at)`. Single INSERT
      with ON CONFLICT DO NOTHING on the projection's PK — projecting the
      same event twice is a no-op (idempotence). The caller owns
      transaction control. No reads from the events table.
    - For evidence_raw: payload metadata is NOT copied into the projection
      and stays exclusively in events.payload (queryable via JOIN to
      events ON created_event_id).
    - For evidence_derived: `output_payload` is PROJECTION SUBSTANCE and
      IS materialized into evidence_derived.output_payload (JSONB).
      Auxiliary derivation metadata stays in events.payload — NOT in
      evidence_derived.

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

import json

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


# ---------------------------------------------------------------------------
# Private: single-statement INSERT into evidence_derived
# ---------------------------------------------------------------------------

_INSERT_EVIDENCE_DERIVED_SQL: str = """
INSERT INTO evidence_derived (
    derived_evidence_id, subject_entity_id, parent_evidence_ids,
    derivation_type, derivation_version, output_payload,
    derived_at_for_projection, created_event_id, projected_at
) VALUES (
    %(derived_evidence_id)s, %(subject_entity_id)s,
    %(parent_evidence_ids)s::uuid[],
    %(derivation_type)s, %(derivation_version)s,
    %(output_payload)s::jsonb,
    %(derived_at_for_projection)s, %(created_event_id)s, %(projected_at)s
)
ON CONFLICT (derived_evidence_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Public projection (derived)
# ---------------------------------------------------------------------------


def project_evidence_derived_created(
    conn: psycopg.Connection, event: Event,
) -> None:
    """
    Project one evidence.derived_created Event into the evidence_derived
    projection.

    Row columns derived from the event:
        derived_evidence_id        ← event.payload.derived_evidence_id
        subject_entity_id          ← event.payload.subject_entity_id
                                     (nullable; soft pointer)
        parent_evidence_ids        ← event.payload.parent_evidence_ids
                                     (UUID[]; order preserved; soft
                                     pointers; no FK on elements)
        derivation_type            ← event.payload.derivation_type
        derivation_version         ← event.payload.derivation_version
        output_payload             ← event.payload.output_payload
                                     (serialized via json.dumps with
                                     sort_keys=True for byte-stable
                                     JSONB; default=str handles
                                     UUID/datetime values the caller
                                     may have supplied inside the dict)
        derived_at_for_projection  ← event.payload.derived_at_for_projection
        created_event_id           ← event.event_id (provenance FK)
        projected_at               ← event.occurred_at (NOT wall-clock)

    Idempotence: ON CONFLICT (derived_evidence_id) DO NOTHING.
    Re-projecting the same event leaves the existing row untouched.

    The projector NEVER re-runs the derivation logic that produced the
    output_payload. The output is recorded verbatim. Replay over the
    same event log produces byte-identical projection rows including the
    output_payload bytes.

    Auxiliary derivation metadata (e.g. prompt template id, model
    parameters, retry count) belongs in events.payload, NOT in this
    projection. The projector keeps evidence_derived narrow to the
    projection-substance fields.

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction.
        - The caller is responsible for commit() / rollback().
    """
    payload = event.payload
    output_payload_json = json.dumps(
        payload.output_payload, sort_keys=True, default=str,
    )
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_EVIDENCE_DERIVED_SQL,
            {
                "derived_evidence_id": payload.derived_evidence_id,
                "subject_entity_id": payload.subject_entity_id,
                "parent_evidence_ids": payload.parent_evidence_ids,
                "derivation_type": payload.derivation_type,
                "derivation_version": payload.derivation_version,
                "output_payload": output_payload_json,
                "derived_at_for_projection": payload.derived_at_for_projection,
                "created_event_id": event.event_id,
                "projected_at": event.occurred_at,
            },
        )
