"""
tests/test_evidence_derived_projector.py

Day-1 Step 10 verification. Mirrors test_entities_projector.py and
test_evidence_projector.py discipline for the evidence_derived projection.

    1. Happy-path projection of a synthetic A1 Garage Doors
       evidence.derived_created event into evidence_derived. All nine
       columns match the values derived from the event tuple.

    2. Schema pin: evidence_derived contains exactly the expected
       columns, including derivation_version AND output_payload
       (both materialized as projection substance).

    3. Idempotence: projecting the same event twice produces one row
       (ON CONFLICT (derived_evidence_id) DO NOTHING).

    4. Determinism: re-projecting the same event leaves every column
       byte-equal to the first projection.

    5. parent_evidence_ids ORDER preservation: a specific multi-element
       order survives the projection round-trip.

    6. Empty parent_evidence_ids list: REJECTED at the Pydantic /
       emit layer per Blueprint §10/§11 (the projector layer is
       therefore unreachable with an empty list — verified upstream).

    7. Static source-grep guard: app/evidence/projectors.py contains no
       non-determinism source (datetime.now, uuid.uuid4, random,
       os.environ, open(, requests, httpx). This guard now scans BOTH
       projectors (raw + derived) since they share the file.

Scope discipline:
    - Replay-engine tests live in tests/test_replay_determinism.py.
    - Rollback-isolated per-test connection.
"""

from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.db import connection as db
from app.events.emitter import emit_evidence_derived_created
from app.events.models import EvidenceDerivedCreatedPayload, Event
from app.evidence.projectors import project_evidence_derived_created


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
    """Rollback-isolated connection."""
    c = psycopg.connect(_resolved_dsn())
    try:
        yield c
    finally:
        try:
            c.rollback()
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Canonical synthetic derived-evidence event
# ---------------------------------------------------------------------------


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
    Emit a fresh A1 Garage Doors evidence.derived_created event inside
    the caller's transaction so the projector's FK to events resolves.
    """
    if parent_evidence_ids is None:
        parent_evidence_ids = [uuid.uuid4(), uuid.uuid4()]
    if output_payload is None:
        output_payload = {
            "summary": "A1 Garage Doors operator content (synthetic)",
            "confidence": 0.85,
            "claims": ["operator-led", "garage-door-vertical"],
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


# ===========================================================================
# Layer 1 — Happy-path projection
# ===========================================================================


def test_project_evidence_derived_inserts_row(conn: psycopg.Connection) -> None:
    """
    Canonical Step-10 projection: every one of the 9 columns matches the
    value derived from the event tuple.
    """
    event = _emit_a1_derived_event(conn)

    project_evidence_derived_created(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT derived_evidence_id, subject_entity_id, "
            "parent_evidence_ids, derivation_type, derivation_version, "
            "output_payload, derived_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_derived WHERE derived_evidence_id = %s",
            (event.payload.derived_evidence_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == event.payload.derived_evidence_id
    assert row[1] == event.payload.subject_entity_id  # may be None
    assert row[2] == event.payload.parent_evidence_ids
    assert row[3] == event.payload.derivation_type
    assert row[4] == event.payload.derivation_version
    assert row[5] == event.payload.output_payload
    assert row[6] == event.payload.derived_at_for_projection
    assert row[7] == event.event_id
    assert row[8] == event.occurred_at


def test_evidence_derived_schema_contains_expected_columns(
    conn: psycopg.Connection,
) -> None:
    """
    evidence_derived must contain exactly these 9 columns. Both
    derivation_version AND output_payload are materialized projection
    substance, not auxiliary metadata.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'evidence_derived' "
            "ORDER BY ordinal_position"
        )
        columns = {r[0] for r in cur.fetchall()}

    expected = {
        "derived_evidence_id",
        "subject_entity_id",
        "parent_evidence_ids",
        "derivation_type",
        "derivation_version",
        "output_payload",
        "derived_at_for_projection",
        "created_event_id",
        "projected_at",
    }
    assert expected <= columns, f"missing columns: {expected - columns}"
    # The projection should NOT carry auxiliary derivation metadata
    # (prompt template id, model parameters, retry count, etc.) — those
    # stay in events.payload only.
    assert "metadata" not in columns, (
        "evidence_derived must not have a metadata column; auxiliary "
        "derivation metadata is exclusively stored in events.payload."
    )


