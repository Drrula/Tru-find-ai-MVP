"""
app.events.models — TruSignalAI Phase 0 event-model foundation.

Pydantic v2 models for the canonical append-only event log.

Day-1 Step 4 scope:
    - Only the `entity.created` event type and its payload are defined here.
      Blueprint §8 lists nine other minimum event types (entity.attribute_set,
      entity.domain_registered, ontology.version_loaded, engine.version_loaded,
      evidence.raw_ingested, evidence.derived_created, indicator.observed,
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

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Event-type literal
# ---------------------------------------------------------------------------

EventType = Literal["entity.created"]
"""
Phase 0 event-type discriminator. Day-1 Step 4 introduces only
`entity.created`; subsequent days extend this to a discriminated union
over the full Blueprint §8 minimum set.
"""


# ---------------------------------------------------------------------------
# Aggregate-type constants
# ---------------------------------------------------------------------------

AGGREGATE_TYPE_ENTITY: str = "entity"
"""
Aggregate type for entity.* events. The aggregate_id of an entity.created
event is the entity_id itself (by convention enforced in the emitter).
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

    For Day-1 Step 4 the envelope's `payload` field is statically typed to
    `EntityCreatedPayload`; later days will widen this to a discriminated
    union over additional payload types as they come online.

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
    payload: EntityCreatedPayload
    schema_version: str = Field(..., min_length=1)
    occurred_at: datetime
    recorded_at: datetime
    actor_type: str = Field(..., min_length=1)
    actor_id: str = Field(..., min_length=1)
    causation_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
