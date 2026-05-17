"""
tests/test_evidence_derived_emitter.py

Day-1 Step 10 verification. Two layers, mirroring the Step 8 shape for
the new evidence.derived_created event type.

    1. Pure model validation (no DB):
       - EvidenceDerivedCreatedPayload accepts a valid construction.
       - extra="forbid" rejects unknown fields.
       - min_length=1 rejects empty derivation_type / derivation_version.
       - derived_evidence_id required (UUID).
       - subject_entity_id optional (UUID | None).
       - parent_evidence_ids is non-empty list[UUID]; empty rejected
         per Blueprint §10/§11 provenance-DAG invariant (min_length=1).
       - output_payload is dict[str, Any]; required.
       - frozen=True (immutable post-construction).
       - The EventType discriminator includes "evidence.derived_created".
       - Event envelope's payload Union accepts the new payload type
         AND still accepts the existing two.
       - The Event aggregate-invariant validator covers
         evidence.derived_created (happy + mismatch).

    2. Single-transaction emit against the live substrate
       (rollback-isolated):
       - emit_evidence_derived_created lands one row in events with the
         expected shape and aggregate_type = "evidence".
       - Payload round-trips via JSONB, including parent_evidence_ids
         as an ORDERED JSON array, derivation_version verbatim, and
         output_payload verbatim with sort_keys-stable key ordering.
       - Each emit gets a fresh event_id.
       - aggregate_id equals payload.derived_evidence_id.
       - subject_entity_id may be NULL.
       - causation_id / correlation_id round-trip exactly.
       - parent_evidence_ids ORDER survives the JSONB round-trip.
       - Construction from a plain dict (replay path simulation) resolves
         to EvidenceDerivedCreatedPayload via plain-Union dispatch.
"""

from __future__ import annotations

import os
import typing
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from pydantic import ValidationError

from app.db import connection as db
from app.events.emitter import (
    EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION,
    emit_evidence_derived_created,
)
from app.events.models import (
    AGGREGATE_TYPE_EVIDENCE,
    EntityCreatedPayload,
    Event,
    EventType,
    EvidenceDerivedCreatedPayload,
    EvidenceRawIngestedPayload,
)


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
# Canonical synthetic A1 derived evidence (Step-10 fixture)
# ---------------------------------------------------------------------------


def _a1_derived_payload(
    *,
    subject_entity_id: uuid.UUID | None = None,
    parent_evidence_ids: list[uuid.UUID] | None = None,
    derivation_type: str = "summary_extraction",
    derivation_version: str = "summarizer-v1.0.0",
    output_payload: dict[str, typing.Any] | None = None,
) -> EvidenceDerivedCreatedPayload:
    """
    Build a fresh synthetic A1 Garage Doors derived-evidence payload.
    Parent IDs default to a fixed two-element list (order matters for
    the order-preservation tests). output_payload defaults to a simple
    JSON-primitive dict.
    """
    if parent_evidence_ids is None:
        parent_evidence_ids = [uuid.uuid4(), uuid.uuid4()]
    if output_payload is None:
        output_payload = {
            "summary": "A1 Garage Doors operator content (synthetic)",
            "confidence": 0.85,
            "claims": ["operator-led", "garage-door-vertical"],
        }
    return EvidenceDerivedCreatedPayload(
        derived_evidence_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        parent_evidence_ids=parent_evidence_ids,
        derivation_type=derivation_type,
        derivation_version=derivation_version,
        output_payload=output_payload,
        derived_at_for_projection=datetime.now(timezone.utc),
    )


# ===========================================================================
# Layer 1 — Pure model validation
# ===========================================================================


def test_derived_payload_accepts_valid_construction() -> None:
    payload = _a1_derived_payload()
    assert isinstance(payload.derived_evidence_id, uuid.UUID)
    assert payload.subject_entity_id is None
    assert len(payload.parent_evidence_ids) == 2
    assert payload.derivation_type == "summary_extraction"
    assert payload.derivation_version == "summarizer-v1.0.0"
    assert payload.output_payload["confidence"] == 0.85
    assert payload.derived_at_for_projection.tzinfo is not None


