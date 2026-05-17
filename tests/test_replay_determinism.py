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
from app.events.emitter import (
    emit_entity_created,
    emit_evidence_derived_created,
    emit_evidence_raw_ingested,
)
from app.events.models import (
    EntityCreatedPayload,
    Event,
    EvidenceDerivedCreatedPayload,
    EvidenceRawIngestedPayload,
)
from app.evidence.projectors import (
    project_evidence_derived_created,
    project_evidence_raw_ingested,
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


# ===========================================================================
# Step 9 extensions — evidence_raw projection replay determinism
# ===========================================================================


_EVIDENCE_RAW_COLUMNS: tuple[str, ...] = (
    "evidence_id",
    "subject_entity_id",
    "source_uri",
    "source_type",
    "content_hash",
    "storage_uri",
    "observed_at_for_projection",
    "created_event_id",
    "projected_at",
)


def _snapshot_evidence_raw_hash(conn: psycopg.Connection) -> str:
    """
    Read evidence_raw with a deterministic column list and primary-key
    sort, serialize via json.dumps(sort_keys=True, default=str), and
    SHA-256. Mirrors _snapshot_entities_hash for the second projection.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence_id, subject_entity_id, source_uri, source_type, "
            "content_hash, storage_uri, observed_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_raw "
            "ORDER BY evidence_id"
        )
        rows = cur.fetchall()
    rows_as_dicts = [dict(zip(_EVIDENCE_RAW_COLUMNS, row)) for row in rows]
    serialized = json.dumps(rows_as_dicts, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _emit_a1_evidence_event(
    conn: psycopg.Connection,
    *,
    subject_entity_id: uuid.UUID | None = None,
) -> Event:
    """
    Emit a synthetic A1 Garage Doors evidence.raw_ingested event for the
    Step-9 replay-determinism tests. Mirrors the canonical fixture in
    tests/test_evidence_projector.py but is duplicated here intentionally
    to keep test modules self-contained (no cross-test-module helpers).
    """
    payload = EvidenceRawIngestedPayload(
        evidence_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        source_uri="https://example.invalid/a1-garage-doors",
        source_type="website_fetch",
        content_hash=hashlib.sha256(_SYNTHETIC_EVIDENCE_CONTENT).hexdigest(),
        storage_uri="s3://substrate-evidence/synthetic/a1-garage-doors.html",
        observed_at_for_projection=datetime.now(timezone.utc),
        metadata={"http_status": "200", "vertical": "GARAGE_DOOR"},
    )
    return emit_evidence_raw_ingested(
        conn,
        payload=payload,
        actor_type="analyst",
        actor_id="andrew",
    )


def _replay_evidence_raw_ingested_events(conn: psycopg.Connection) -> int:
    """
    Re-read evidence.raw_ingested rows from the append-only events table
    in sequence_no ASC order, reconstruct Event objects, and re-project
    each through the Step 9 projector. Returns the count projected.

    All UUIDs and timestamps come from the row; nothing is regenerated.
    The payload JSONB is parsed back into EvidenceRawIngestedPayload by
    Pydantic.

    This helper is intentionally inlined in the test module. It is NOT a
    replay framework, NOT exported from app.evidence, and NOT reusable
    infrastructure. Future replay work will be authorized separately.

    WARNING — manual replay-filter maintenance contract:
        The SQL filter `WHERE event_type = 'evidence.raw_ingested'` below
        is the ONLY mechanism that keeps this helper correct as new event
        types are added to the log. When a future day adds another event
        type that MUTATES THE evidence_raw PROJECTION (e.g. a hypothetical
        evidence.attribute_set), that event type MUST be added to this
        filter AND the helper extended. Otherwise replay-determinism tests
        will silently pass — the snapshot hash before/after the
        wipe-and-replay cycle compares only the events the helper *did*
        re-apply — while production replay is actually incomplete. There
        is intentionally NO framework / registry / dispatcher enforcing
        this; the contract is held by the test author at the point of
        adding the new event type. The identical contract applies to
        `_replay_entity_created_events` for the entities projection.

        As of Step 9, only `evidence.raw_ingested` mutates `evidence_raw`.
    """
    with conn.cursor() as cur:
        cur.execute(
            # WARNING: when a new evidence-affecting event type lands,
            # extend this WHERE clause (e.g. `event_type IN (...)`) and
            # add the corresponding projector dispatch below. See the
            # helper docstring for the full maintenance contract.
            "SELECT event_id, event_type, aggregate_type, aggregate_id, "
            "payload, schema_version, occurred_at, recorded_at, "
            "actor_type, actor_id, causation_id, correlation_id "
            "FROM events "
            "WHERE event_type = 'evidence.raw_ingested' "
            "ORDER BY sequence_no ASC"
        )
        rows = cur.fetchall()

    count = 0
    for row in rows:
        payload = EvidenceRawIngestedPayload(**row[4])
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
        project_evidence_raw_ingested(conn, event)
        count += 1
    return count


def test_replay_rebuilds_evidence_raw_projection_deterministically(
    conn: psycopg.Connection,
) -> None:
    """
    Step 9 proof — mirror of the Step 6 entity-projection replay test
    applied to the new evidence_raw projection. Clearing evidence_raw and
    rebuilding from the append-only events log produces a byte-identical
    projection state.

    No entity is created in this test — subject_entity_id is a soft
    pointer at the projection layer (no FK to entities), so the evidence
    row stands alone.
    """
    # 1. Emit one evidence.raw_ingested with a fresh synthetic
    #    subject_entity_id UUID (no entity row needed at this layer).
    placeholder_entity_id = uuid.uuid4()
    evidence_event = _emit_a1_evidence_event(
        conn, subject_entity_id=placeholder_entity_id,
    )

    # 2. Project via the Step 9 projector.
    project_evidence_raw_ingested(conn, evidence_event)

    # 3. Snapshot + hash — the "expected" state.
    hash_before = _snapshot_evidence_raw_hash(conn)

    # 4a. Capture the events count so we can prove the event log is
    #     untouched by replay.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        events_count_before = cur.fetchone()[0]
    assert events_count_before >= 1

    # 4b. Clear ONLY the mutable evidence_raw projection. The events
    #     table is left untouched — replay's source-of-truth invariant.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence_raw")
        cur.execute("SELECT count(*) FROM evidence_raw")
        assert cur.fetchone()[0] == 0

    # 5. Rebuild from events (ORDER BY sequence_no ASC;
    #    evidence.raw_ingested only).
    rebuilt_count = _replay_evidence_raw_ingested_events(conn)
    assert rebuilt_count == events_count_before

    # 5a. Event log is unchanged after replay.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        events_count_after = cur.fetchone()[0]
    assert events_count_after == events_count_before

    # 6. Re-hash and assert byte-equal.
    hash_after = _snapshot_evidence_raw_hash(conn)
    assert hash_after == hash_before, (
        "Step 9 invariant violated: rebuilt evidence_raw snapshot does "
        "not hash to the same value as the original projection.\n"
        f"  before: {hash_before}\n"
        f"  after:  {hash_after}"
    )


def test_replay_rebuilds_both_projections_after_combined_wipe(
    conn: psycopg.Connection,
) -> None:
    """
    Step 9 combined-projection invariant: with both entities AND
    evidence_raw populated from a mixed, interleaved event log, wiping
    BOTH projections and replaying via a SINGLE sequence_no-ordered pass
    with inline if/elif dispatch rebuilds both projections byte-identical.

    Replay-dispatch discipline:
        - Single SELECT across all event types, ordered by sequence_no.
        - Inline if/elif branching on event_type.
        - No registry. No dispatcher. No generalized engine. No helper
          extraction beyond what already exists in this test module.
        - When a future event type lands, add an `elif` branch here AND
          (if it mutates a projection) extend the relevant per-type
          replay helper. Both are manual contracts held by the test
          author at the point of adding the new event type.
    """
    # 1. Emit multiple interleaved events:
    #      entity #1 → evidence #1 → entity #2 → evidence #2
    entity_event_1 = _emit_a1_event(conn)
    project_entity_created(conn, entity_event_1)

    evidence_event_1 = _emit_a1_evidence_event(
        conn, subject_entity_id=entity_event_1.payload.entity_id,
    )
    project_evidence_raw_ingested(conn, evidence_event_1)

    entity_event_2 = _emit_a1_event(conn)
    project_entity_created(conn, entity_event_2)

    evidence_event_2 = _emit_a1_evidence_event(
        conn, subject_entity_id=entity_event_2.payload.entity_id,
    )
    project_evidence_raw_ingested(conn, evidence_event_2)

    # 2. Snapshot BOTH projections.
    entities_hash_before = _snapshot_entities_hash(conn)
    evidence_hash_before = _snapshot_evidence_raw_hash(conn)

    # 3. Capture both event-type counts.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        entity_count_before = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        evidence_count_before = cur.fetchone()[0]
    assert entity_count_before >= 2
    assert evidence_count_before >= 2

    # 4. Wipe BOTH projections. evidence_raw first (the "more downstream"
    #    projection); entities second. The events log is left untouched.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence_raw")
        cur.execute("DELETE FROM entities")
        cur.execute("SELECT count(*) FROM evidence_raw")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM entities")
        assert cur.fetchone()[0] == 0

    # 5. Single sequence_no-ordered pass with inline if/elif dispatch.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type, aggregate_type, aggregate_id, "
            "payload, schema_version, occurred_at, recorded_at, "
            "actor_type, actor_id, causation_id, correlation_id "
            "FROM events "
            "ORDER BY sequence_no ASC"
        )
        all_rows = cur.fetchall()

    entity_replayed = 0
    evidence_replayed = 0
    for row in all_rows:
        event_type = row[1]
        if event_type == "entity.created":
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
            entity_replayed += 1
        elif event_type == "evidence.raw_ingested":
            payload = EvidenceRawIngestedPayload(**row[4])
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
            project_evidence_raw_ingested(conn, event)
            evidence_replayed += 1
        # WARNING: when a new event type lands, add another `elif` branch
        # here. The replay-dispatch contract is held inline; there is
        # intentionally no registry / dispatcher to enforce completeness.

    assert entity_replayed == entity_count_before
    assert evidence_replayed == evidence_count_before

    # 6. Event-type counts unchanged after replay.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        assert cur.fetchone()[0] == entity_count_before
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        assert cur.fetchone()[0] == evidence_count_before

    # 7. Re-hash both projections; both must match originals byte-equal.
    entities_hash_after = _snapshot_entities_hash(conn)
    evidence_hash_after = _snapshot_evidence_raw_hash(conn)
    assert entities_hash_after == entities_hash_before, (
        "Step 9 combined-replay invariant violated: entities projection "
        "diverged after combined wipe + interleaved replay.\n"
        f"  before: {entities_hash_before}\n"
        f"  after:  {entities_hash_after}"
    )
    assert evidence_hash_after == evidence_hash_before, (
        "Step 9 combined-replay invariant violated: evidence_raw "
        "projection diverged after combined wipe + interleaved replay.\n"
        f"  before: {evidence_hash_before}\n"
        f"  after:  {evidence_hash_after}"
    )


# ===========================================================================
# Step 10 extensions — evidence_derived projection replay determinism
# ===========================================================================


_EVIDENCE_DERIVED_COLUMNS: tuple[str, ...] = (
    "derived_evidence_id",
    "subject_entity_id",
    "parent_evidence_ids",
    "derivation_type",
    "derivation_version",
    "output_payload",
    "derived_at_for_projection",
    "created_event_id",
    "projected_at",
)


def _snapshot_evidence_derived_hash(conn: psycopg.Connection) -> str:
    """
    Read evidence_derived with a deterministic column list and primary-key
    sort, serialize via json.dumps(sort_keys=True, default=str), and
    SHA-256. Mirrors _snapshot_entities_hash / _snapshot_evidence_raw_hash
    for the third projection.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT derived_evidence_id, subject_entity_id, "
            "parent_evidence_ids, derivation_type, derivation_version, "
            "output_payload, derived_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_derived "
            "ORDER BY derived_evidence_id"
        )
        rows = cur.fetchall()
    rows_as_dicts = [
        dict(zip(_EVIDENCE_DERIVED_COLUMNS, row)) for row in rows
    ]
    serialized = json.dumps(rows_as_dicts, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _emit_a1_derived_event(
    conn: psycopg.Connection,
    *,
    subject_entity_id: uuid.UUID | None = None,
    parent_evidence_ids: list[uuid.UUID] | None = None,
    derivation_type: str = "summary_extraction",
    derivation_version: str = "summarizer-v1.0.0",
    output_payload: dict | None = None,
) -> Event:
    """
    Emit a synthetic A1 Garage Doors evidence.derived_created event.
    Duplicates the canonical fixture in tests/test_evidence_derived_*.py
    intentionally to keep this test module self-contained.
    """
    if parent_evidence_ids is None:
        parent_evidence_ids = [uuid.uuid4(), uuid.uuid4()]
    if output_payload is None:
        output_payload = {
            "summary": "A1 Garage Doors operator content (synthetic)",
            "confidence": 0.85,
        }
    payload = EvidenceDerivedCreatedPayload(
        derived_evidence_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        parent_evidence_ids=parent_evidence_ids,
        derivation_type=derivation_type,
        derivation_version=derivation_version,
        output_payload=output_payload,
        derived_at_for_projection=datetime.now(timezone.utc),
    )
    return emit_evidence_derived_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )


