"""
tests/test_replay_determinism.py

Day-1 Step 6 proof: deterministic replay of the mutable entities projection
from the append-only events log.

Scope discipline (NON-NEGOTIABLE):
    - This is a PROOF test, not infrastructure. No replay engine, no
      app/events/replay.py module, no CLI, no projector registry, no
      generalized dispatcher. The substrate's replay-determinism
      invariant is established here in test-shape only — future work
      that builds infrastructure on top of it can rely on this proof
      without inheriting any framework shape from it.
    - The test imports ONLY the existing Step 4 emitter and Step 5
      projector. Event-row → Event reconstruction is inlined here.

What this test proves (Phase_0_Governance_and_Replayability.md Part B):
    1. Emit one entity.created event for the canonical A1 Garage Doors
       (Tommy Mello operator context; GARAGE_DOOR vertical) via the
       Step 4 emitter.
    2. Project it through the Step 5 projector into entities.
    3. Snapshot the entities table with explicit column order, a
       deterministic primary-key sort, and stable JSON serialization;
       SHA-256 the result. This is the "expected projection state".
    4. Clear the mutable entities projection (DELETE FROM entities).
       The append-only events table is NEVER cleared as part of
       rebuild — replay's source-of-truth invariant.
    5. Re-read events ORDER BY sequence_no ASC, filter to entity.created,
       reconstruct Event objects from the row tuples (UUIDs, timestamps,
       and JSONB payload recovered, not regenerated), and re-project.
    6. Recompute the snapshot SHA-256. Assert byte-equal to the original.

Replay-determinism invariants exercised:
    - Emitter-side UUIDs and timestamps are recovered from the event
      row, not regenerated at rebuild time (Mistakes #1, #2 prevention).
    - Payload JSONB round-trips through Pydantic deterministically
      (Mistake #7 prevention).
    - Projector is a pure function of the event tuple (Step 5 contract),
      so the rebuilt projection row is byte-identical to the original.

Forbidden in this file:
    - No replay engine. No replay module. No CLI. No registry. No
      dispatcher. No production replay APIs. No scoring/indicator/
      reporting code. No event types beyond entity.created.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.db import connection as db
from app.entities.projectors import project_entity_created
from app.events.emitter import emit_entity_created, emit_evidence_raw_ingested
from app.events.models import (
    EntityCreatedPayload,
    Event,
    EvidenceRawIngestedPayload,
)


# ---------------------------------------------------------------------------
# Fixtures (same shape as test_events_emitter.py / test_entities_projector.py)
# ---------------------------------------------------------------------------


def _resolved_dsn() -> str:
    return os.environ.get("TRUSIGNAL_TEST_DATABASE_URL") or db.get_dsn()


@pytest.fixture(scope="session", autouse=True)
def bootstrap_substrate_db() -> None:
    """Migrations applied + triggers verified once per test session."""
    db.bootstrap(dsn=_resolved_dsn())


@pytest.fixture()
def conn() -> psycopg.Connection:
    """
    Rollback-isolated connection. The whole replay proof runs inside one
    transaction: emit → project → snapshot → DELETE entities → replay →
    re-snapshot → rollback. Nothing persists beyond the test.
    """
    c = psycopg.connect(_resolved_dsn())
    try:
        yield c
    finally:
        try:
            c.rollback()
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Deterministic entities snapshot — column order, key sort, stable JSON
# ---------------------------------------------------------------------------

_ENTITIES_COLUMNS: tuple[str, ...] = (
    "entity_id",
    "name",
    "vertical",
    "created_at_for_projection",
    "created_event_id",
    "projected_at",
)


def _snapshot_entities_hash(conn: psycopg.Connection) -> str:
    """
    Read the entities table with a deterministic column list and primary-key
    sort, serialize via json.dumps(sort_keys=True, default=str), and hash
    with SHA-256. Two snapshots of byte-identical projection state produce
    byte-identical hashes.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id, name, vertical, created_at_for_projection, "
            "created_event_id, projected_at "
            "FROM entities "
            "ORDER BY entity_id"
        )
        rows = cur.fetchall()
    rows_as_dicts = [dict(zip(_ENTITIES_COLUMNS, row)) for row in rows]
    serialized = json.dumps(rows_as_dicts, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Replay path — inlined; not a reusable engine
# ---------------------------------------------------------------------------


def _replay_entity_created_events(conn: psycopg.Connection) -> int:
    """
    Re-read entity.created rows from the append-only events table in
    sequence_no ASC order, reconstruct Event objects, and re-project each
    through the Step 5 projector. Returns the count projected.

    All UUIDs and timestamps come from the row; nothing is regenerated.
    The payload JSONB is parsed back into EntityCreatedPayload by Pydantic.

    This helper is intentionally inlined in the test module. It is NOT a
    replay framework, NOT exported from app.events, and NOT reusable
    infrastructure. Future replay work will be authorized separately.

    WARNING — manual replay-filter maintenance contract:
        The SQL filter `WHERE event_type = 'entity.created'` below is the
        ONLY mechanism that keeps this helper correct as new event types
        are added to the log. When a future day adds another event type
        that MUTATES THE ENTITIES PROJECTION (e.g. entity.attribute_set,
        entity.domain_registered), that event type MUST be added to this
        filter AND the helper extended to dispatch to its projector.
        Otherwise the replay-determinism tests will silently pass — the
        snapshot hash before/after the wipe-and-replay cycle compares only
        the events the helper *did* re-apply — while production replay is
        actually incomplete. There is intentionally NO framework /
        registry / dispatcher enforcing this; the contract is held by
        the test author at the point of adding the new event type.

        As of Step 8, only `entity.created` mutates `entities`. The
        `evidence.raw_ingested` event type is intentionally NOT in this
        filter — it has no projector yet (deferred to Step 9+), and even
        when it does, it will not write to `entities`.
    """
    with conn.cursor() as cur:
        cur.execute(
            # WARNING: when a new entity-affecting event type lands,
            # extend this WHERE clause (e.g. `event_type IN (...)`) and
            # add the corresponding projector dispatch below. See the
            # helper docstring for the full maintenance contract.
            "SELECT event_id, event_type, aggregate_type, aggregate_id, "
            "payload, schema_version, occurred_at, recorded_at, "
            "actor_type, actor_id, causation_id, correlation_id "
            "FROM events "
            "WHERE event_type = 'entity.created' "
            "ORDER BY sequence_no ASC"
        )
        rows = cur.fetchall()

    count = 0
    for row in rows:
        payload = EntityCreatedPayload(**row[4])
        event = Event(
            event_id=row[0],
            event_type=row[1],
            aggregate_type=row[2],
            aggregate_id=row[3],
            payload=payload,
            schema_version=row[5],
            occurred_at=row[6],
            recorded_at=row[7],
            actor_type=row[8],
            actor_id=row[9],
            causation_id=row[10],
            correlation_id=row[11],
        )
        project_entity_created(conn, event)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Canonical A1 Garage Doors / Tommy Mello / GARAGE_DOOR event
# ---------------------------------------------------------------------------


def _emit_a1_event(conn: psycopg.Connection) -> Event:
    """Emit the canonical Day-1 first-projection event."""
    payload = EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=datetime.now(timezone.utc),
    )
    return emit_entity_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )


