"""Lead intelligence domain (per ADRs 035-041 + 044).

Public surface:
- `LIFECYCLE_STATES` + `transition` (B.4.4) -- the lifecycle state
  machine for leads. `transition` is the ONLY way
  `lead.lifecycle_state` should be mutated.
- `record_lead_event` + `record_lead_signal` (B.4.5) -- thin
  catalog-validation + DB-write helpers. Neither publishes a
  canonical envelope; callers emit `publish_event` separately if
  they want the structured log line.
- `compute_lead_score` + `ComputedLeadScore` (B.5.2) -- pure
  deterministic scoring primitive. Reads stored signals + active
  weights; returns (score, breakdown, inputs). Does NOT persist;
  B.5.3's `record_lead_score` helper wraps compute + write.

Importing this package triggers side-effect registration of the
lead.* event types with `app.core.event_registry` (mirrors the
auth-events pattern from B.2.3).
"""

from __future__ import annotations

from app.domain.leads import events  # noqa: F401 — side-effect: registers types
from app.domain.leads.lifecycle import (
    LIFECYCLE_STATES,
    LIFECYCLE_TRANSITION_EVENT_TYPE,
    transition,
)
from app.domain.leads.recording import record_lead_event, record_lead_signal
from app.domain.leads.scoring import ComputedLeadScore, compute_lead_score

__all__ = [
    "LIFECYCLE_STATES",
    "LIFECYCLE_TRANSITION_EVENT_TYPE",
    "ComputedLeadScore",
    "compute_lead_score",
    "record_lead_event",
    "record_lead_signal",
    "transition",
]