def _replay_evidence_derived_created_events(conn: psycopg.Connection) -> int:
    """
    Re-read evidence.derived_created rows from the append-only events
    table in sequence_no ASC order, reconstruct Event objects, and
    re-project each through the Step 10 projector. Returns the count
    projected.

    All UUIDs and timestamps come from the row; nothing is regenerated.
    The payload JSONB is parsed back into EvidenceDerivedCreatedPayload
    by Pydantic. The transformation logic that originally produced
    output_payload is NOT re-run; the output_payload is recovered
    verbatim from the stored event.

    WARNING — manual replay-filter maintenance contract:
        The SQL filter `WHERE event_type = 'evidence.derived_created'`
        below is the ONLY mechanism that keeps this helper correct as
        new event types are added to the log. When a future day adds
        another event type that MUTATES THE evidence_derived
        PROJECTION (e.g. an `evidence.derived_revised` or similar),
        that event type MUST be added to this filter AND the helper
        extended. Otherwise replay-determinism tests will silently
        pass — the snapshot hash before/after the wipe-and-replay
        cycle compares only the events the helper *did* re-apply —
        while production replay is actually incomplete. The identical
        contract applies to the two earlier per-type helpers and to
        the combined inline-dispatch test below.

        As of Step 10, only `evidence.derived_created` mutates
        `evidence_derived`.
    """
    with conn.cursor() as cur:
        cur.execute(
            # WARNING: when a new evidence_derived-affecting event type
            # lands, extend this WHERE clause (e.g. `event_type IN (...)`)
            # and add the corresponding projector dispatch below. See the
            # helper docstring for the full maintenance contract.
            "SELECT event_id, event_type, aggregate_type, aggregate_id, "
            "payload, schema_version, occurred_at, recorded_at, "
            "actor_type, actor_id, causation_id, correlation_id "
            "FROM events "
            "WHERE event_type = 'evidence.derived_created' "
            "ORDER BY sequence_no ASC"
        )
        rows = cur.fetchall()

    count = 0
    for row in rows:
        payload = EvidenceDerivedCreatedPayload(**row[4])
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
        project_evidence_derived_created(conn, event)
        count += 1
    return count


