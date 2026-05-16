"""
app.events.models — TruSignalAI Phase 0 event-model foundation.

Pydantic v2 models for the canonical append-only event log.

Scope:
    - Day-1 Step 4 introduced `entity.created` + EntityCreatedPayload.
    - Day-1 Step 8 introduced `evidence.raw_ingested` + EvidenceRawIngestedPayload.
      Blueprint §8 lists eight remaining minimum event types
      (entity.attribute_set, entity.domain_registered, ontology.version_loaded,
      engine.version_loaded, evidence.derived_created, indicator.observed,
      indicator.analyst_set, scoring.run_completed); those land in later
      days as their respective work surfaces are authorized.
    - No projector logic, no replay logic, no DB I/O. Pure data structures.

Replay-determinism contract (Phase_0_Governance_and_Replayability.md Part B):
    - All UUIDs and timestamps in the event envelope come from the emitter
      side and are persisted in the events table; the projector (Day-1
      Step 5) reads them back, never re-derives them. This module enforces
      that contract structurally — every UUID/datetime field is REQUIRED;
      no `default_factory=uuid.uuid4` or `default_factory=datetime.now`
      conveniences are used. The emitter must supply them explicitly.

Locked references:
    - Phase_0_Execution_Blueprint.md §7  (events table column set)
    - Phase_0_Execution_Blueprint.md §8  (initial event-type taxonomy)
    - Phase_0_Governance_and_Replayability.md Part B  (replay-determinism)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Event-type literal
# ---------------------------------------------------------------------------

EventType = Literal["entity.created", "evidence.raw_ingested"]
"""
Phase 0 event-type discriminator. Day-1 Step 4 introduced `entity.created`;
Day-1 Step 8 added `evidence.raw_ingested`. Subsequent days extend this
toward the full Blueprint §8 minimum set.
"""


# ---------------------------------------------------------------------------
# Aggregate-type constants
# ---------------------------------------------------------------------------

AGGREGATE_TYPE_ENTITY: str = "entity"
"""
Aggregate type for entity.* events. The aggregate_id of an entity.created
event is the entity_id itself (by convention enforced in the emitter).
"""

AGGREGATE_TYPE_EVIDENCE: str = "evidence"
"""
Aggregate type for evidence.* events. The aggregate_id of an
evidence.raw_ingested event is the evidence_id itself (by convention
enforced in the emitter). Each evidence record is its own aggregate;
linkage to an entity is carried as `subject_entity_id` in the payload,
not as aggregate-graph membership.
"""


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class EntityCreatedPayload(BaseModel):
    """
    Payload for `entity.created` events.

    Fields per the CURRENT_STATE_BRIEF.md Day-1 spec:
        entity_id — stable UUID for the entity. Distinct from the envelope's
                    event_id; the same entity may emit many events over time
                    but only one entity.created.
        name      — display name (e.g., "A1 Garage Doors").
        vertical  — vertical code from the locked ontology release
                    (e.g., "GARAGE_DOOR", "DENTAL_DSO"). Validated as a
                    non-empty string only at this layer; cross-reference
                    against the ontology release happens at observation /
                    scoring time, not at entity-creation time, to keep
                    the substrate emit path free of cross-module reads.
        created_at_for_projection — logical creation time. The Day-1 Step 5
                    projector will write this directly into the entities
                    projection table without re-running now() at projection
                    time (Governance & Replayability Mistake #1 prevention).

    Pydantic config:
        - frozen=True       — payload is immutable after construction;
                              matches append-only spirit.
        - extra="forbid"    — unknown fields raise; prevents silent payload
                              drift (Mistake #8 prevention).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: uuid.UUID
    name: str = Field(..., min_length=1)
    vertical: str = Field(..., min_length=1)
    created_at_for_projection: datetime


class EvidenceRawIngestedPayload(BaseModel):
    """
    Payload for `evidence.raw_ingested` events.

    Represents the ingestion of a single raw external observation (e.g. a
    fetched web page, a DNC registry API response, an analyst paste-in).
    The raw bytes themselves are NEVER in the payload — they live in
    external storage addressed by `storage_uri`. The payload carries only
    the provenance metadata + a `content_hash` so that future replay can
    re-validate integrity without re-fetching from the original source.

    Fields:
        evidence_id              — stable UUID for the evidence record.
                                   Aggregate convention: aggregate_id ==
                                   evidence_id, enforced in the emitter.
        subject_entity_id        — optional UUID linking the evidence to
                                   an entity. Nullable so that evidence
                                   captured before entity creation (e.g.
                                   a DNC lookup on a phone number before
                                   the entity exists) is expressible.
        source_uri               — canonical URI of the source observed
                                   (e.g. "https://example.invalid/contact").
        source_type              — discriminator string (e.g.
                                   "website_fetch", "dnc_registry_lookup",
                                   "manual_analyst_note"). Free-form at
                                   this layer; future projections may
                                   constrain.
        content_hash             — SHA-256 of the raw content, expressed
                                   as exactly 64 lowercase hex characters.
                                   Provenance + replay-integrity hook.
        storage_uri              — URI identifying where the raw bytes
                                   live (e.g. "s3://bucket/path",
                                   "minio://...", "file:///..."). Storage
                                   backend is opaque at this layer; no
                                   MinIO / S3 integration is implied by
                                   accepting the URI shape.
        observed_at_for_projection — logical observation time. A future
                                     evidence projector will write this
                                     directly into its projection table
                                     (same replay-determinism discipline
                                     as EntityCreatedPayload).
        metadata                 — flat dict[str, str] of additional
                                   provenance metadata (e.g.
                                   `{"http_status": "200", "vertical":
                                   "GARAGE_DOOR"}`). Constrained to
                                   str→str to keep JSONB shape stable.

    Out of scope for Day-1 Step 8 (do NOT add here):
        - raw_content (the bytes). External storage only.
        - Storage backend abstractions. storage_uri is opaque.
        - DNC-specific fields. DNC plugs in later as a particular
          source_type value, NOT as a new payload type.
        - Evidence projection table or projector (Step 9+).

    Pydantic config:
        - frozen=True       — payload is immutable after construction.
        - extra="forbid"    — unknown fields raise (Mistake #8 prevention).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: uuid.UUID
    subject_entity_id: uuid.UUID | None = None
    source_uri: str = Field(..., min_length=1)
    source_type: str = Field(..., min_length=1)
    content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    storage_uri: str = Field(..., min_length=1)
    observed_at_for_projection: datetime
    metadata: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event envelope (Blueprint §7 column set, emitter-supplied subset)
# ---------------------------------------------------------------------------


class Event(BaseModel):
    """
    Phase 0 event envelope.

    Matches the Blueprint §7 events-table column set EXCEPT for
    `sequence_no`, which is DB-assigned (BIGSERIAL) at INSERT time and is
    therefore not part of the emitter's contract. All other fields must be
    supplied by the emitter; none are defaulted via `default_factory` so the
    emitter is forced to be explicit about UUID / timestamp generation
    (Governance & Replayability Mistakes #1, #2 prevention).

    Day-1 Step 8 widens the `payload` field from the single
    `EntityCreatedPayload` to a plain Union over the two payload types
    currently defined (`EntityCreatedPayload | EvidenceRawIngestedPayload`).
    Plain Union (not a Pydantic discriminated union) is sufficient because
    the two payloads have strictly disjoint required-field sets and both
    use `extra="forbid"`; future payload types must keep their required
    fields disjoint from existing payloads, OR this field upgrades to an
    explicit discriminated union at that time.

    Pydantic config:
        - frozen=True    — events are immutable values; append-only by
                           convention at the Python layer.
        - extra="forbid" — unknown fields raise (Mistake #8 prevention).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID
    event_type: EventType
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: EntityCreatedPayload | EvidenceRawIngestedPayload
    schema_version: str = Field(..., min_length=1)
    occurred_at: datetime
    recorded_at: datetime
    actor_type: str = Field(..., min_length=1)
    actor_id: str = Field(..., min_length=1)
    causation_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_aggregate_id_matches_payload(self) -> "Event":
        """
        Structural invariant: an event's aggregate_id must equal the
        identity field of its payload (entity_id for entity.created,
        evidence_id for evidence.raw_ingested). Emitters set this by
        convention; the validator enforces it at construction time so
        replay can never resurrect a misaligned envelope from storage
        without raising. Future event types extend the `event_type`
        Literal AND this validator together.
        """
        if self.event_type == "entity.created":
            if not isinstance(self.payload, EntityCreatedPayload):
                raise ValueError(
                    "entity.created event must carry an EntityCreatedPayload, "
                    f"got {type(self.payload).__name__}"
                )
            if self.aggregate_id != self.payload.entity_id:
                raise ValueError(
                    "entity.created: aggregate_id "
                    f"({self.aggregate_id}) must equal payload.entity_id "
                    f"({self.payload.entity_id})"
                )
        elif self.event_type == "evidence.raw_ingested":
            if not isinstance(self.payload, EvidenceRawIngestedPayload):
                raise ValueError(
                    "evidence.raw_ingested event must carry an "
                    "EvidenceRawIngestedPayload, "
                    f"got {type(self.payload).__name__}"
                )
            if self.aggregate_id != self.payload.evidence_id:
                raise ValueError(
                    "evidence.raw_ingested: aggregate_id "
                    f"({self.aggregate_id}) must equal payload.evidence_id "
                    f"({self.payload.evidence_id})"
                )
        return self
