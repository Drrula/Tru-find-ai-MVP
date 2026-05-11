"""LeadRepository — explicit named methods over the `lead` table.

Per ADR-031 (repository pattern) + ADR-008 (tenancy filter active —
Lead has `account_id` so every read filters by `self.account_id`) +
ADR-016 (soft-delete filter active — Lead has `deleted_at` so reads
exclude soft-deleted rows by default).

Per `feedback_inspectability_over_abstraction.md`: this repo
exposes NAMED methods (`create`, `find_by_email_hash`,
`find_by_phone_hash`, `find_by_lifecycle_state`,
`update_lifecycle_state`) instead of a generic query builder.
Inherited `get` / `find_one` / `find_many` / `add` / `soft_delete`
from BaseRepository remain available for callers that need direct
primitives, but the domain-layer callers (B.4.4 lifecycle helper,
B.4.5 recording helpers) reach for the named methods.

Tenancy filter applies to every read AND to `update_lifecycle_state`
(the UPDATE includes `account_id = self.account_id`). Lead lookups
are account-scoped — a lead with the same email_hash in a different
account is a different lead, NOT a duplicate.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import update

from app.core.ids import new_id
from app.db.models import Lead
from app.db.repositories.base import BaseRepository


class LeadRepository(BaseRepository[Lead]):
    """CRUD + named query helpers for the lead table."""

    model_class = Lead

    async def create(
        self,
        *,
        account_id: UUID,
        source: str,
        vertical_id: UUID | None = None,
        lifecycle_state: str = "cold",
        email_hash: bytes | None = None,
        email_encrypted: bytes | None = None,
        phone_hash: bytes | None = None,
        phone_encrypted: bytes | None = None,
        consent_sms: bool = False,
        consent_email: bool = False,
        consent_source: str | None = None,
    ) -> Lead:
        """Stage a new lead row.

        Mints the UUIDv7 id explicitly so callers can read `.id`
        immediately without waiting for `session.flush()`. Required
        args (`account_id` + `source`) are keyword-only so call sites
        are self-documenting at the import site.

        `lifecycle_state` defaults to `'cold'`; the domain lifecycle
        helper (B.4.4) is the right path for non-default initial
        states + subsequent transitions, but creating a lead in a
        non-default state directly is allowed (e.g., importing a lead
        that's already engaged elsewhere).
        """
        lead = Lead(
            id=new_id(),
            account_id=account_id,
            source=source,
            vertical_id=vertical_id,
            lifecycle_state=lifecycle_state,
            email_hash=email_hash,
            email_encrypted=email_encrypted,
            phone_hash=phone_hash,
            phone_encrypted=phone_encrypted,
            consent_sms=consent_sms,
            consent_email=consent_email,
            consent_source=consent_source,
        )
        self.add(lead)
        return lead

    async def find_by_email_hash(self, email_hash: bytes) -> Lead | None:
        """Look up a lead by `email_hash` within the constructor's
        tenancy scope. Returns None if no active (non-soft-deleted)
        lead matches.

        ACCOUNT-SCOPED: a lead with the same `email_hash` in a
        different account is a different lead — leads are NOT
        deduplicated across accounts. The tenancy filter from
        BaseRepository handles this automatically.
        """
        return await self.find_one(email_hash=email_hash)

    async def find_by_phone_hash(self, phone_hash: bytes) -> Lead | None:
        """Look up a lead by `phone_hash` within the constructor's
        tenancy scope. Returns None if no active lead matches.

        Account-scoped, same as `find_by_email_hash`.
        """
        return await self.find_one(phone_hash=phone_hash)

    async def find_by_lifecycle_state(self, state: str) -> list[Lead]:
        """Return all active leads in the given lifecycle state within
        the constructor's tenancy scope.

        Operational query for "show me all my qualified leads" etc.
        Does NOT validate `state` against the enum — the DB CHECK
        constraint enforces the enum on writes; passing an unknown
        state to this method returns an empty list.
        """
        return await self.find_many(lifecycle_state=state)

    async def update_lifecycle_state(
        self,
        lead_id: UUID,
        new_state: str,
    ) -> bool:
        """Update `lifecycle_state` on the lead matching `lead_id`
        within the constructor's tenancy scope.

        Returns True if a row was updated. Does NOT validate
        `new_state` against the Python-side enum — the DB CHECK
        constraint enforces the enum and will reject invalid values
        at flush time. The domain lifecycle helper
        (`app.domain.leads.lifecycle.transition`, B.4.4) validates
        in Python before calling this repo method.

        Soft-deleted leads are NOT updated (the WHERE excludes them).
        """
        stmt = (
            update(Lead)
            .where(Lead.id == lead_id)
            .where(Lead.deleted_at.is_(None))
        )
        if self.account_id is not None:
            stmt = stmt.where(Lead.account_id == self.account_id)
        stmt = stmt.values(
            lifecycle_state=new_state,
            updated_at=sa_func.now(),
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0