# ===========================================================================
# The Step 6 proof
# ===========================================================================


def test_replay_rebuilds_entities_projection_deterministically(
    conn: psycopg.Connection,
) -> None:
    """
    Step 6 proof: clearing the entities projection and rebuilding it from
    the append-only events log (ordered by sequence_no ASC) produces a
    byte-identical projection state. Hashes match exactly.
    """
    # 1. Emit one entity.created event for A1 Garage Doors.
    event = _emit_a1_event(conn)

    # 2. Project it via the Step 5 projector.
    project_entity_created(conn, event)

    # 3. Snapshot + hash. This is the "expected" state.
    hash_before = _snapshot_entities_hash(conn)

    # 4a. Capture the events count before the projection-clear so we can
    #     prove the event log is untouched by replay.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        events_count_before = cur.fetchone()[0]
    assert events_count_before >= 1

    # 4b. Clear ONLY the mutable entities projection. The events table is
    #     left untouched — replay's source-of-truth invariant.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM entities")
        cur.execute("SELECT count(*) FROM entities")
        assert cur.fetchone()[0] == 0

    # 5. Rebuild from events (ORDER BY sequence_no ASC; entity.created only).
    rebuilt_count = _replay_entity_created_events(conn)
    assert rebuilt_count == events_count_before

    # 5a. The events table is unchanged after replay (append-only,
    #     never read-destructively).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        events_count_after = cur.fetchone()[0]
    assert events_count_after == events_count_before

    # 6. Re-hash and assert byte-equal.
    hash_after = _snapshot_entities_hash(conn)
    assert hash_after == hash_before, (
        "Replay determinism violated: rebuilt entities snapshot does not "
        "hash to the same value as the original projection.\n"
        f"  before: {hash_before}\n"
        f"  after:  {hash_after}"
    )