def test_derived_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EvidenceDerivedCreatedPayload(
            derived_evidence_id=uuid.uuid4(),
            parent_evidence_ids=[uuid.uuid4()],
            derivation_type="x",
            derivation_version="v1",
            output_payload={},
            derived_at_for_projection=datetime.now(timezone.utc),
            unexpected_field="boom",  # type: ignore[call-arg]
        )


def test_derived_payload_rejects_empty_derivation_type() -> None:
    with pytest.raises(ValidationError):
        EvidenceDerivedCreatedPayload(
            derived_evidence_id=uuid.uuid4(),
            parent_evidence_ids=[uuid.uuid4()],
            derivation_type="",
            derivation_version="v1",
            output_payload={},
            derived_at_for_projection=datetime.now(timezone.utc),
        )


def test_derived_payload_rejects_empty_derivation_version() -> None:
    with pytest.raises(ValidationError):
        EvidenceDerivedCreatedPayload(
            derived_evidence_id=uuid.uuid4(),
            parent_evidence_ids=[uuid.uuid4()],
            derivation_type="x",
            derivation_version="",
            output_payload={},
            derived_at_for_projection=datetime.now(timezone.utc),
        )


def test_derived_payload_rejects_empty_parent_evidence_ids() -> None:
    """
    Empty parent_evidence_ids list is REJECTED per Blueprint §10/§11
    provenance-DAG invariant: derived evidence must reference one or
    more parents. Enforced at the Pydantic layer via min_length=1.
    """
    with pytest.raises(ValidationError):
        EvidenceDerivedCreatedPayload(
            derived_evidence_id=uuid.uuid4(),
            parent_evidence_ids=[],
            derivation_type="x",
            derivation_version="v1",
            output_payload={},
            derived_at_for_projection=datetime.now(timezone.utc),
        )


def test_derived_payload_accepts_optional_subject_entity_id() -> None:
    """subject_entity_id is optional (UUID | None)."""
    payload = _a1_derived_payload(subject_entity_id=None)
    assert payload.subject_entity_id is None

    entity_id = uuid.uuid4()
    payload2 = _a1_derived_payload(subject_entity_id=entity_id)
    assert payload2.subject_entity_id == entity_id


def test_derived_payload_output_payload_accepts_empty_dict() -> None:
    """output_payload may be an empty dict at this layer."""
    payload = _a1_derived_payload(output_payload={})
    assert payload.output_payload == {}


def test_derived_payload_is_frozen() -> None:
    """frozen=True makes the payload immutable post-construction."""
    payload = _a1_derived_payload()
    with pytest.raises(ValidationError):
        payload.derivation_type = "claim_extraction"  # type: ignore[misc]


def test_event_type_literal_includes_evidence_derived_created() -> None:
    """The EventType discriminator was widened in Step 10."""
    args = typing.get_args(EventType)
    assert "entity.created" in args
    assert "evidence.raw_ingested" in args
    assert "evidence.derived_created" in args


def test_event_envelope_accepts_derived_payload() -> None:
    """The Event Union now includes EvidenceDerivedCreatedPayload."""
    payload = _a1_derived_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.derived_created",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=payload.derived_evidence_id,
        payload=payload,
        schema_version=EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(event.payload, EvidenceDerivedCreatedPayload)
    assert event.aggregate_type == "evidence"


