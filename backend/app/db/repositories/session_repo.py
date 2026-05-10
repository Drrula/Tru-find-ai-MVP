"""UserSession repository.

Per ADR-031, ADR-008, ADR-018. Tenancy filter fires (UserSession has
`account_id`).

`account_id` is denormalized at write time from the user's account
(see `create`), so reads through this repo are cheaply
tenancy-scoped without joining `user`.

Revocation uses an explicit UPDATE rather than the BaseRepository
`soft_delete` helper — the table has no `deleted_at` column (see
ARCHITECTURE-LOCK §2.3 + the model docstring). `BaseRepository.
soft_delete()` would raise `NotImplementedError` for this model, by
design.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import update

from app.core.ids import new_id
from app.db.models import User, UserSession
from app.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository[UserSession]):
    """CRUD for user sessions."""

    model_class = UserSession

    async def create(
        self,
        *,
        user: User,
        issued_at: datetime,
        expires_at: datetime,
        ip_hash: bytes | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        """Create a new session row, denormalizing account_id from the user.

        Mints the UUIDv7 id explicitly so callers can read `.id` (the
        cookie payload) immediately without waiting for `session.flush()`.

        `user_agent` is truncated to 256 chars at write time; the column
        length matches.
        """
        sess = UserSession(
            id=new_id(),
            user_id=user.id,
            account_id=user.account_id,
            issued_at=issued_at,
            expires_at=expires_at,
            ip_hash=ip_hash,
            user_agent=user_agent[:256] if user_agent is not None else None,
        )
        self.add(sess)
        return sess

    async def revoke(self, session_id: UUID) -> bool:
        """Mark a session as revoked by setting `revoked_at = now()`.

        Returns True if a row was updated. Idempotent: an already-revoked
        session returns False (the WHERE excludes them). Tenancy filter
        applies — only sessions owned by `self.account_id` can be revoked
        through this method.
        """
        stmt = update(UserSession).where(
            UserSession.id == session_id,
            UserSession.revoked_at.is_(None),
        )
        if self._has_account_id_column and self.account_id is not None:
            stmt = stmt.where(UserSession.account_id == self.account_id)
        stmt = stmt.values(revoked_at=sa_func.now())
        result = await self.session.execute(stmt)
        return result.rowcount > 0
