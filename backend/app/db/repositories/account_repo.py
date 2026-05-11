"""Account repository — tenancy root.

Per docs/phase-b-plan.md §5. The Account table IS the tenancy root, so
the BaseRepository's tenancy filter naturally skips it (Account has no
`account_id` column — column introspection returns False). No subclass
override needed.

Soft-delete still applies (Account has `deleted_at`). Per ADR-016,
deleted accounts are filtered from default reads but rows persist for
recovery / audit.
"""

from __future__ import annotations

from uuid import UUID

from app.core.ids import new_id
from app.db.models import Account
from app.db.repositories.base import BaseRepository


class AccountRepository(BaseRepository[Account]):
    """CRUD for accounts. The tenancy root."""

    model_class = Account

    async def create(
        self,
        display_name: str,
        *,
        parent_account_id: UUID | None = None,
        region: str | None = None,
    ) -> Account:
        """Create a new account row.

        Mints the UUIDv7 id explicitly so callers can read `.id` immediately
        without waiting for `session.flush()` to populate it from the model's
        Python-side default. (The model's `default=new_id` still applies for
        any direct-construction code path that bypasses this repo.)

        `region` (per ADR-046): if None, falls through to the model's
        `default='us'` / server_default='us'. Pass explicitly (`'us'`,
        `'ca'`, `'uk'`) when the caller has region context (e.g. from
        geoip, user input). The CHECK constraint
        `account_region_check` rejects out-of-allowlist values at the
        DB layer.
        """
        kwargs: dict = {
            "id": new_id(),
            "display_name": display_name,
            "parent_account_id": parent_account_id,
        }
        if region is not None:
            kwargs["region"] = region
        account = Account(**kwargs)
        self.add(account)
        return account

    async def find_by_status(self, status: str) -> list[Account]:
        """Convenience wrapper around find_many(status=...)."""
        return await self.find_many(status=status)
