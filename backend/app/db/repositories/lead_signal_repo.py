"""LeadSignalRepository — append-only signal observation writes +
named query helpers.

Per ADR-031 + ADR-036 + ADR-010 analog + ADR-047 (customer-owned:
tenancy filter active; no soft-delete column — signal observations
are immutable per the append-only contract).

APPEND-ONLY: this repo exposes `create` + 3 named query methods.
NO `update_*` methods. NO mutators of any kind. Inherited
`BaseRepository.soft_delete` naturally refuses (no deleted_at
column on LeadSignal).

Per feedback_inspectability_over_abstraction:
- `find_current(lead_id, signal_name)` — the latest observation;
  tie-broken by id DESC (UUIDv7 ids are time-sortable per ADR-033).
- `find_history(lead_id, signal_name)` — all observations for this
  signal on this lead, newest first.
- `find_by_lead_id(lead_id)` — all signals on this lead, newest
  first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.ids import new_id
from app.db.models import Lead, LeadSignal
from app.db.repositories.base import BaseRepository


class LeadSignalRepository(BaseRepository[LeadSignal]):
    model_class = LeadSignal

    async def create(
        self,
        *,
        lead: Lead,
        signal_name: str,
        value: dict[str, Any],
        source: str,
        observed_at: datetime,
        recorded_at: datetime,
        source_ref_id: UUID | None = None,
    ) -> LeadSignal:
        """Stage a new lead_signal observation row.

        Denormalizes `account_id` from `lead.account_id` so the
        account-scoped index (`ix_lead_signal_account_observed`)
        works without joining `lead`. Mints UUIDv7 explicitly so
        callers can read `.id` immediately.
        """
        row = LeadSignal(
            id=new_id(),
            account_id=lead.account_id,
            lead_id=lead.id,
            signal_name=signal_name,
            value=value,
            source=source,
            source_ref_id=source_ref_id,
            observed_at=observed_at,
            recorded_at=recorded_at,
        )
        self.add(row)
        return row

    async def find_current(
        self, lead_id: UUID, signal_name: str
    ) -> LeadSignal | None:
        """Return the LATEST observation of `signal_name` for `lead_id`,
        or None if no observation has been recorded.

        ORDER BY observed_at DESC, id DESC LIMIT 1 — the second
        sort key tie-breaks on UUIDv7 id (which is time-sortable per
        ADR-033), so when two observations land in the same
        microsecond the one inserted later wins deterministically.

        Account-scoped via BaseRepository tenancy filter. Backed by
        `ix_lead_signal_lead_name_observed`.
        """
        stmt = (
            self._base_select()
            .where(LeadSignal.lead_id == lead_id)
            .where(LeadSignal.signal_name == signal_name)
            .order_by(LeadSignal.observed_at.desc(), LeadSignal.id.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_history(
        self, lead_id: UUID, signal_name: str
    ) -> list[LeadSignal]:
        """Return ALL observations of `signal_name` for `lead_id`,
        newest first.

        Backed by `ix_lead_signal_lead_name_observed` for the
        (lead_id, signal_name) prefix.
        """
        stmt = (
            self._base_select()
            .where(LeadSignal.lead_id == lead_id)
            .where(LeadSignal.signal_name == signal_name)
            .order_by(LeadSignal.observed_at.desc(), LeadSignal.id.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_lead_id(self, lead_id: UUID) -> list[LeadSignal]:
        """Return ALL signal observations for `lead_id` across every
        signal_name, newest first.

        Backed by `ix_lead_signal_lead_name_observed` (the
        lead_id-only prefix is a usable subset of the composite
        index).
        """
        stmt = (
            self._base_select()
            .where(LeadSignal.lead_id == lead_id)
            .order_by(LeadSignal.observed_at.desc(), LeadSignal.id.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
