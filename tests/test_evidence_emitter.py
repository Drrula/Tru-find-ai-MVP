"""
tests/test_evidence_emitter.py

Day-1 Step 8 verification. Two layers, mirroring the Step 4 shape for the
new evidence aggregate type.

    1. Pure model validation (no DB):
       - EvidenceRawIngestedPayload accepts a valid construction.
       - extra="forbid" rejects unknown fields (Mistake #8 prevention).
       - min_length=1 rejects empty source_uri / source_type / storage_uri.
       - content_hash must be exactly 64 lowercase hex characters.
       - subject_entity_id is optional (UUID | None).
       - metadata defaults to {} and only accepts str→str.
       - The EventType discriminator now includes "evidence.raw_ingested".
       - The Event envelope round-trips an EvidenceRawIngestedPayload.

    2. Single-transaction emit against the live substrate (rollback-isolated):
       - emit_evidence_raw_ingested lands one row in events with the
         expected shape and aggregate_type = "evidence".
       - Payload (including metadata dict) round-trips through JSONB.
       - Each emit generates a fresh event_id.
       - aggregate_id equals payload.evidence_id (evidence.* convention).
       - subject_entity_id may be NULL.
       - Both occurred_at and recorded_at are timezone-aware UTC.

Scope discipline:
    - Tests interact ONLY with the events table and the emitter. No
      evidence projection (none exists yet — Step 9+). No replay engine.
    - Canonical test context: a synthetic "website fetch" evidence record
      for A1 Garage Doors. The raw bytes are NOT stored in the payload;
      `storage_uri` references a hypothetical external blob.
"""

from __future__ import annotations

import hashlib
import os
import typing
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from pydantic import ValidationError

from app.db import connection as db
from app.events.emitter import (
    EVIDENCE_RAW_INGESTED_SCHEMA_VERSION,
    emit_evidence_raw_ingested,
)
from app.events.models import (
    AGGREGATE_TYPE_EVIDENCE,
    EntityCreatedPayload,
    Event,
    EventType,
    EvidenceRawIngestedPayload,
)


# ---------------------------------------------------------------------------
# Fixtures (rollback-isolated, same pattern as test_events_emitter.py)
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
# Canonical Step-8 evidence target — synthetic A1 Garage Doors website fetch
# ---------------------------------------------------------------------------

_A1_SYNTHETIC_CONTENT: bytes = (
    b"<html><body>A1 Garage Doors - synthetic Step-8 fixture</body></html>"
)


def _a1_content_hash() -> str:
    """Deterministic SHA-256 of the synthetic A1 page content."""
    return hashlib.sha256(_A1_SYNTHETIC_CONTENT).hexdigest()


def _a1_evidence_payload(
    *, subject_entity_id: uuid.UUID | None = None
) -> EvidenceRawIngestedPayload:
    """
    Build a fresh EvidenceRawIngestedPayload for a synthetic A1 Garage
    Doors website fetch. Storage URI references a hypothetical bucket;
    no real storage is touched.
    """
    return EvidenceRawIngestedPayload(
        evidence_id=uuid.uuid4(),
        subject_entity_id=subject_entity_id,
        source_uri="https://example.invalid/a1-garage-doors",
        source_type="website_fetch",
        content_hash=_a1_content_hash(),
        storage_uri="s3://substrate-evidence/synthetic/a1-garage-doors.html",
        observed_at_for_projection=datetime.now(timezone.utc),
        metadata={"http_status": "200", "vertical": "GARAGE_DOOR"},
    )


# ===========================================================================
# Layer 1 — Pure model validation
# ===========================================================================


def test_evidence_payload_accepts_valid_construction() -> None:
    payload = _a1_evidence_payload()
    assert isinstance(payload.evidence_id, uuid.UUID)
    assert payload.subject_entity_id is None
    assert payload.source_uri.startswith("https://")
    assert payload.source_type == "website_fetch"
    assert len(payload.content_hash) == 64
    assert payload.storage_uri.startswith("s3://")
    assert payload.observed_at_for_projection.tzinfo is not None
    assert payload.metadata == {"http_status": "200", "vertical": "GARAGE_DOOR"}


def test_evidence_payload_rejects_unknown_fields() -> None:
    """extra='forbid' guards against silent payload drift (Mistake #8)."""
    with pytest.raises(ValidationError):
        EvidenceRawIngestedPayload(
            evidence_id=uuid.uuid4(),
            source_uri="https://example.invalid/x",
            source_type="website_fetch",
            content_hash=_a1_content_hash(),
            storage_uri="s3://b/x",
            observed_at_for_projection=datetime.now(timezone.utc),
            unexpected_field="this should fail",  # type: ignore[call-arg]
        )


