"""Lead intelligence domain (per ADRs 035-041 + 044).

Public surface:
- `LIFECYCLE_STATES` + `transition` (B.4.4) -- the lifecycle state
  machine for leads. `transition` is the ONLY way
  `lead.lifecycle_state` should be mutated.
- `record_lead_event` + `record_lead_signal` (B.4.5, pending) -- the
  generic recording helpers.

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

__all__ = [
    "LIFECYCLE_STATES",
    "LIFECYCLE_TRANSITION_EVENT_TYPE",
    "transition",
]