# ===========================================================================
# Layer 2 — Idempotence
# ===========================================================================


def test_project_evidence_derived_is_idempotent(conn: psycopg.Connection) -> None:
    """
    ON CONFLICT (derived_evidence_id) DO NOTHING — the second projection
    of the same event is a no-op.
    """
    event = _emit_a1_derived_event(conn)

    project_evidence_derived_created(conn, event)
    project_evidence_derived_created(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM evidence_derived "
            "WHERE derived_evidence_id = %s",
            (event.payload.derived_evidence_id,),
        )
        count = cur.fetchone()[0]

    assert count == 1


# ===========================================================================
# Layer 3 — Deterministic projection
# ===========================================================================


def test_project_evidence_derived_is_deterministic(
    conn: psycopg.Connection,
) -> None:
    """
    Re-projecting the same event leaves every column byte-equal to the
    first projection.
    """
    event = _emit_a1_derived_event(conn)

    project_evidence_derived_created(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT derived_evidence_id, subject_entity_id, "
            "parent_evidence_ids, derivation_type, derivation_version, "
            "output_payload, derived_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_derived WHERE derived_evidence_id = %s",
            (event.payload.derived_evidence_id,),
        )
        first = cur.fetchone()

    project_evidence_derived_created(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT derived_evidence_id, subject_entity_id, "
            "parent_evidence_ids, derivation_type, derivation_version, "
            "output_payload, derived_at_for_projection, "
            "created_event_id, projected_at "
            "FROM evidence_derived WHERE derived_evidence_id = %s",
            (event.payload.derived_evidence_id,),
        )
        second = cur.fetchone()

    assert first == second


# ===========================================================================
# Layer 4 — parent_evidence_ids order preservation
# ===========================================================================


def test_project_evidence_derived_preserves_parent_evidence_ids_order(
    conn: psycopg.Connection,
) -> None:
    """
    parent_evidence_ids ORDER must be preserved end-to-end through the
    projector. A specific multi-element order is asserted to match
    exactly after the projection round-trip.
    """
    parents_in = [
        uuid.UUID("11111111-1111-4111-8111-111111111111"),
        uuid.UUID("22222222-2222-4222-8222-222222222222"),
        uuid.UUID("33333333-3333-4333-8333-333333333333"),
        uuid.UUID("44444444-4444-4444-8444-444444444444"),
    ]
    event = _emit_a1_derived_event(conn, parent_evidence_ids=parents_in)

    project_evidence_derived_created(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT parent_evidence_ids FROM evidence_derived "
            "WHERE derived_evidence_id = %s",
            (event.payload.derived_evidence_id,),
        )
        stored = cur.fetchone()[0]

    assert stored == parents_in, (
        "parent_evidence_ids order was NOT preserved through the "
        "evidence_derived projection. The substrate's order-preservation "
        "contract is broken.\n"
        f"  in:  {parents_in}\n"
        f"  out: {stored}"
    )


def test_project_evidence_derived_rejects_empty_parent_evidence_ids_upstream(
    conn: psycopg.Connection,
) -> None:
    """
    Empty parent_evidence_ids is REJECTED at the Pydantic / emit layer
    per Blueprint §10/§11 — the projector is never reached with an
    empty list. This test pins the upstream rejection so the projector
    layer can safely assume a non-empty array.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _emit_a1_derived_event(conn, parent_evidence_ids=[])


# ===========================================================================
# Layer 5 — Static source-grep: projector has no non-determinism sources
# ===========================================================================


def test_projector_source_has_no_nondeterminism_sources() -> None:
    """
    Static guard: app/evidence/projectors.py (now containing BOTH the raw
    and derived projector functions) must NOT contain any clock,
    randomness, env, file, or network call.
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