def test_evidence_payload_rejects_empty_source_uri() -> None:
    with pytest.raises(ValidationError):
        EvidenceRawIngestedPayload(
            evidence_id=uuid.uuid4(),
            source_uri="",
            source_type="website_fetch",
            content_hash=_a1_content_hash(),
            storage_uri="s3://b/x",
            observed_at_for_projection=datetime.now(timezone.utc),
        )


def test_evidence_payload_rejects_empty_source_type() -> None:
    with pytest.raises(ValidationError):
        EvidenceRawIngestedPayload(
            evidence_id=uuid.uuid4(),
            source_uri="https://example.invalid/x",
            source_type="",
            content_hash=_a1_content_hash(),
            storage_uri="s3://b/x",
            observed_at_for_projection=datetime.now(timezone.utc),
        )


def test_evidence_payload_rejects_empty_storage_uri() -> None:
    with pytest.raises(ValidationError):
        EvidenceRawIngestedPayload(
            evidence_id=uuid.uuid4(),
            source_uri="https://example.invalid/x",
            source_type="website_fetch",
            content_hash=_a1_content_hash(),
            storage_uri="",
            observed_at_for_projection=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize(
    "bad_hash",
    [
        "",                                        # empty
        "abc",                                     # too short
        "a" * 63,                                  # one short
        "a" * 65,                                  # one long
        "A" * 64,                                  # uppercase
        "G" * 64,                                  # non-hex char
        _a1_content_hash().upper(),                # uppercase variant of valid hash
        _a1_content_hash() + "0",                  # extra char appended
    ],
)
def test_evidence_payload_rejects_malformed_content_hash(bad_hash: str) -> None:
    """content_hash must be exactly 64 lowercase hex characters."""
    with pytest.raises(ValidationError):
        EvidenceRawIngestedPayload(
            evidence_id=uuid.uuid4(),
            source_uri="https://example.invalid/x",
            source_type="website_fetch",
            content_hash=bad_hash,
            storage_uri="s3://b/x",
            observed_at_for_projection=datetime.now(timezone.utc),
        )


def test_evidence_payload_accepts_none_subject_entity_id() -> None:
    """subject_entity_id is optional — evidence may exist before its entity."""
    payload = _a1_evidence_payload(subject_entity_id=None)
    assert payload.subject_entity_id is None


def test_evidence_payload_accepts_set_subject_entity_id() -> None:
    """When the entity is known, subject_entity_id carries the link."""
    entity_id = uuid.uuid4()
    payload = _a1_evidence_payload(subject_entity_id=entity_id)
    assert payload.subject_entity_id == entity_id


def test_evidence_payload_metadata_defaults_to_empty_dict() -> None:
    payload = EvidenceRawIngestedPayload(
        evidence_id=uuid.uuid4(),
        source_uri="https://example.invalid/x",
        source_type="website_fetch",
        content_hash=_a1_content_hash(),
        storage_uri="s3://b/x",
        observed_at_for_projection=datetime.now(timezone.utc),
    )
    assert payload.metadata == {}


def test_evidence_payload_metadata_rejects_non_string_values() -> None:
    """metadata is dict[str, str]; ints, lists, dicts as values are rejected."""
    with pytest.raises(ValidationError):
        EvidenceRawIngestedPayload(
            evidence_id=uuid.uuid4(),
            source_uri="https://example.invalid/x",
            source_type="website_fetch",
            content_hash=_a1_content_hash(),
            storage_uri="s3://b/x",
            observed_at_for_projection=datetime.now(timezone.utc),
            metadata={"http_status": 200},  # type: ignore[dict-item]
        )


def test_evidence_payload_is_frozen() -> None:
    """frozen=True makes payloads immutable post-construction."""
    payload = _a1_evidence_payload()
    with pytest.raises(ValidationError):
        payload.source_type = "manual_analyst_note"  # type: ignore[misc]


def test_event_type_literal_includes_evidence_raw_ingested() -> None:
    """The EventType discriminator was widened in Step 8."""
    args = typing.get_args(EventType)
    assert "entity.created" in args
    assert "evidence.raw_ingested" in args


def test_event_envelope_accepts_evidence_payload() -> None:
    """The Event envelope's payload union now includes EvidenceRawIngestedPayload."""
    payload = _a1_evidence_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.raw_ingested",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=payload.evidence_id,
        payload=payload,
        schema_version=EVIDENCE_RAW_INGESTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(event.payload, EvidenceRawIngestedPayload)
    assert event.aggregate_type == "evidence"


def test_event_envelope_still_accepts_entity_created_payload() -> None:
    """
    Widening Event.payload to a Union must NOT regress the existing
    EntityCreatedPayload path. Belt-and-suspenders check.
    """
    entity_payload = EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=datetime.now(timezone.utc),
    )
    now = datetime.now(timezone.utc)
    event = Event(
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
    assert isinstance(event.payload, EntityCreatedPayload)


# ===========================================================================
# Layer 2 — Single-transaction emit (rollback-isolated)
# ===========================================================================


def test_emit_evidence_raw_ingested_inserts_event_row(
    conn: psycopg.Connection,
) -> None:
    """
    Canonical Step-8 emit: synthetic A1 Garage Doors website-fetch evidence,
    not linked to an entity (subject_entity_id=None). After emit, the row
    must be readable inside the same transaction with the expected shape.
    """
    payload = _a1_evidence_payload()
    event = emit_evidence_raw_ingested(
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
    assert row[1] == "evidence.raw_ingested"
    assert row[2] == AGGREGATE_TYPE_EVIDENCE
    assert row[3] == payload.evidence_id
    assert row[4] == EVIDENCE_RAW_INGESTED_SCHEMA_VERSION
    assert row[5] == "analyst"
    assert row[6] == "andrew"


def test_emit_evidence_payload_round_trips_via_jsonb(
    conn: psycopg.Connection,
) -> None:
    """
    All payload fields (including the metadata dict) survive the JSON
    serialize → JSONB store → JSON parse round-trip.
    """
    entity_id = uuid.uuid4()
    payload = _a1_evidence_payload(subject_entity_id=entity_id)
    event = emit_evidence_raw_ingested(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["evidence_id"] == str(payload.evidence_id)
    assert stored["subject_entity_id"] == str(entity_id)
    assert stored["source_uri"] == "https://example.invalid/a1-garage-doors"
    assert stored["source_type"] == "website_fetch"
    assert stored["content_hash"] == _a1_content_hash()
    assert stored["storage_uri"] == (
        "s3://substrate-evidence/synthetic/a1-garage-doors.html"
    )
    assert stored["metadata"] == {
        "http_status": "200",
        "vertical": "GARAGE_DOOR",
    }
    assert isinstance(stored["observed_at_for_projection"], str)
    assert "T" in stored["observed_at_for_projection"]


def test_emit_evidence_generates_distinct_event_ids(
    conn: psycopg.Connection,
) -> None:
    """Each emit gets a fresh UUID."""
    e1 = emit_evidence_raw_ingested(
        conn,
        payload=_a1_evidence_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    e2 = emit_evidence_raw_ingested(
        conn,
        payload=_a1_evidence_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert e1.event_id != e2.event_id


def test_emit_evidence_aggregate_id_equals_evidence_id(
    conn: psycopg.Connection,
) -> None:
    """
    evidence.* convention: aggregate_id IS the evidence's evidence_id.
    The emitter must wire this automatically.
    """
    payload = _a1_evidence_payload()
    event = emit_evidence_raw_ingested(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )
    assert event.aggregate_id == payload.evidence_id


def test_emit_evidence_subject_entity_id_can_be_null(
    conn: psycopg.Connection,
) -> None:
    """
    Evidence captured before entity creation: subject_entity_id is None
    in the payload and stored as JSON null in JSONB. Round-trip preserved.
    """
    payload = _a1_evidence_payload(subject_entity_id=None)
    event = emit_evidence_raw_ingested(
        conn, payload=payload, actor_type="analyst", actor_id="andrew",
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM events WHERE event_id = %s",
            (event.event_id,),
        )
        stored = cur.fetchone()[0]

    assert stored["subject_entity_id"] is None


def test_emit_evidence_timestamps_are_utc(conn: psycopg.Connection) -> None:
    event = emit_evidence_raw_ingested(
        conn,
        payload=_a1_evidence_payload(),
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.occurred_at.tzinfo is not None
    assert event.recorded_at.tzinfo is not None


def test_emit_evidence_causation_and_correlation_round_trip(
    conn: psycopg.Connection,
) -> None:
    """
    The optional causation_id / correlation_id are emitter-supplied and
    persisted as their own UUID columns on the events row. Both must
    survive the INSERT → SELECT round-trip exactly.
    """
    causation_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    event = emit_evidence_raw_ingested(
        conn,
        payload=_a1_evidence_payload(),
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


# ===========================================================================
# Step-8 hardening — Event-level aggregate-invariant validator
# ===========================================================================


def test_event_validator_accepts_matching_entity_aggregate_id() -> None:
    """
    Happy path: when aggregate_id == payload.entity_id, the entity.created
    envelope constructs cleanly.
    """
    entity_payload = EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=datetime.now(timezone.utc),
    )
    now = datetime.now(timezone.utc)
    event = Event(
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
    assert event.aggregate_id == entity_payload.entity_id


def test_event_validator_rejects_mismatched_entity_aggregate_id() -> None:
    """
    Misaligned envelope: aggregate_id != payload.entity_id must raise at
    construction time. Replay can never resurrect a misaligned event.
    """
    entity_payload = EntityCreatedPayload(
        entity_id=uuid.uuid4(),
        name="A1 Garage Doors",
        vertical="GARAGE_DOOR",
        created_at_for_projection=datetime.now(timezone.utc),
    )
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError) as excinfo:
        Event(
            event_id=uuid.uuid4(),
            event_type="entity.created",
            aggregate_type="entity",
            aggregate_id=uuid.uuid4(),  # NOT entity_payload.entity_id
            payload=entity_payload,
            schema_version="1.0.0",
            occurred_at=now,
            recorded_at=now,
            actor_type="analyst",
            actor_id="andrew",
        )
    assert "aggregate_id" in str(excinfo.value)
    assert "payload.entity_id" in str(excinfo.value)


def test_event_validator_accepts_matching_evidence_aggregate_id() -> None:
    """Happy path for evidence.raw_ingested envelope."""
    evidence_payload = _a1_evidence_payload()
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.raw_ingested",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=evidence_payload.evidence_id,
        payload=evidence_payload,
        schema_version=EVIDENCE_RAW_INGESTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert event.aggregate_id == evidence_payload.evidence_id


def test_event_validator_rejects_mismatched_evidence_aggregate_id() -> None:
    """
    Misaligned evidence envelope: aggregate_id != payload.evidence_id
    must raise at construction time.
    """
    evidence_payload = _a1_evidence_payload()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError) as excinfo:
        Event(
            event_id=uuid.uuid4(),
            event_type="evidence.raw_ingested",
            aggregate_type=AGGREGATE_TYPE_EVIDENCE,
            aggregate_id=uuid.uuid4(),  # NOT evidence_payload.evidence_id
            payload=evidence_payload,
            schema_version=EVIDENCE_RAW_INGESTED_SCHEMA_VERSION,
            occurred_at=now,
            recorded_at=now,
            actor_type="analyst",
            actor_id="andrew",
        )
    assert "aggregate_id" in str(excinfo.value)
    assert "payload.evidence_id" in str(excinfo.value)


# ===========================================================================
# Step-8 hardening — Union deserialization from plain dict input
# ===========================================================================


def test_event_constructs_evidence_payload_from_plain_dict() -> None:
    """
    Pydantic's plain-Union resolution must correctly materialize an
    EvidenceRawIngestedPayload when the payload is supplied as a plain
    dict (as it would be on replay from a JSONB row). This is the
    contract that lets future replay code reconstruct an Event without
    knowing the payload type in advance — the Union resolution picks
    EvidenceRawIngestedPayload over EntityCreatedPayload via disjoint
    required-field-set matching.

    When the substrate ever needs a Pydantic discriminator field on the
    payload, this test pins the current behavior so the refactor stays
    backward-compatible at the dict-input boundary.
    """
    evidence_id = uuid.uuid4()
    subject_entity_id = uuid.uuid4()
    observed_at = datetime.now(timezone.utc)
    payload_dict = {
        "evidence_id": str(evidence_id),
        "subject_entity_id": str(subject_entity_id),
        "source_uri": "https://example.invalid/a1-garage-doors",
        "source_type": "website_fetch",
        "content_hash": _a1_content_hash(),
        "storage_uri": "s3://substrate-evidence/synthetic/a1-garage-doors.html",
        "observed_at_for_projection": observed_at.isoformat(),
        "metadata": {"http_status": "200", "vertical": "GARAGE_DOOR"},
    }
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=uuid.uuid4(),
        event_type="evidence.raw_ingested",
        aggregate_type=AGGREGATE_TYPE_EVIDENCE,
        aggregate_id=evidence_id,
        payload=payload_dict,  # type: ignore[arg-type]
        schema_version=EVIDENCE_RAW_INGESTED_SCHEMA_VERSION,
        occurred_at=now,
        recorded_at=now,
        actor_type="analyst",
        actor_id="andrew",
    )
    assert isinstance(event.payload, EvidenceRawIngestedPayload)
    assert event.payload.evidence_id == evidence_id
    assert event.payload.subject_entity_id == subject_entity_id
    assert event.payload.source_type == "website_fetch"
    assert event.payload.content_hash == _a1_content_hash()
    assert event.payload.metadata == {
        "http_status": "200",
        "vertical": "GARAGE_DOOR",
    }
