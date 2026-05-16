"""
app.entities.projectors — TruSignalAI Phase 0 entity projector.

Day-1 Step 5 scope:
    - Project entity.created events into the entities projection table.
    - Pure function of (event.payload, event.event_id, event.occurred_at).
    - Single INSERT with ON CONFLICT (entity_id) DO NOTHING — projecting
      the same event twice is a no-op (idempotence).
    - The caller owns transaction control. The projector performs exactly
      one SQL statement: the INSERT. No commit / rollback here.

Replay-determinism contract (Phase_0_Governance_and_Replayability.md Part B):
    - The projector NEVER reads the wall clock, NEVER generates UUIDs,
      NEVER reads env vars, NEVER opens files, NEVER makes network calls.
      Every value written to the entities row is derived from the event
      tuple supplied by the caller. Replay over the same event log
      produces byte-identical projection rows (Mistakes #1, #2, #7
      prevention).
    - projected_at is sourced from event.occurred_at, NOT from a fresh
      clock read at projection time.

Out of scope (do NOT add here):
    - Replay engine (Day-1 Step 6, app/events/replay.py).
    - Additional projection tables (later days).
    - Indicators, scoring, reporting, dashboards, CLI.

Locked references:
    - Phase_0_Execution_Blueprint.md §19 (Day 1 deliverables 6–7)
    - Phase_0_Governance_and_Replayability.md Part B (replay-determinism)
    - Phase_0_Freeze_Boundary.md §A (projections mutable, events append-only)
"""

from __future__ import annotations

import psycopg

from app.events.models import Event


# ---------------------------------------------------------------------------
# Private: single-statement INSERT into entities
# ---------------------------------------------------------------------------

_INSERT_ENTITY_SQL: str = """
INSERT INTO entities (
    entity_id, name, vertical, created_at_for_projection,
    created_event_id, projected_at
) VALUES (
    %(entity_id)s, %(name)s, %(vertical)s, %(created_at_for_projection)s,
    %(created_event_id)s, %(projected_at)s
)
ON CONFLICT (entity_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------


def project_entity_created(conn: psycopg.Connection, event: Event) -> None:
    """
    Project one entity.created Event into the entities projection table.

    The row's columns are derived from the event as follows:
        entity_id                  ← event.payload.entity_id
        name                       ← event.payload.name
        vertical                   ← event.payload.vertical
        created_at_for_projection  ← event.payload.created_at_for_projection
        created_event_id           ← event.event_id
        projected_at               ← event.occurred_at

    Idempotence: ON CONFLICT (entity_id) DO NOTHING. Re-projecting the
    same event leaves the existing row untouched.

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction.
        - The caller is responsible for commit() / rollback().
    """
    payload = event.payload
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_ENTITY_SQL,
            {
                "entity_id": payload.entity_id,
                "name": payload.name,
                "vertical": payload.vertical,
                "created_at_for_projection": payload.created_at_for_projection,
                "created_event_id": event.event_id,
                "projected_at": event.occurred_at,
            },
        )
