"""
tests/test_compliance_state_emitter.py

Day-1 Step 11 verification. Two layers, mirroring the Step 10 shape for
the new compliance.state_asserted event type.

    1. Pure model validation (no DB):
       - ComplianceStateAssertedPayload accepts a valid construction.
       - extra="forbid" rejects unknown fields.
       - min_length=1 rejects empty policy_id / policy_version.
       - parent_derived_evidence_ids is non-empty (min_length=1);
         empty list is REJECTED per Step-11 doctrine.
       - compliance_state_id required (UUID).
       - subject_entity_id optional (UUID | None).
       - assertion is dict[str, Any]; required (may be empty dict).
       - frozen=True (immutable post-construction).
       - The EventType discriminator includes "compliance.state_asserted".
       - Event envelope's payload Union accepts the new payload type
         AND still accepts the existing three.
       - The Event aggregate-invariant validator covers
         compliance.state_asserted (happy + mismatch).

    2. Single-transaction emit against the live substrate
       (rollback-isolated):
       - emit_compliance_state_asserted lands one row in events with the
         expected shape and aggregate_type = "compliance".
       - Payload round-trips via JSONB, including
         parent_derived_evidence_ids as an ORDERED JSON array,
         policy_version verbatim, and assertion verbatim with sort_keys-
         stable key ordering.
       - Each emit gets a fresh event_id.
       - aggregate_id equals payload.compliance_state_id.
       - subject_entity_id may be NULL.
       - causation_id / correlation_id round-trip exactly.
       - parent_derived_evidence_ids ORDER survives the JSONB round-trip.
       - Construction from a plain dict (replay path simulation) resolves
         to ComplianceStateAssertedPayload via plain-Union dispatch.

DOCTRINE (Day-1 Step 11):
    Tests treat compliance_state assertions as REPLAYABLE HISTORICAL
    INTERPRETATIONS made under a specific policy_version and evidence
    context — NOT canonical objective truth. The substrate records and
    replays the assertion bytes verbatim; the substrate does NOT
    re-evaluate policy at emit, project, or replay time.
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
    COMPLIANCE_STATE_ASSERTED_SCHEMA_VERSION,
    emit_compliance_state_asserted,
)
from app.events.models import (
    AGGREGATE_TYPE_COMPLIANCE,
    ComplianceStateAssertedPayload,
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
# Canonical synthetic A1 compliance assertion (Step-11 fixture)
# ---------------------------------------------------------------------------


def _a1_compliance_payload(
    *,
    subject_entity_id: uuid.UUID | None = None,
    parent_derived_evidence_ids: list[uuid.UUID] | None = None,
    policy_id: str = "us_dnc_v1",
    policy_version: str = "1.0.0",
    assertion: dict[str, typing.Any] | None = None,
) -> ComplianceStateAssertedPayload:
    """
    Build a fresh synthetic A1 Garage Doors compliance-state-asserted
    payload. Parent derived-evidence IDs default to a fixed two-element
    list (order matters for the order-preservation tests). assertion
    defaults to a representative non-compliant DNC verdict.
    """
    if parent_derived_evidence_ids is None:
        parent_derived_evidence_ids = [uuid.uuid4(), uuid.uuid4()]
    if assertion is None:
        assertion = {
            "compliant": False,
            "blocker": "phone_on_dnc_list",
            "confidence": 0.92,
        }
    return ComplianceStateAssertedPayload(
        compliance_state_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        parent_derived_evidence_ids=parent_derived_evidence_ids,
        policy_id=policy_id,
        policy_version=policy_version,
        assertion=assertion,
        asserted_at_for_projection=datetime.now(timezone.utc),
    )


# ===========================================================================
# Layer 1 — Pure model validation
# ===========================================================================


def test_compliance_payload_accepts_valid_construction() -> None:
    payload = _a1_compliance_payload()
    assert isinstance(payload.compliance_state_id, uuid.UUID)
    assert payload.subject_entity_id is None
    assert len(payload.parent_derived_evidence_ids) == 2
    assert payload.policy_id == "us_dnc_v1"
    assert payload.policy_version == "1.0.0"
    assert payload.assertion["compliant"] is False
    assert payload.asserted_at_for_projection.tzinfo is not None


def test_compliance_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ComplianceStateAssertedPayload(
            compliance_state_id=uuid.uuid4(),
            parent_derived_evidence_ids=[uuid.uuid4()],
            policy_id="us_dnc_v1",
            policy_version="1.0.0",
            assertion={},
            asserted_at_for_projection=datetime.now(timezone.utc),
            unexpected_field="boom",  # type: ignore[call-arg]
        )


def test_compliance_payload_rejects_empty_policy_id() -> None:
    with pytest.raises(ValidationError):
        ComplianceStateAssertedPayload(
            compliance_state_id=uuid.uuid4(),
            parent_derived_evidence_ids=[uuid.uuid4()],
            policy_id="",
            policy_version="1.0.0",
            assertion={},
            asserted_at_for_projection=datetime.now(timezone.utc),
        )


def test_compliance_payload_rejects_empty_policy_version() -> None:
    with pytest.raises(ValidationError):
        ComplianceStateAssertedPayload(
            compliance_state_id=uuid.uuid4(),
            parent_derived_evidence_ids=[uuid.uuid4()],
            policy_id="us_dnc_v1",
            policy_version="",
            assertion={},
            asserted_at_for_projection=datetime.now(timezone.utc),
        )


def test_compliance_payload_rejects_empty_parent_derived_evidence_ids() -> None:
    """
    Empty parent_derived_evidence_ids is REJECTED per Step-11 substrate
    doctrine: compliance assertions must be grounded in at least one
    derived-evidence parent. Enforced at the Pydantic layer via
    min_length=1.
    """
    with pytest.raises(ValidationError):
        ComplianceStateAssertedPayload(
            compliance_state_id=uuid.uuid4(),
            parent_derived_evidence_ids=[],
            policy_id="us_dnc_v1",
            policy_version="1.0.0",
            assertion={},
            asserted_at_for_projection=datetime.now(timezone.utc),
        )


def test_compliance_payload_accepts_optional_subject_entity_id() -> None:
    """subject_entity_id is optional (UUID | None) — DNC-before-entity."""
    p1 = _a1_compliance_payload(subject_entity_id=None)
    assert p1.subject_entity_id is None

    entity_id = uuid.uuid4()
    p2 = _a1_compliance_payload(subject_entity_id=entity_id)
    assert p2.subject_entity_id == entity_id


def test_compliance_payload_assertion_accepts_empty_dict() -> None:
    """assertion may be an empty dict at this layer."""
    payload = _a1_compliance_payload(assertion={})
    assert payload.assertion == {}


def test_compliance_payload_is_frozen() -> None:
    """frozen=True makes the payload immutable post-construction."""
    payload = _a1_compliance_payload()
    with pytest.raises(ValidationError):
        payload.policy_id = "gdpr_consent"  # type: ignore[misc]


def test_event_type_literal_includes_compliance_state_asserted() -> None:
    """The EventType discriminator was widened in Step 11."""
    args = typing.get_args(EventType)
    assert "entity.created" in args
    assert "evidence.raw_ingested" in args
    assert "evidence.derived_created" in args
    assert "compliance.state_asserted" in args


def test_event_envelope_accepts_compliance_payload() -> None:
    """The Event Union now includes ComplianceStateAssertedPayload."""
    payload = _a1_compliance_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="compliance.state_asserted",
        aggregate_type=AGGREGATE_TYPE_COMPLIANCE,
        aggregate_id=payload.compliance_state_id,
        payload=payload,
        schema_version=COMPLIANCE_STATE_ASSERTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(event.payload, ComplianceStateAssertedPayload)
    assert event.aggregate_type == "compliance"


def test_event_envelope_still_accepts_entity_raw_and_derived_payloads() -> None:
    """Widening the Union must NOT regress the existing payload paths."""
    now = datetime.now(timezone.utc)

    entity_payload = EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=now,
    )
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
        observed_at_for_projection=now,
    )
    e2 = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.raw_ingested",
        aggregate_type="evidence",
        aggregate_id=raw_payload.evidence_id,
        payload=raw_payload,
        schema_version="1.0.0",
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(e2.payload, EvidenceRawIngestedPayload)

    derived_payload = EvidenceDerivedCreatedPayload(
        derived_evidence_id=uuid.uuid4(),
        parent_evidence_ids=[uuid.uuid4()],
        derivation_type="summary_extraction",
        derivation_version="summarizer-v1.0.0",
        output_payload={"summary": "x"},
        derived_at_for_projection=now,
    )
    e3 = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.derived_created",
        aggregate_type="evidence",
        aggregate_id=derived_payload.derived_evidence_id,
        payload=derived_payload,
        schema_version="1.0.0",
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(e3.payload, EvidenceDerivedCreatedPayload)


def test_event_validator_accepts_matching_compliance_aggregate_id() -> None:
    """Happy path for compliance.state_asserted envelope."""
    payload = _a1_compliance_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="compliance.state_asserted",
        aggregate_type=AGGREGATE_TYPE_COMPLIANCE,
        aggregate_id=payload.compliance_state_id,
        payload=payload,
        schema_version=COMPLIANCE_STATE_ASSERTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.aggregate_id == payload.compliance_state_id


def test_event_validator_rejects_mismatched_compliance_aggregate_id() -> None:
    """Misaligned compliance envelope: aggregate_id != compliance_state_id raises."""
    payload = _a1_compliance_payload()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError) as excinfo:
        Event(
            event_id=uuid.uuid4(),
            event_type="compliance.state_asserted",
            aggregate_type=AGGREGATE_TYPE_COMPLIANCE,
            aggregate_id=uuid.uuid4(),  # NOT payload.compliance_state_id
            payload=payload,
            schema_version=COMPLIANCE_STATE_ASSERTED_SCHEMA_VERSION,
            occurred_at=now,
            recorded_at=now,
            actor_type="analyst",
            actor_id="andrew",
        )
    assert "aggregate_id" in str(excinfo.value)
    assert "compliance_state_id" in str(excinfo.value)


# ===========================================================================
# Layer 2 — Single-transaction emit (rollback-isolated)
# ===========================================================================


def test_emit_compliance_inserts_event_row(conn: psycopg.Connection) -> None:
    """
    Canonical Step-11 emit: synthetic A1 Garage Doors compliance assertion.
    After emit, the row must be readable inside the same transaction with
    the expected shape.
    """
    payload = _a1_compliance_payload()
    event = emit_compliance_state_asserted(
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
    assert row[1] == "compliance.state_asserted"
    assert row[2] == AGGREGATE_TYPE_COMPLIANCE
    assert row[3] == payload.compliance_state_id
    assert row[4] == COMPLIANCE_STATE_ASSERTED_SCHEMA_VERSION
    assert row[5] == "analyst"
    assert row[6] == "andrew"


def test_emit_compliance_payload_round_trips_via_jsonb(
    conn: psycopg.Connection,
) -> None:
    """
    All payload fields (incl. parent_derived_evidence_ids list,
    policy_version, and assertion dict) survive the JSON serialize →
    JSONB store → JSON parse round-trip.
    """
    entity_id = uuid.uuid4()
    parent_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    payload = _a1_compliance_payload(
        subject_entity_id=entity_id,
        parent_derived_evidence_ids=parent_ids,
        policy_version="2024-Q1",
        assertion={"compliant": True, "verdict": "consent_on_file"},
    )
    event = emit_compliance_state_asserted(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["compliance_state_id"] == str(payload.compliance_state_id)
    assert stored["subject_entity_id"] == str(entity_id)
    assert stored["policy_id"] == "us_dnc_v1"
    assert stored["policy_version"] == "2024-Q1"
    assert stored["assertion"] == {"compliant": True, "verdict": "consent_on_file"}
    assert stored["parent_derived_evidence_ids"] == [str(p) for p in parent_ids]
    assert isinstance(stored["asserted_at_for_projection"], str)
    assert "T" in stored["asserted_at_for_projection"]


def test_emit_compliance_parent_ids_order_preserved_in_event_payload(
    conn: psycopg.Connection,
) -> None:
    """
    parent_derived_evidence_ids ORDER must survive the JSONB round-trip
    end-to-end: Python list[UUID] → model_dump(mode='json') list[str] →
    json.dumps (stable) → JSONB → psycopg JSONB→list[str] → expected
    order.
    """
    parents_in = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    payload = _a1_compliance_payload(parent_derived_evidence_ids=parents_in)
    event = emit_compliance_state_asserted(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload->'parent_derived_evidence_ids' "
            "FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored_list = cur.fetchone()[0]

    expected = [str(p) for p in parents_in]
    assert stored_list == expected, (
        "parent_derived_evidence_ids order was not preserved through the "
        f"event payload JSONB round-trip. expected={expected}, got={stored_list}"
    )


def test_emit_compliance_generates_distinct_event_ids(
    conn: psycopg.Connection,
) -> None:
    e1 = emit_compliance_state_asserted(
        conn,
        payload=_a1_compliance_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    e2 = emit_compliance_state_asserted(
        conn,
        payload=_a1_compliance_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert e1.event_id != e2.event_id


def test_emit_compliance_aggregate_id_equals_compliance_state_id(
    conn: psycopg.Connection,
) -> None:
    """
    compliance.* convention: aggregate_id IS the compliance_state_id.
    The emitter must wire this automatically.
    """
    payload = _a1_compliance_payload()
    event = emit_compliance_state_asserted(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )
    assert event.aggregate_id == payload.compliance_state_id


def test_emit_compliance_subject_entity_id_can_be_null(
    conn: psycopg.Connection,
) -> None:
    payload = _a1_compliance_payload(subject_entity_id=None)
    event = emit_compliance_state_asserted(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["subject_entity_id"] is None


def test_emit_compliance_timestamps_are_utc(conn: psycopg.Connection) -> None:
    event = emit_compliance_state_asserted(
        conn,
        payload=_a1_compliance_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.occurred_at.tzinfo is not None
    assert event.recorded_at.tzinfo is not None


def test_emit_compliance_causation_and_correlation_round_trip(
    conn: psycopg.Connection,
) -> None:
    """
    Optional causation_id / correlation_id are emitter-supplied and
    persisted as their own UUID columns; both must survive INSERT →
    SELECT.
    """
    causation_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    event = emit_compliance_state_asserted(
        conn,
        payload=_a1_compliance_payload(),
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


def test_event_constructs_compliance_payload_from_plain_dict() -> None:
    """
    Plain-Union resolution must materialize a ComplianceStateAssertedPayload
    when the payload is supplied as a plain dict (simulating replay-time
    reconstruction from a JSONB row).
    """
    compliance_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    parent_ids = [uuid.uuid4(), uuid.uuid4()]
    asserted_at = datetime.now(timezone.utc)
    payload_dict = {
        "compliance_state_id": str(compliance_id),
        "subject_entity_id": str(subject_id),
        "parent_derived_evidence_ids": [str(p) for p in parent_ids],
        "policy_id": "gdpr_consent",
        "policy_version": "2024-Q1",
        "assertion": {"compliant": True, "lawful_basis": "consent"},
        "asserted_at_for_projection": asserted_at.isoformat(),
    }
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="compliance.state_asserted",
        aggregate_type=AGGREGATE_TYPE_COMPLIANCE,
        aggregate_id=compliance_id,
        payload=payload_dict,  # type: ignore[arg-type]
        schema_version=COMPLIANCE_STATE_ASSERTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(event.payload, ComplianceStateAssertedPayload)
    assert event.payload.compliance_state_id == compliance_id
    assert event.payload.subject_entity_id == subject_id
    assert event.payload.parent_derived_evidence_ids == parent_ids
    assert event.payload.policy_id == "gdpr_consent"
    assert event.payload.policy_version == "2024-Q1"
    assert event.payload.assertion == {"compliant": True, "lawful_basis": "consent"}
