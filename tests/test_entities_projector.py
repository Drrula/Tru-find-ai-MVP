"""
tests/test_entities_projector.py

Day-1 Step 5 verification. Four layers:

    1. Happy-path projection of the canonical A1 Garage Doors entity.created
       event (Tommy Mello operator context; GARAGE_DOOR vertical) into the
       entities table. All six columns match the values derived from the
       event tuple.

    2. Idempotence: projecting the same event twice produces one row
       (ON CONFLICT (entity_id) DO NOTHING).

    3. Determinism: re-projecting the same event leaves every column
       byte-equal to the first projection. Combined with (1), this proves
       the projection row is a pure function of the event tuple.

    4. Static source-grep guard: projectors.py does not import or call
       any non-determinism source (datetime.now, uuid.uuid4, random,
       os.environ, open(, requests, httpx). The projector is purely a
       function of its event input.

Scope discipline:
    - No replay-engine import, no replay test.
    - No additional projection tables.
    - Tests interact with the entities table and the projector ONLY.
    - Rollback-isolated per-test connection; emitted events and projected
      rows never persist beyond the test.

Environment:
    - DSN comes from TRUSIGNAL_TEST_DATABASE_URL if set, else falls back
      to TRUSIGNAL_DATABASE_URL (resolved by app.db.connection.get_dsn).
"""

from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.db import connection as db
from app.entities.projectors import project_entity_created
from app.events.emitter import emit_entity_created
from app.events.models import EntityCreatedPayload, Event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _resolved_dsn() -> str:
    return os.environ.get("TRUSIGNAL_TEST_DATABASE_URL") or db.get_dsn()


@pytest.fixture(scope="session", autouse=True)
def bootstrap_substrate_db() -> None:
    """Migrations applied + triggers verified once per test session."""
    db.bootstrap(dsn=_resolved_dsn())


@pytest.fixture()
def conn() -> psycopg.Connection:
    """Rollback-isolated connection: emits + projections never persist."""
    c = psycopg.connect(_resolved_dsn())
    try:
        yield c
    finally:
        try:
            c.rollback()
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Canonical first-projection target — A1 Garage Doors / Tommy Mello / GARAGE_DOOR
# ---------------------------------------------------------------------------


def _emit_a1_event(conn: psycopg.Connection) -> Event:
    """
    Emit a real entity.created event inside the caller's transaction so the
    projector's FK to events(event_id) resolves. The fixture's rollback at
    teardown cleans up both the event and the entities row.
    """
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
# Layer 1 — Happy-path projection
# ===========================================================================


def test_project_entity_created_inserts_row(conn: psycopg.Connection) -> None:
    """
    Canonical first projection: A1 Garage Doors entity.created → one row
    in entities with every column matching the value derived from the
    event tuple.
    """
    event = _emit_a1_event(conn)

    project_entity_created(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id, name, vertical, created_at_for_projection, "
            "created_event_id, projected_at "
            "FROM entities WHERE entity_id = %s",
            (event.payload.entity_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == event.payload.entity_id
    assert row[1] == "A1 Garage Doors"
    assert row[2] == "GARAGE_DOOR"
    assert row[3] == event.payload.created_at_for_projection
    assert row[4] == event.event_id
    assert row[5] == event.occurred_at


# ===========================================================================
# Layer 2 — Idempotence
# ===========================================================================


def test_project_entity_created_is_idempotent(conn: psycopg.Connection) -> None:
    """
    ON CONFLICT (entity_id) DO NOTHING. The second projection of the same
    event is a no-op; the entities table still contains exactly one row
    for this entity_id.
    """
    event = _emit_a1_event(conn)

    project_entity_created(conn, event)
    project_entity_created(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM entities WHERE entity_id = %s",
            (event.payload.entity_id,),
        )
        count = cur.fetchone()[0]

    assert count == 1


# ===========================================================================
# Layer 3 — Deterministic projection
# ===========================================================================


def test_project_entity_created_is_deterministic(conn: psycopg.Connection) -> None:
    """
    Same event input → identical entity row. Re-projecting the event does
    not mutate any column. Combined with the happy-path test, this proves
    every column is a pure function of the event tuple.
    """
    event = _emit_a1_event(conn)

    project_entity_created(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id, name, vertical, created_at_for_projection, "
            "created_event_id, projected_at "
            "FROM entities WHERE entity_id = %s",
            (event.payload.entity_id,),
        )
        first = cur.fetchone()

    project_entity_created(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id, name, vertical, created_at_for_projection, "
            "created_event_id, projected_at "
            "FROM entities WHERE entity_id = %s",
            (event.payload.entity_id,),
        )
        second = cur.fetchone()

    assert first == second


# ===========================================================================
# Layer 4 — Static source-grep: projector has no non-determinism sources
# ===========================================================================


def test_projector_source_has_no_nondeterminism_sources() -> None:
    """
    Static guard: projectors.py must NOT contain any clock, randomness,
    env, file, or network call. The projector is a pure function of the
    event tuple. This test is a substring check against the source file
    so the discipline survives future edits.

    Token list mirrors the Step-5 authorization (datetime.now, uuid.uuid4,
    random, os.environ, open(, requests, httpx).
    """
    src_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app" / "entities" / "projectors.py"
    )
    src = src_path.read_text(encoding="utf-8")

    forbidden = (
        "datetime.now",
        "uuid.uuid4",
        "random",
        "os.environ",
        "open(",
        "requests",
        "httpx",
    )
    found = [token for token in forbidden if token in src]
    assert found == [], (
        f"projectors.py must not reference non-determinism sources, "
        f"but the following tokens were found: {found}"
    )
