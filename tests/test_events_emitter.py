"""
tests/test_events_emitter.py

Day-1 Step 4 verification. Two layers:

    1. Pure model validation (no DB):
       - EntityCreatedPayload accepts a valid construction.
       - extra="forbid" rejects unknown fields (Mistake #8 prevention).
       - min_length=1 rejects empty `name` and empty `vertical`.
       - Event envelope is frozen (immutable).

    2. Single-transaction emit against the live substrate (rollback-isolated):
       - emit_entity_created lands one row in events with the expected shape.
       - Payload round-trips through JSONB.
       - Each emit generates a fresh event_id.
       - aggregate_id equals payload.entity_id (entity.* convention).
       - The canonical first emit target: A1 Garage Doors (Tommy Mello
         operator context, GARAGE_DOOR vertical) per the brief's clarification.

Scope discipline:
    - Tests interact ONLY with the events table and the emitter. No
      projector logic, no entities projection table, no replay reads.
    - Rollback-based isolation: each emit test opens its own connection,
      emits inside it, verifies via SELECT, then rolls back. Successful
      INSERTs never persist beyond test runtime — and since TRUNCATE is
      forbidden by the substrate triggers, rollback is the only correct
      cleanup mechanism for events.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from pydantic import ValidationError

from app.db import connection as db
from app.events.emitter import (
    ENTITY_CREATED_SCHEMA_VERSION,
    emit_entity_created,
)
from app.events.models import (
    AGGREGATE_TYPE_ENTITY,
    EntityCreatedPayload,
    Event,
)


# ---------------------------------------------------------------------------
# Fixtures (DB-layer; pure-model tests do not consume `conn`)
# ---------------------------------------------------------------------------


def _resolved_dsn() -> str:
    return os.environ.get("TRUSIGNAL_TEST_DATABASE_URL") or db.get_dsn()


@pytest.fixture(scope="session", autouse=True)
def bootstrap_substrate_db() -> None:
    """Migrations applied + triggers verified once per test session."""
    db.bootstrap(dsn=_resolved_dsn())


@pytest.fixture()
def conn() -> psycopg.Connection:
    """Rollback-isolated connection: emits never persist beyond the test."""
    c = psycopg.connect(_resolved_dsn())
    try:
        yield c
    finally:
        try:
            c.rollback()
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Canonical first emit target — A1 Garage Doors (Tommy Mello operator context)
# ---------------------------------------------------------------------------


def _a1_garage_payload() -> EntityCreatedPayload:
    """
    Build a fresh EntityCreatedPayload for A1 Garage Doors — the Day-1
    canonical archetype per CURRENT_STATE_BRIEF.md and the Phase-0
    flagship case (Tommy Mello operator context; GARAGE_DOOR vertical).
    Each call generates a new entity_id so emit tests don't collide.
    """
    return EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=datetime.now(timezone.utc),
    )


# ===========================================================================
# Layer 1 — Pure model validation (no DB)
# ===========================================================================


def test_entity_created_payload_accepts_valid_construction() -> None:
    payload = _a1_garage_payload()
    assert payload.name == "A1 Garage Doors"
    assert payload.vertical == "GARAGE_DOOR"
    assert isinstance(payload.entity_id, uuid.UUID)
    assert payload.created_at_for_projection.tzinfo is not None


def test_entity_created_payload_rejects_unknown_fields() -> None:
    """extra='forbid' guards against silent payload drift (Mistake #8)."""
    with pytest.raises(ValidationError):
        EntityCreatedPayload(
            entity_id=uuid.uuid4(),
            name="A1 Garage Doors",
            vertical="GARAGE_DOOR",
            created_at_for_projection=datetime.now(timezone.utc),
            unexpected_field="this should fail",  # type: ignore[call-arg]
        )


def test_entity_created_payload_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        EntityCreatedPayload(
            entity_id=uuid.uuid4(),
            name="",
            vertical="GARAGE_DOOR",
            created_at_for_projection=datetime.now(timezone.utc),
        )


def test_entity_created_payload_rejects_empty_vertical() -> None:
    with pytest.raises(ValidationError):
        EntityCreatedPayload(
            entity_id=uuid.uuid4(),
            name="A1 Garage Doors",
            vertical="",
            created_at_for_projection=datetime.now(timezone.utc),
        )


def test_event_envelope_is_frozen() -> None:
    """
    frozen=True makes Event values immutable in Python. Append-only at the
    storage layer is enforced by triggers (Step 2); append-only at the
    Python layer is enforced here.
    """
    payload = _a1_garage_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="entity.created",
        aggregate_type=AGGREGATE_TYPE_ENTITY,
        aggregate_id=payload.entity_id,
        payload=payload,
        schema_version=ENTITY_CREATED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    with pytest.raises(ValidationError):
        # Pydantic v2 raises ValidationError on frozen-instance mutation
        event.actor_id = "someone-else"  # type: ignore[misc]


# ===========================================================================
# Layer 2 — Single-transaction emit (rollback-isolated)
# ===========================================================================


def test_emit_entity_created_inserts_event_row(conn: psycopg.Connection) -> None:
    """
    Canonical first emit: A1 Garage Doors. After emit, the row must be
    readable inside the same transaction with the expected shape.
    """
    payload = _a1_garage_payload()
    event = emit_entity_created(
        conn,
        payload=payload,
        actor_type="analyst",
        actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type, aggregate_type, aggregate_id, "
            "schema_version, actor_type, actor_id "
            "FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == event.event_id
    assert row[1] == "entity.created"
    assert row[2] == AGGREGATE_TYPE_ENTITY
    assert row[3] == payload.entity_id
    assert row[4] == ENTITY_CREATED_SCHEMA_VERSION
    assert row[5] == "analyst"
    assert row[6] == "andrew"


def test_emit_payload_round_trips_via_jsonb(conn: psycopg.Connection) -> None:
    """
    The four payload fields (entity_id, name, vertical,
    created_at_for_projection) must survive the JSON serialize → JSONB
    store → JSON parse round-trip.
    """
    payload = _a1_garage_payload()
    event = emit_entity_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["name"] == "A1 Garage Doors"
    assert stored["vertical"] == "GARAGE_DOOR"
    assert stored["entity_id"] == str(payload.entity_id)
    # ISO-8601 timestamp survives intact
    assert isinstance(stored["created_at_for_projection"], str)
    assert "T" in stored["created_at_for_projection"]


def test_emit_generates_distinct_event_ids(conn: psycopg.Connection) -> None:
    """Each emit gets a fresh UUID — no accidental replay from emitter side."""
    e1 = emit_entity_created(
        conn,
        payload=_a1_garage_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    e2 = emit_entity_created(
        conn,
        payload=_a1_garage_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert e1.event_id != e2.event_id


def test_emit_aggregate_id_equals_entity_id(conn: psycopg.Connection) -> None:
    """
    entity.* convention: aggregate_id IS the entity's entity_id. The
    emitter must wire this automatically; the caller does not pass
    aggregate_id explicitly.
    """
    payload = _a1_garage_payload()
    event = emit_entity_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )
    assert event.aggregate_id == payload.entity_id


def test_emit_timestamps_are_utc(conn: psycopg.Connection) -> None:
    """
    Both occurred_at and recorded_at must be timezone-aware (UTC) so that
    replay-time comparisons are unambiguous.
    """
    event = emit_entity_created(
        conn,
        payload=_a1_garage_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.occurred_at.tzinfo is not None
    assert event.recorded_at.tzinfo is not None
