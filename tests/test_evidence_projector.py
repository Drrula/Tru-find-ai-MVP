"""
tests/test_evidence_projector.py

Day-1 Step 9 verification. Mirrors tests/test_entities_projector.py
discipline for the evidence_raw projection. Four layers:

    1. Happy-path projection of a synthetic A1 Garage Doors website-fetch
       evidence.raw_ingested event into the evidence_raw table. All nine
       columns match values derived from the event tuple.

    2. Idempotence: projecting the same event twice produces one row
       (ON CONFLICT (evidence_id) DO NOTHING).

    3. Determinism: re-projecting the same event leaves every column
       byte-equal to the first projection. Together with (1), this proves
       the projection row is a pure function of the event tuple.

    4. Static source-grep guard: app/evidence/projectors.py does not
       import or call any non-determinism source (datetime.now, uuid.uuid4,
       random, os.environ, open(, requests, httpx).

Plus a focused schema test asserting evidence_raw has NO metadata column —
metadata lives exclusively in events.payload.

Scope discipline:
    - No replay-engine import, no replay test (those live in
      tests/test_replay_determinism.py).
    - Rollback-isolated per-test connection: emitted events and projected
      rows never persist beyond the test.

Environment:
    - DSN comes from TRUSIGNAL_TEST_DATABASE_URL if set, else falls back
      to TRUSIGNAL_DATABASE_URL (resolved by app.db.connection.get_dsn).
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.db import connection as db
from app.events.emitter import emit_evidence_raw_ingested
from app.events.models import EvidenceRawIngestedPayload, Event
from app.evidence.projectors import project_evidence_raw_ingested


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
# Canonical synthetic evidence — A1 Garage Doors website fetch
# ---------------------------------------------------------------------------

_A1_SYNTHETIC_CONTENT: bytes = (
    b"<html><body>A1 Garage Doors - Step-9 projector fixture</body></html>"
)


def _emit_a1_evidence_event(
    conn: psycopg.Connection,
    *,
    subject_entity_id: uuid.UUID | None = None,
) -> Event:
    """
    Emit a fresh synthetic A1 Garage Doors evidence.raw_ingested event
    inside the caller's transaction so the projector's FK to events
    resolves. The fixture's rollback at teardown cleans up.
    """
    payload = EvidenceRawIngestedPayload(
        evidence_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        source_uri="https://example.invalid/a1-garage-doors",
        source_type="website_fetch",
        content_hash=hashlib.sha256(_A1_SYNTHETIC_CONTENT).hexdigest(),
        storage_uri="s3://substrate-evidence/synthetic/a1-garage-doors.html",
        observed_at_for_projection=datetime.now(timezone.utc),
        metadata={"http_status": "200", "vertical": "GARAGE_DOOR"},
    )
    return emit_evidence_raw_ingested(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )


# ===========================================================================
# Layer 1 — Happy-path projection
# ===========================================================================


def test_project_evidence_raw_ingested_inserts_row(
    conn: psycopg.Connection,
) -> None:
    """
    Canonical Step-9 projection: A1 Garage Doors evidence.raw_ingested
    becomes one row in evidence_raw with every column matching the value
    derived from the event tuple.
    """
    event = _emit_a1_evidence_event(conn)

    project_evidence_raw_ingested(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence_id, subject_entity_id, source_uri, source_type, "
            "content_hash, storage_uri, observed_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_raw WHERE evidence_id = %s",
            (event.payload.evidence_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == event.payload.evidence_id
    assert row[1] == event.payload.subject_entity_id  # may be None
    assert row[2] == event.payload.source_uri
    assert row[3] == event.payload.source_type
    assert row[4] == event.payload.content_hash
    assert row[5] == event.payload.storage_uri
    assert row[6] == event.payload.observed_at_for_projection
    assert row[7] == event.event_id
    assert row[8] == event.occurred_at


def test_evidence_raw_schema_has_no_metadata_column(
    conn: psycopg.Connection,
) -> None:
    """
    evidence_raw has NO metadata column by design — metadata lives in
    events.payload (JSONB). This test pins the schema decision so any
    future migration that adds metadata to evidence_raw must consciously
    update this test.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'evidence_raw' "
            "ORDER BY ordinal_position"
        )
        columns = {r[0] for r in cur.fetchall()}

    assert "metadata" not in columns, (
        "evidence_raw must not have a metadata column; metadata is "
        "exclusively stored in events.payload (queryable via JOIN to "
        "events ON created_event_id)."
    )
    expected = {
        "evidence_id",
        "subject_entity_id",
        "source_uri",
        "source_type",
        "content_hash",
        "storage_uri",
        "observed_at_for_projection",
        "created_event_id",
        "projected_at",
    }
    assert expected <= columns, f"missing columns: {expected - columns}"


# ===========================================================================
# Layer 2 — Idempotence
# ===========================================================================


def test_project_evidence_raw_ingested_is_idempotent(
    conn: psycopg.Connection,
) -> None:
    """
    ON CONFLICT (evidence_id) DO NOTHING — the second projection of the
    same event is a no-op; evidence_raw still contains exactly one row
    for this evidence_id.
    """
    event = _emit_a1_evidence_event(conn)

    project_evidence_raw_ingested(conn, event)
    project_evidence_raw_ingested(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM evidence_raw WHERE evidence_id = %s",
            (event.payload.evidence_id,),
        )
        count = cur.fetchone()[0]

    assert count == 1


# ===========================================================================
# Layer 3 — Deterministic projection
# ===========================================================================


def test_project_evidence_raw_ingested_is_deterministic(
    conn: psycopg.Connection,
) -> None:
    """
    Same event input → identical evidence_raw row. Re-projecting the
    event does not mutate any column. Combined with the happy-path test,
    this proves every column is a pure function of the event tuple.
    """
    event = _emit_a1_evidence_event(conn)

    project_evidence_raw_ingested(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence_id, subject_entity_id, source_uri, source_type, "
            "content_hash, storage_uri, observed_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_raw WHERE evidence_id = %s",
            (event.payload.evidence_id,),
        )
        first = cur.fetchone()

    project_evidence_raw_ingested(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence_id, subject_entity_id, source_uri, source_type, "
            "content_hash, storage_uri, observed_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_raw WHERE evidence_id = %s",
            (event.payload.evidence_id,),
        )
        second = cur.fetchone()

    assert first == second


# ===========================================================================
# Layer 4 — Static source-grep: projector has no non-determinism sources
# ===========================================================================


def test_projector_source_has_no_nondeterminism_sources() -> None:
    """
    Static guard: app/evidence/projectors.py must NOT contain any clock,
    randomness, env, file, or network call. The projector is a pure
    function of the event tuple. This substring check makes the discipline
    survive future edits.

    Token list mirrors the Step-9 authorization (datetime.now, uuid.uuid4,
    random, os.environ, open(, requests, httpx) and matches the Step-5
    entity projector's identical guard.
    """
    src_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app" / "evidence" / "projectors.py"
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
        f"app/evidence/projectors.py must not reference non-determinism "
        f"sources, but the following tokens were found: {found}"
    )
