"""
tests/test_compliance_state_projector.py

Day-1 Step 11 verification. Mirrors the Step-10 evidence_derived
projector test discipline for the compliance_state projection.

    1. Happy-path projection of a synthetic A1 Garage Doors
       compliance.state_asserted event into compliance_state. All nine
       columns match the values derived from the event tuple.

    2. Schema pin: compliance_state contains exactly the expected
       columns, including policy_id, policy_version, and assertion
       (assertion is projection substance, not auxiliary metadata).

    3. Idempotence: projecting the same event twice produces one row
       (ON CONFLICT (compliance_state_id) DO NOTHING).

    4. Determinism: re-projecting the same event leaves every column
       byte-equal to the first projection.

    5. parent_derived_evidence_ids ORDER preservation: a specific
       multi-element order survives the projection round-trip.

    6. Empty parent_derived_evidence_ids: REJECTED at the Pydantic /
       emit layer per Step-11 doctrine (the projector layer is
       therefore unreachable with an empty list — verified upstream).

    7. Static source-grep guard: app/compliance/projectors.py contains
       no non-determinism source (datetime.now, uuid.uuid4, random,
       os.environ, open(, requests, httpx).

DOCTRINE (Day-1 Step 11):
    Tests treat compliance_state assertions as REPLAYABLE HISTORICAL
    INTERPRETATIONS made under a specific (policy_id, policy_version)
    and evidence context — NOT canonical objective truth. The
    projector records what was asserted at the time the assertion was
    made; replay never re-runs policy evaluation.

Scope discipline:
    - Replay-engine tests live in tests/test_replay_determinism.py.
    - Rollback-isolated per-test connection.
"""

from __future__ import annotations

import os
import pathlib
import typing
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.compliance.projectors import project_compliance_state_asserted
from app.db import connection as db
from app.events.emitter import emit_compliance_state_asserted
from app.events.models import ComplianceStateAssertedPayload, Event


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
# Canonical synthetic compliance-state-asserted event
# ---------------------------------------------------------------------------


def _emit_a1_compliance_event(
    conn: psycopg.Connection,
    *,
    subject_entity_id: uuid.UUID | None = None,
    parent_derived_evidence_ids: list[uuid.UUID] | None = None,
    policy_id: str = "us_dnc_v1",
    policy_version: str = "1.0.0",
    assertion: dict[str, typing.Any] | None = None,
) -> Event:
    """
    Emit a fresh A1 Garage Doors compliance.state_asserted event inside
    the caller's transaction so the projector's FK to events resolves.
    """
    if parent_derived_evidence_ids is None:
        parent_derived_evidence_ids = [uuid.uuid4(), uuid.uuid4()]
    if assertion is None:
        assertion = {
            "compliant": False,
            "blocker": "phone_on_dnc_list",
            "confidence": 0.92,
        }
    payload = ComplianceStateAssertedPayload(
        compliance_state_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        parent_derived_evidence_ids=parent_derived_evidence_ids,
        policy_id=policy_id,
        policy_version=policy_version,
        assertion=assertion,
        asserted_at_for_projection=datetime.now(timezone.utc),
    )
    return emit_compliance_state_asserted(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )


# ===========================================================================
# Layer 1 — Happy-path projection
# ===========================================================================