def test_event_envelope_still_accepts_entity_and_raw_payloads() -> None:
    """Widening the Union must NOT regress the two existing payload paths."""
    entity_payload = EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=datetime.now(timezone.utc),
    )
    now = datetime.now(timezone.utc)
    e1 = Event(
        event_id=uuid.uuid4(),
        event_type="entity.created",
        aggregate_type="entity",
        aggregate_id=entity_payload.entity_id,
        payload=entity_payload,
        schema_version="1.0.0",
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(e1.payload, EntityCreatedPayload)

    raw_payload = EvidenceRawIngestedPayload(
        evidence_id=uuid.uuid4(),
        source_uri="https://example.invalid/x",
        source_type="website_fetch",
        content_hash="a" * 64,
        storage_uri="s3://b/x",
        observed_at_for_projection=datetime.now(timezone.utc),
    )
    e2 = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.raw_ingested",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=raw_payload.evidence_id,
        payload=raw_payload,
        schema_version="1.0.0",
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(e2.payload, EvidenceRawIngestedPayload)


def test_event_validator_accepts_matching_derived_aggregate_id() -> None:
    """Happy path for evidence.derived_created envelope."""
    payload = _a1_derived_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.derived_created",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=payload.derived_evidence_id,
        payload=payload,
        schema_version=EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.aggregate_id == payload.derived_evidence_id


def test_event_validator_rejects_mismatched_derived_aggregate_id() -> None:
    """Misaligned derived envelope: aggregate_id != derived_evidence_id raises."""
    payload = _a1_derived_payload()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError) as excinfo:
        Event(
            event_id=uuid.uuid4(),
            event_type="evidence.derived_created",
            aggregate_type=AGGREGATE_TYPE_EVIDENCE,
            aggregate_id=uuid.uuid4(),  # NOT payload.derived_evidence_id
            payload=payload,
            schema_version=EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION,
            occurred_at=now,
            recorded_at=now,
            actor_type="analyst",
            actor_id="andrew",
        )
    assert "aggregate_id" in str(excinfo.value)
    assert "derived_evidence_id" in str(excinfo.value)


# ===========================================================================
# Layer 2 — Single-transaction emit (rollback-isolated)
# ===========================================================================


def test_emit_derived_inserts_event_row(conn: psycopg.Connection) -> None:
    """
    Canonical Step-10 emit: synthetic A1 Garage Doors derived evidence.
    After emit, the row must be readable inside the same transaction
    with the expected shape.
    """
    payload = _a1_derived_payload()
    event = emit_evidence_derived_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
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
    assert row[1] == "evidence.derived_created"
    assert row[2] == AGGREGATE_TYPE_EVIDENCE
    assert row[3] == payload.derived_evidence_id
    assert row[4] == EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION
    assert row[5] == "analyst"
    assert row[6] == "andrew"


def test_emit_derived_payload_round_trips_via_jsonb(
    conn: psycopg.Connection,
) -> None:
    """
    All payload fields (incl. parent_evidence_ids list,
    derivation_version, and output_payload dict) survive the JSON
    serialize → JSONB store → JSON parse round-trip.
    """
    entity_id = uuid.uuid4()
    parent_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    payload = _a1_derived_payload(
        subject_entity_id=entity_id,
        parent_evidence_ids=parent_ids,
        derivation_version="summarizer-2026.05@a3f1b2c",
        output_payload={"summary": "round-trip test", "score": 0.42},
    )
    event = emit_evidence_derived_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["derived_evidence_id"] == str(payload.derived_evidence_id)
    assert stored["subject_entity_id"] == str(entity_id)
    assert stored["derivation_type"] == "summary_extraction"
    assert stored["derivation_version"] == "summarizer-2026.05@a3f1b2c"
    assert stored["output_payload"] == {"summary": "round-trip test", "score": 0.42}
    assert stored["parent_evidence_ids"] == [str(p) for p in parent_ids]
    assert isinstance(stored["derived_at_for_projection"], str)
    assert "T" in stored["derived_at_for_projection"]