# ===========================================================================
# Step 8 extension — mixed entity.created + evidence.raw_ingested log
# ===========================================================================


_SYNTHETIC_EVIDENCE_CONTENT: bytes = (
    b"<html><body>A1 Garage Doors - synthetic Step-8 replay fixture</body></html>"
)


def _synthetic_evidence_payload(
    *, subject_entity_id: uuid.UUID
) -> EvidenceRawIngestedPayload:
    """
    Build a deterministic synthetic evidence payload linked to the given
    entity. No external storage is touched; storage_uri is a placeholder.
    """
    return EvidenceRawIngestedPayload(
        evidence_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        source_uri="https://example.invalid/a1-garage-doors",
        source_type="website_fetch",
        content_hash=hashlib.sha256(_SYNTHETIC_EVIDENCE_CONTENT).hexdigest(),
        storage_uri="s3://substrate-evidence/synthetic/a1-garage-doors.html",
        observed_at_for_projection=datetime.now(timezone.utc),
        metadata={"http_status": "200", "vertical": "GARAGE_DOOR"},
    )


def test_replay_determinism_robust_to_mixed_event_types(
    conn: psycopg.Connection,
) -> None:
    """
    Step 8 invariant: adding `evidence.raw_ingested` events to the
    append-only event log MUST NOT break deterministic replay of the
    existing `entities` projection. The replay helper filters by
    event_type, so evidence rows are read-and-skipped; the entities
    snapshot must rebuild byte-identical across the wipe-and-replay
    cycle, and both event-type counts must remain unchanged (the event
    log is append-only and is never modified by replay).
    """
    # 1. Emit canonical A1 Garage Doors entity.created, then project.
    entity_event = _emit_a1_event(conn)
    project_entity_created(conn, entity_event)

    # 2. Emit one evidence.raw_ingested linked to A1 Garage Doors. There
    #    is intentionally no evidence projector — the projection table
    #    does not exist yet (deferred to Step 9+).
    evidence_payload = _synthetic_evidence_payload(
        subject_entity_id=entity_event.payload.entity_id,
    )
    emit_evidence_raw_ingested(
        conn,
        payload=evidence_payload,
        actor_type="analyst",
        actor_id="andrew",
    )

    # 3. Snapshot the entities table + capture event-type counts.
    hash_before = _snapshot_entities_hash(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        entity_events_before = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        evidence_events_before = cur.fetchone()[0]
    assert entity_events_before >= 1
    assert evidence_events_before >= 1

    # 4. Clear ONLY the mutable entities projection. The events table
    #    (now containing both event types) must remain untouched.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM entities")
        cur.execute("SELECT count(*) FROM entities")
        assert cur.fetchone()[0] == 0

    # 5. Rebuild via the existing replay helper, which filters
    #    event_type = 'entity.created' — evidence rows are read and
    #    skipped by SQL predicate, not by Python dispatch.
    rebuilt_count = _replay_entity_created_events(conn)
    assert rebuilt_count == entity_events_before

    # 6. Both event-type counts are unchanged after replay.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        assert cur.fetchone()[0] == entity_events_before
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        assert cur.fetchone()[0] == evidence_events_before

    # 7. Hash matches — adding evidence events did not perturb entity replay.
    hash_after = _snapshot_entities_hash(conn)
    assert hash_after == hash_before, (
        "Step 8 invariant violated: introducing evidence.raw_ingested "
        "events into the append-only log broke entity-projection replay "
        "determinism.\n"
        f"  before: {hash_before}\n"
        f"  after:  {hash_after}"
    )
