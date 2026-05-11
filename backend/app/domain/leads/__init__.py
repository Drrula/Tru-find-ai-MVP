"""Lead intelligence domain (per ADRs 035-041 + 044).

B.4.2 introduces this package with the canonical lead.* event-type
registrations only. Future sub-phases extend it:

- B.4.4: `lifecycle.py` — LIFECYCLE_STATES frozenset + `transition()`
  helper.
- B.4.5: `recording.py` — `record_lead_event` + `record_lead_signal`
  helpers.

Importing this package triggers side-effect registration of the
lead.* event types with `app.core.event_registry` (mirrors the
auth-events pattern from B.2.3).
"""

from __future__ import annotations

from app.domain.leads import events  # noqa: F401 — side-effect: registers types