def test_emit_derived_parent_evidence_ids_order_preserved_in_event_payload(
    conn: psycopg.Connection,
) -> None:
    """
    parent_evidence_ids ORDER must survive the JSONB round-trip end-to-end:
    Python list[UUID] → model_dump(mode='json') list[str] → json.dumps
    (stable) → JSONB → psycopg JSONB→list[str] → expected order.
    """
    parents_in = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    payload = _a1_derived_payload(parent_evidence_ids=parents_in)
    event = emit_evidence_derived_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload->'parent_evidence_ids' "
            "FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored_list = cur.fetchone()[0]

    expected = [str(p) for p in parents_in]
    assert stored_list == expected, (
        "parent_evidence_ids order was not preserved through the event "
        f"payload JSONB round-trip. expected={expected}, got={stored_list}"
    )


def test_emit_derived_generates_distinct_event_ids(
    conn: psycopg.Connection,
) -> None:
    e1 = emit_evidence_derived_created(
        conn,
        payload=_a1_derived_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    e2 = emit_evidence_derived_created(
        conn,
        payload=_a1_derived_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert e1.event_id != e2.event_id


def test_emit_derived_aggregate_id_equals_derived_evidence_id(
    conn: psycopg.Connection,
) -> None:
    """
    evidence.* convention: aggregate_id IS the derived_evidence_id.
    The emitter must wire this automatically.
    """
    payload = _a1_derived_payload()
    event = emit_evidence_derived_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )
    assert event.aggregate_id == payload.derived_evidence_id


def test_emit_derived_subject_entity_id_can_be_null(
    conn: psycopg.Connection,
) -> None:
    payload = _a1_derived_payload(subject_entity_id=None)
    event = emit_evidence_derived_created(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["subject_entity_id"] is None


def test_emit_derived_timestamps_are_utc(conn: psycopg.Connection) -> None:
    event = emit_evidence_derived_created(
        conn,
        payload=_a1_derived_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.occurred_at.tzinfo is not None
    assert event.recorded_at.tzinfo is not None


def test_emit_derived_causation_and_correlation_round_trip(
    conn: psycopg.Connection,
) -> None:
    """
    Optional causation_id / correlation_id are emitter-supplied and
    persisted as their own UUID columns; both must survive INSERT → SELECT.
    """
    causation_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    event = emit_evidence_derived_created(
        conn,
        payload=_a1_derived_payload(),
        actor_type="analyst",
        actor_id="andrew",
        causation_id=causation_id,
        correlation_id=correlation_id,
    )

    assert event.causation_id == causation_id
    assert event.correlation_id == correlation_id

    with conn.cursor() as cur:
        cur.execute(
            "SELECT causation_id, correlation_id "
            "FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == causation_id
    assert row[1] == correlation_id


def test_event_constructs_derived_payload_from_plain_dict() -> None:
    """
    Plain-Union resolution must materialize an EvidenceDerivedCreatedPayload
    when the payload is supplied as a plain dict (simulating replay-time
    reconstruction from a JSONB row).
    """
    derived_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    parent_ids = [uuid.uuid4(), uuid.uuid4()]
    derived_at = datetime.now(timezone.utc)
    payload_dict = {
        "derived_evidence_id": str(derived_id),
        "subject_entity_id": str(subject_id),
        "parent_evidence_ids": [str(p) for p in parent_ids],
        "derivation_type": "claim_extraction",
        "derivation_version": "extractor-v2.1.0",
        "output_payload": {"claims": ["a", "b"], "score": 0.7},
        "derived_at_for_projection": derived_at.isoformat(),
    }
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.derived_created",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=derived_id,
        payload=payload_dict,  # type: ignore[arg-type]
        schema_version=EVIDENCE_DERIVED_CREATED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(event.payload, EvidenceDerivedCreatedPayload)
    assert event.payload.derived_evidence_id == derived_id
    assert event.payload.subject_entity_id == subject_id
    assert event.payload.parent_evidence_ids == parent_ids
    assert event.payload.derivation_type == "claim_extraction"
    assert event.payload.derivation_version == "extractor-v2.1.0"
    assert event.payload.output_payload == {"claims": ["a", "b"], "score": 0.7}