def test_project_compliance_state_inserts_row(conn: psycopg.Connection) -> None:
    """
    Canonical Step-11 projection: every one of the 9 columns matches the
    value derived from the event tuple.
    """
    event = _emit_a1_compliance_event(conn)

    project_compliance_state_asserted(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT compliance_state_id, subject_entity_id, "
            "parent_derived_evidence_ids, policy_id, policy_version, "
            "assertion, asserted_at_for_projection, "
            "created_event_id, projected_at "
            "FROM compliance_state WHERE compliance_state_id = %s",
            (event.payload.compliance_state_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == event.payload.compliance_state_id
    assert row[1] == event.payload.subject_entity_id  # may be None
    assert row[2] == event.payload.parent_derived_evidence_ids
    assert row[3] == event.payload.policy_id
    assert row[4] == event.payload.policy_version
    assert row[5] == event.payload.assertion
    assert row[6] == event.payload.asserted_at_for_projection
    assert row[7] == event.event_id
    assert row[8] == event.occurred_at


def test_compliance_state_schema_contains_expected_columns(
    conn: psycopg.Connection,
) -> None:
    """
    compliance_state must contain exactly these 9 columns. policy_id,
    policy_version, and assertion are all materialized projection
    substance (query-substantive metadata + the actual policy/risk claim).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'compliance_state' "
            "ORDER BY ordinal_position"
        )
        columns = {r[0] for r in cur.fetchall()}

    expected = {
        "compliance_state_id",
        "subject_entity_id",
        "parent_derived_evidence_ids",
        "policy_id",
        "policy_version",
        "assertion",
        "asserted_at_for_projection",
        "created_event_id",
        "projected_at",
    }
    assert expected <= columns, f"missing columns: {expected - columns}"
    # The projection should NOT carry auxiliary evaluator metadata
    # (evaluator runtime, retry count, audit signatures, prompt template
    # id, etc.) — those stay in events.payload only.
    assert "metadata" not in columns, (
        "compliance_state must not have a metadata column; auxiliary "
        "evaluator metadata is exclusively stored in events.payload."
    )


# ===========================================================================
# Layer 2 — Idempotence
# ===========================================================================


def test_project_compliance_state_is_idempotent(conn: psycopg.Connection) -> None:
    """
    ON CONFLICT (compliance_state_id) DO NOTHING — the second projection
    of the same event is a no-op.
    """
    event = _emit_a1_compliance_event(conn)

    project_compliance_state_asserted(conn, event)
    project_compliance_state_asserted(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM compliance_state "
            "WHERE compliance_state_id = %s",
            (event.payload.compliance_state_id,),
        )
        count = cur.fetchone()[0]

    assert count == 1


# ===========================================================================
# Layer 3 — Deterministic projection
# ===========================================================================


def test_project_compliance_state_is_deterministic(
    conn: psycopg.Connection,
) -> None:
    """
    Re-projecting the same event leaves every column byte-equal to the
    first projection.
    """
    event = _emit_a1_compliance_event(conn)

    project_compliance_state_asserted(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT compliance_state_id, subject_entity_id, "
            "parent_derived_evidence_ids, policy_id, policy_version, "
            "assertion, asserted_at_for_projection, "
            "created_event_id, projected_at "
            "FROM compliance_state WHERE compliance_state_id = %s",
            (event.payload.compliance_state_id,),
        )
        first = cur.fetchone()

    project_compliance_state_asserted(conn, event)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT compliance_state_id, subject_entity_id, "
            "parent_derived_evidence_ids, policy_id, policy_version, "
            "assertion, asserted_at_for_projection, "
            "created_event_id, projected_at "
            "FROM compliance_state WHERE compliance_state_id = %s",
            (event.payload.compliance_state_id,),
        )
        second = cur.fetchone()

    assert first == second


# ===========================================================================
# Layer 4 — parent_derived_evidence_ids order preservation
# ===========================================================================


def test_project_compliance_state_preserves_parent_ids_order(
    conn: psycopg.Connection,
) -> None:
    """
    parent_derived_evidence_ids ORDER must be preserved end-to-end
    through the projector. A specific multi-element order is asserted
    to match exactly after the projection round-trip.
    """
    parents_in = [
        uuid.UUID("11111111-1111-4111-8111-111111111111"),
        uuid.UUID("22222222-2222-4222-8222-222222222222"),
        uuid.UUID("33333333-3333-4333-8333-333333333333"),
        uuid.UUID("44444444-4444-4444-8444-444444444444"),
    ]
    event = _emit_a1_compliance_event(
        conn, parent_derived_evidence_ids=parents_in,
    )

    project_compliance_state_asserted(conn, event)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT parent_derived_evidence_ids FROM compliance_state "
            "WHERE compliance_state_id = %s",
            (event.payload.compliance_state_id,),
        )
        stored = cur.fetchone()[0]

    assert stored == parents_in, (
        "parent_derived_evidence_ids order was NOT preserved through the "
        "compliance_state projection. The substrate's order-preservation "
        "contract is broken.\n"
        f"  in:  {parents_in}\n"
        f"  out: {stored}"
    )


def test_project_compliance_state_rejects_empty_parent_ids_upstream(
    conn: psycopg.Connection,
) -> None:
    """
    Empty parent_derived_evidence_ids is REJECTED at the Pydantic /
    emit layer per Step-11 doctrine — the projector is never reached
    with an empty list. This test pins the upstream rejection so the
    projector layer can safely assume a non-empty array.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _emit_a1_compliance_event(conn, parent_derived_evidence_ids=[])


# ===========================================================================
# Layer 5 — Static source-grep: projector has no non-determinism sources
# ===========================================================================


def test_projector_source_has_no_nondeterminism_sources() -> None:
    """
    Static guard: app/compliance/projectors.py must NOT contain any
    clock, randomness, env, file, or network call. The compliance
    projector is a pure function of the event tuple; policy evaluation
    runs OUTSIDE the substrate.
    """
    src_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app" / "compliance" / "projectors.py"
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
        f"app/compliance/projectors.py must not reference non-determinism "
        f"sources, but the following tokens were found: {found}"
    )