def test_replay_rebuilds_evidence_derived_projection_deterministically(
    conn: psycopg.Connection,
) -> None:
    """
    Step 10 proof — mirror of the Step 6/9 replay tests applied to the
    new evidence_derived projection. Clearing evidence_derived and
    rebuilding from the append-only events log produces a byte-identical
    projection state.

    The replay path does NOT re-run the transformation logic that
    produced output_payload — it recovers output_payload verbatim from
    the stored event and writes it back to the projection. This is the
    core invariant for transformation-evolution auditability.
    """
    # 1. Emit one evidence.derived_created with a fixed-order
    #    parent_evidence_ids list to exercise the order-preservation
    #    contract under replay.
    parents = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    derived_event = _emit_a1_derived_event(
        conn,
        parent_evidence_ids=parents,
        output_payload={"summary": "replay-determinism fixture", "score": 0.5},
    )

    # 2. Project via the Step 10 projector.
    project_evidence_derived_created(conn, derived_event)

    # 3. Snapshot + hash — the "expected" state.
    hash_before = _snapshot_evidence_derived_hash(conn)

    # 4a. Capture event count so we can prove the event log is untouched.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.derived_created'"
        )
        events_count_before = cur.fetchone()[0]
    assert events_count_before >= 1

    # 4b. Clear ONLY the mutable evidence_derived projection.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence_derived")
        cur.execute("SELECT count(*) FROM evidence_derived")
        assert cur.fetchone()[0] == 0

    # 5. Rebuild from events.
    rebuilt_count = _replay_evidence_derived_created_events(conn)
    assert rebuilt_count == events_count_before

    # 5a. Event log unchanged.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.derived_created'"
        )
        events_count_after = cur.fetchone()[0]
    assert events_count_after == events_count_before

    # 6. Re-hash and assert byte-equal.
    hash_after = _snapshot_evidence_derived_hash(conn)
    assert hash_after == hash_before, (
        "Step 10 invariant violated: rebuilt evidence_derived snapshot "
        "does not hash to the same value as the original projection.\n"
        f"  before: {hash_before}\n"
        f"  after:  {hash_after}"
    )

    # 7. Explicit parent_evidence_ids order check under replay (belt and
    #    suspenders on top of the hash equality).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT parent_evidence_ids FROM evidence_derived "
            "WHERE derived_evidence_id = %s",
            (derived_event.payload.derived_evidence_id,),
        )
        replayed_parents = cur.fetchone()[0]
    assert replayed_parents == parents, (
        "parent_evidence_ids order was NOT preserved under replay.\n"
        f"  emitted:  {parents}\n"
        f"  replayed: {replayed_parents}"
    )


