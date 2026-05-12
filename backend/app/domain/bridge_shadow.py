"""B.6B shadow seam: fire-and-forget canonical persistence,
post-response, never authoritative.

Per docs/phase-b6b-plan.md §4.5 + the 13 locked decisions in §2.

OBJECTIVE: "Live shadow persistence under production traffic with
zero response authority."

This module is the ONE function that gates the entire production
reach of the canonical persistence bridge. The HTTP route (wired
in B.6B.3) schedules `run_shadow_persist_if_enabled` as a
FastAPI BackgroundTask AFTER the response is sent. By
construction, this function CANNOT affect the HTTP response.

Locked invariants (testable, not assumed -- see
test_bridge_shadow.py):

  FLAG OFF (b6b_shadow_scoring_enabled=False):
    - Zero orchestrator execution
    - Zero DB writes
    - Zero connection acquisition
    - Zero sessionmaker invocation
    - Zero async task allocation beyond the function call itself
    - Zero divergence logging
    - Function returns None after a single bool check

  FLAG ON (b6b_shadow_scoring_enabled=True):
    - Acquires its OWN AsyncSession via `_get_sessionmaker()()`
      AFTER the flag check. Request-scoped sessions are NOT
      threaded through.
    - Wraps orchestrator call in `asyncio.wait_for(..., timeout=5)`
    - Commits the shadow session on success
    - Rolls back the shadow session on failure OR timeout
    - Swallows ALL exceptions (TimeoutError, anything else,
      and even a failing rollback)
    - Returns None in every path

Logging severity ladder (per plan §7):

  bridge.shadow_succeeded       DEBUG    success
  bridge.shadow_timeout         WARNING  operational incident
  bridge.shadow_failed          WARNING  orchestrator raised
  bridge.shadow_rollback_failed WARNING  rollback itself raised

Absence of `bridge.*` events for a request IS the signal that
the flag is OFF (per plan §6 decision #6). No "shadow skipped
because disabled" log is emitted.

`bridge.shadow_timeout` is an OPERATIONAL incident (DB slowness,
pool exhaustion, network degradation) -- separate event-name
class from `bridge.score_comparison` at ERROR (which signals
real scoring drift). Same dashboards may surface both, but the
two classes must remain distinguishable.

Demo persistence target: DEMO_ACCOUNT_ID + DEMO_VERTICAL_ID
constants are UUID5-derived and match the seed rows from
migration 0020. Lead-per-call discipline preserved (per plan §2
decision #11; dedupe is a B.6C+ concern).
"""

from __future__ import annotations

import asyncio
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.repositories.lead_repo import LeadRepository
from app.db.repositories.lead_score_snapshot_repo import (
    LeadScoreSnapshotRepository,
)
from app.db.repositories.lead_signal_definition_repo import (
    LeadSignalDefinitionRepository,
)
from app.db.repositories.lead_signal_repo import LeadSignalRepository
from app.db.repositories.vertical_lead_signal_weight_repo import (
    VerticalLeadSignalWeightRepository,
)
from app.db.session import _get_sessionmaker
from app.domain.scoring_persistence import analyze_and_persist


#: Deterministic UUID5 identities matching migration 0020's seed
#: (see backend/alembic/versions/0020_seed_demo_account_vertical_catalog.py).
#: Same namespace + same name -> same UUID across environments,
#: so the shadow path always targets the seeded demo account /
#: vertical. Tests verify these equal the migration's constants.
_SEED_NAMESPACE = uuid.NAMESPACE_DNS
DEMO_ACCOUNT_ID: UUID = uuid.uuid5(
    _SEED_NAMESPACE, "trufindai.demo.account"
)
DEMO_VERTICAL_ID: UUID = uuid.uuid5(
    _SEED_NAMESPACE,
    "trufindai.demo.vertical.local_business_ai_visibility",
)

#: Hard ceiling on shadow execution. Per plan §2 decision #5.
#: Timeouts swallow + log at WARNING; never affect the HTTP
#: response (which has already been delivered by the time the
#: BackgroundTask fires).
SHADOW_TIMEOUT_SECONDS: float = 5.0

_logger = get_logger("app.domain.bridge_shadow")


async def run_shadow_persist_if_enabled(
    *,
    business_name: str,
    location: str,
    trade: str | None,
) -> None:
    """Fire-and-forget shadow persistence (B.6B.2 seam).

    Called from a FastAPI BackgroundTask AFTER the response is
    delivered (B.6B.3 wires the route side). This function:

      1. Reads `Settings.b6b_shadow_scoring_enabled` ONCE.
      2. If False: returns None immediately. No session acquired,
         no orchestrator invoked, no logs. The flag-OFF fast path
         is a single bool check.
      3. If True: acquires its OWN AsyncSession, runs the B.6A.4
         orchestrator inside a `SHADOW_TIMEOUT_SECONDS` timeout,
         and swallows every exception class (TimeoutError,
         orchestrator failures, rollback failures).

    Returns None unconditionally. NEVER raises. The HTTP response
    has already been delivered when this function executes; any
    side effect is invisible to the client.
    """
    if not get_settings().b6b_shadow_scoring_enabled:
        # FLAG-OFF FAST PATH (per plan §6):
        # zero side effects, zero allocation, zero log.
        return

    # Past this point we are ON. Acquire OWN session.
    async with _get_sessionmaker()() as session:
        try:
            await asyncio.wait_for(
                analyze_and_persist(
                    business_name=business_name,
                    location=location,
                    trade=trade,
                    account_id=DEMO_ACCOUNT_ID,
                    vertical_id=DEMO_VERTICAL_ID,
                    lead_repo=LeadRepository(session, DEMO_ACCOUNT_ID),
                    lead_signal_repo=LeadSignalRepository(
                        session, DEMO_ACCOUNT_ID
                    ),
                    signal_definition_repo=LeadSignalDefinitionRepository(
                        session, None
                    ),
                    weight_repo=VerticalLeadSignalWeightRepository(
                        session, None
                    ),
                    score_repo=LeadScoreSnapshotRepository(
                        session, DEMO_ACCOUNT_ID
                    ),
                    logger=_logger,
                ),
                timeout=SHADOW_TIMEOUT_SECONDS,
            )
            await session.commit()
            _logger.debug(
                "bridge.shadow_succeeded",
                business_name=business_name,
                location=location,
            )
        except asyncio.TimeoutError:
            _logger.warning(
                "bridge.shadow_timeout",
                business_name=business_name,
                location=location,
                timeout_seconds=SHADOW_TIMEOUT_SECONDS,
            )
            await _safe_rollback(session)
        except Exception:
            _logger.warning(
                "bridge.shadow_failed",
                business_name=business_name,
                location=location,
                exc_info=True,
            )
            await _safe_rollback(session)


async def _safe_rollback(session: AsyncSession) -> None:
    """Best-effort rollback. If rollback itself raises, log at
    WARNING and swallow -- never propagate. The shadow path's
    contract is "return None unconditionally"; a rollback failure
    cannot break that contract."""
    try:
        await session.rollback()
    except Exception:
        _logger.warning(
            "bridge.shadow_rollback_failed", exc_info=True
        )
