"""User repository.

Per ADR-031, ADR-008, ADR-013. First repository where the
BaseRepository tenancy filter actually fires:
`User.__table__.columns` includes `account_id`, so
`_has_account_id_column` is True and every default read filters by
the constructed `account_id`. Constructing this repository with
`account_id=None` raises at first read (unless
`force_cross_account=True` is passed).

`find_by_email_hash` is the system-context exception: during the
magic-link consume flow the resolver does not yet know which account
the email belongs to, so the lookup MUST cross account boundaries.
The method passes `force_cross_account=True` internally — caller does
not need to know the bypass detail.
"""

from __future__ import annotations

from uuid import UUID

from app.core.ids import new_id
from app.db.models import User
from app.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """CRUD for users."""

    model_class = User

    async def create(
        self,
        *,
        account_id: UUID,
        email_hash: bytes,
        email_encrypted: bytes,
        display_name: str | None = None,
        role: str = "owner",
    ) -> User:
        """Create a new user row.

        Mints the UUIDv7 id explicitly so callers can read `.id` and
        `.account_id` immediately without waiting for `session.flush()`.
        """
        user = User(
            id=new_id(),
            account_id=account_id,
            email_hash=email_hash,
            email_encrypted=email_encrypted,
            display_name=display_name,
            role=role,
        )
        self.add(user)
        return user

    async def find_by_email_hash(self, email_hash: bytes) -> User | None:
        """Find a user by email_hash, ignoring tenancy.

        SYSTEM-CONTEXT call: the magic-link consume flow does not yet know
        which account the email belongs to, so this lookup must cross
        account boundaries by design. Internally uses
        `force_cross_account=True`. Soft-deleted users are excluded
        (the partial unique index on email_hash is also gated on
        `deleted_at IS NULL`).
        """
        return await self.find_one(
            force_cross_account=True,
            email_hash=email_hash,
        )
