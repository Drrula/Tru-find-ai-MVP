"""
app.compliance.projectors — TruSignalAI Phase 0 (post-Blueprint-§8
expansion) compliance-state projector.

Day-1 Step 11 scope:
    - Project compliance.state_asserted events into the compliance_state
      projection.
    - Pure function of (event.payload, event.event_id, event.occurred_at).
    - Single INSERT with ON CONFLICT (compliance_state_id) DO NOTHING —
      projecting the same event twice is a no-op (idempotence).
    - The caller owns transaction control. The projector performs exactly
      one SQL statement: the INSERT. No reads from the events table.
    - Auxiliary evaluator metadata (runtime, retry count, audit
      signatures, prompt template id) is NOT copied into the projection.
      It stays in events.payload (queryable via JOIN to events ON
      created_event_id when needed).

DOCTRINE (Day-1 Step 11) — replayable historical interpretation, not
objective truth:
    compliance_state assertions are REPLAYABLE HISTORICAL INTERPRETATIONS
    made under a specific (policy_id, policy_version) and evidence
    context. The substrate does not enforce policy semantics; the
    projector records what was asserted at the time the assertion was
    made. Re-evaluating against today's policy is a DIFFERENT question
    from what the policy SAID at assertion time, and the substrate
    preserves both possibilities by recording (policy_id, policy_version,
    parent_derived_evidence_ids, assertion) verbatim.

Replay-determinism contract (Phase_0_Governance_and_Replayability.md
Part B):
    - The projector NEVER reads the wall clock, NEVER generates fresh
      identifiers, NEVER reads env vars, NEVER touches local files,
      NEVER makes network calls, NEVER runs policy-evaluation /
      classifier / LLM / rules-engine logic. Every value written to
      compliance_state is derived from the event tuple supplied by the
      caller. Replay over the same event log produces byte-identical
      projection rows.
    - projected_at is sourced from event.occurred_at, NOT from a fresh
      clock read at projection time.

Out of scope (do NOT add here):
    - Reads from the events table.
    - Replay engine, dispatcher, registry, or any cross-projection
      orchestration. Each projector is its own narrow function.
    - Policy evaluation, scoring, routing, enforcement, action,
      automation, Sara/UI, reporting code.
    - Cross-projection consistency checks against
      parent_derived_evidence_ids. The substrate emits/projects
      faithfully; consistency is a consumer concern.

Locked references:
    - Phase_0_Execution_Blueprint.md §19 (Day 1 deliverables)
    - Phase_0_Governance_and_Replayability.md Part B (replay-determinism)
    - Phase_0_Freeze_Boundary.md §A (projections mutable, events
      append-only)
"""

from __future__ import annotations

import json

import psycopg

from app.events.models import Event


# ---------------------------------------------------------------------------
# Private: single-statement INSERT into compliance_state
# ---------------------------------------------------------------------------

_INSERT_COMPLIANCE_STATE_SQL: str = """
INSERT INTO compliance_state (
    compliance_state_id, subject_entity_id, parent_derived_evidence_ids,
    policy_id, policy_version, assertion,
    asserted_at_for_projection, created_event_id, projected_at
) VALUES (
    %(compliance_state_id)s, %(subject_entity_id)s,
    %(parent_derived_evidence_ids)s::uuid[],
    %(policy_id)s, %(policy_version)s,
    %(assertion)s::jsonb,
    %(asserted_at_for_projection)s, %(created_event_id)s, %(projected_at)s
)
ON CONFLICT (compliance_state_id) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------


def project_compliance_state_asserted(
    conn: psycopg.Connection, event: Event,
) -> None:
    """
    Project one compliance.state_asserted Event into the compliance_state
    projection.

    Row columns derived from the event:
        compliance_state_id          ← event.payload.compliance_state_id
        subject_entity_id            ← event.payload.subject_entity_id
                                       (nullable; soft pointer)
        parent_derived_evidence_ids  ← event.payload.parent_derived_evidence_ids
                                       (UUID[]; non-empty by Pydantic
                                       contract; order preserved; soft
                                       pointers; no FK on elements)
        policy_id                    ← event.payload.policy_id
        policy_version               ← event.payload.policy_version
        assertion                    ← event.payload.assertion
                                       (serialized via json.dumps with
                                       sort_keys=True and default=str
                                       for byte-stable JSONB)
        asserted_at_for_projection   ← event.payload.asserted_at_for_projection
        created_event_id             ← event.event_id (provenance FK)
        projected_at                 ← event.occurred_at (NOT wall-clock)

    Idempotence: ON CONFLICT (compliance_state_id) DO NOTHING.
    Re-projecting the same event leaves the existing row untouched.

    The projector NEVER re-runs the policy-evaluation logic that
    produced the assertion. The assertion is recorded verbatim. Replay
    over the same event log produces byte-identical projection rows
    including the assertion bytes.

    Auxiliary evaluator metadata (runtime, retry count, audit
    signatures) belongs in events.payload, NOT in this projection. The
    projector keeps compliance_state narrow to the projection-substance
    fields: identity, provenance, policy lineage, the asserted claim.

    Transactional contract:
        - The single INSERT runs inside the caller-supplied connection's
          current transaction.
        - The caller is responsible for commit() / rollback().
    """
    payload = event.payload
    assertion_json = json.dumps(payload.assertion, sort_keys=True, default=str)
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_COMPLIANCE_STATE_SQL,
            {
                "compliance_state_id": payload.compliance_state_id,
                "subject_entity_id": payload.subject_entity_id,
                "parent_derived_evidence_ids": payload.parent_derived_evidence_ids,
                "policy_id": payload.policy_id,
                "policy_version": payload.policy_version,
                "assertion": assertion_json,
                "asserted_at_for_projection": payload.asserted_at_for_projection,
                "created_event_id": event.event_id,
                "projected_at": event.occurred_at,
            },
        )