def test_replay_rebuilds_all_three_projections_after_combined_wipe(
    conn: psycopg.Connection,
) -> None:
    """
    Step 10 combined-projection invariant: with all three projection
    tables populated from a mixed, interleaved event log, wiping all
    three projections and replaying via a SINGLE sequence_no-ordered
    pass with inline if/elif/elif dispatch rebuilds all three
    projections byte-identical.

    Replay-dispatch discipline:
        - Single SELECT across all event types, ordered by sequence_no.
        - Inline if/elif/elif branching on event_type.
        - No registry. No dispatcher. No generalized engine. No helper
          extraction beyond what already exists in this test module.
        - When a future event type lands, add an `elif` branch here AND
          (if it mutates a projection) extend the relevant per-type
          replay helper. Both are manual contracts held by the test
          author at the point of adding the new event type.
    """
    # 1. Emit multiple interleaved events across all three types:
    #      entity #1 → raw #1 → derived #1 → entity #2 → raw #2 → derived #2
    entity_event_1 = _emit_a1_event(conn)
    project_entity_created(conn, entity_event_1)

    raw_event_1 = _emit_a1_evidence_event(
        conn, subject_entity_id=entity_event_1.payload.entity_id,
    )
    project_evidence_raw_ingested(conn, raw_event_1)

    derived_event_1 = _emit_a1_derived_event(
        conn,
        subject_entity_id=entity_event_1.payload.entity_id,
        parent_evidence_ids=[raw_event_1.payload.evidence_id],
    )
    project_evidence_derived_created(conn, derived_event_1)

    entity_event_2 = _emit_a1_event(conn)
    project_entity_created(conn, entity_event_2)

    raw_event_2 = _emit_a1_evidence_event(
        conn, subject_entity_id=entity_event_2.payload.entity_id,
    )
    project_evidence_raw_ingested(conn, raw_event_2)

    derived_event_2 = _emit_a1_derived_event(
        conn,
        subject_entity_id=entity_event_2.payload.entity_id,
        parent_evidence_ids=[
            raw_event_1.payload.evidence_id,
            raw_event_2.payload.evidence_id,
        ],
    )
    project_evidence_derived_created(conn, derived_event_2)

    # 2. Snapshot ALL THREE projections.
    entities_hash_before = _snapshot_entities_hash(conn)
    evidence_raw_hash_before = _snapshot_evidence_raw_hash(conn)
    evidence_derived_hash_before = _snapshot_evidence_derived_hash(conn)

    # 3. Capture all three event-type counts.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        entity_count_before = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        raw_count_before = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.derived_created'"
        )
        derived_count_before = cur.fetchone()[0]
    assert entity_count_before >= 2
    assert raw_count_before >= 2
    assert derived_count_before >= 2

    # 4. Wipe ALL THREE projections. Most-downstream first
    #    (evidence_derived → evidence_raw → entities). Events untouched.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence_derived")
        cur.execute("DELETE FROM evidence_raw")
        cur.execute("DELETE FROM entities")
        cur.execute("SELECT count(*) FROM evidence_derived")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM evidence_raw")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM entities")
        assert cur.fetchone()[0] == 0

    # 5. Single sequence_no-ordered pass with inline if/elif/elif dispatch.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type, aggregate_type, aggregate_id, "
            "payload, schema_version, occurred_at, recorded_at, "
            "actor_type, actor_id, causation_id, correlation_id "
            "FROM events "
            "ORDER BY sequence_no ASC"
        )
        all_rows = cur.fetchall()

    entity_replayed = 0
    raw_replayed = 0
    derived_replayed = 0
    for row in all_rows:
        event_type = row[1]
        if event_type == "entity.created":
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
            entity_replayed += 1
        elif event_type == "evidence.raw_ingested":
            payload = EvidenceRawIngestedPayload(**row[4])
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
            project_evidence_raw_ingested(conn, event)
            raw_replayed += 1
        elif event_type == "evidence.derived_created":
            payload = EvidenceDerivedCreatedPayload(**row[4])
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
            project_evidence_derived_created(conn, event)
            derived_replayed += 1
        # WARNING: when a new event type lands, add another `elif` branch
        # here. The replay-dispatch contract is held inline; there is
        # intentionally no registry / dispatcher to enforce completeness.

    assert entity_replayed == entity_count_before
    assert raw_replayed == raw_count_before
    assert derived_replayed == derived_count_before

    # 6. All three event-type counts unchanged after replay.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_type = 'entity.created'"
        )
        assert cur.fetchone()[0] == entity_count_before
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.raw_ingested'"
        )
        assert cur.fetchone()[0] == raw_count_before
        cur.execute(
            "SELECT count(*) FROM events "
            "WHERE event_type = 'evidence.derived_created'"
        )
        assert cur.fetchone()[0] == derived_count_before

    # 7. Re-hash all three projections; all must match originals byte-equal.
    entities_hash_after = _snapshot_entities_hash(conn)
    evidence_raw_hash_after = _snapshot_evidence_raw_hash(conn)
    evidence_derived_hash_after = _snapshot_evidence_derived_hash(conn)
    assert entities_hash_after == entities_hash_before, (
        "Step 10 three-way replay invariant violated: entities projection "
        "diverged after combined wipe + interleaved replay.\n"
        f"  before: {entities_hash_before}\n"
        f"  after:  {entities_hash_after}"
    )
    assert evidence_raw_hash_after == evidence_raw_hash_before, (
        "Step 10 three-way replay invariant violated: evidence_raw "
        "projection diverged after combined wipe + interleaved replay.\n"
        f"  before: {evidence_raw_hash_before}\n"
        f"  after:  {evidence_raw_hash_after}"
    )
    assert evidence_derived_hash_after == evidence_derived_hash_before, (
        "Step 10 three-way replay invariant violated: evidence_derived "
        "projection diverged after combined wipe + interleaved replay.\n"
        f"  before: {evidence_derived_hash_before}\n"
        f"  after:  {evidence_derived_hash_after}"
    )
