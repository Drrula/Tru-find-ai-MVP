"""MagicLinkToken repository.

Per ADR-031, ADR-018, ADR-032. The `magic_link_token` table is
intentionally pre-account-binding (no `account_id` column), so
`BaseRepository._has_account_id_column` is False and reads do NOT
require an `account_id`. Pass `account_id=None` to the constructor.

This is the SYSTEM-CONTEXT repository for the request half of the
magic-link flow: the auth domain has no logged-in user yet at that
point.

Consume marks `consumed_at = now()` via an explicit UPDATE — the table
has no `deleted_at` column, so BaseRepository's soft_delete helper is
not applicable here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import update

from app.core.ids import new_id
from app.db.models import MagicLinkToken
from app.db.repositories.base import BaseRepository


class MagicLinkTokenRepository(BaseRepository[MagicLinkToken]):
    """CRUD for magic-link tokens. Pre-account-binding."""

    model_class = MagicLinkToken

    async def create(
        self,
        *,
        email_hash: bytes,
        token_hash: bytes,
        issued_at: datetime,
        expires_at: datetime,
        ip_hash: bytes | None = None,
    ) -> MagicLinkToken:
        """Create a new outstanding magic-link token.

        Mints the UUIDv7 id explicitly so callers can read `.id`
        immediately for logging / audit purposes.
        """
        token = MagicLinkToken(
            id=new_id(),
            email_hash=email_hash,
            token_hash=token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            ip_hash=ip_hash,
        )
        self.add(token)
        return token

    async def find_active_by_token_hash(
        self, token_hash: bytes
    ) -> MagicLinkToken | None:
        """Find an outstanding (not-yet-consumed) token by its hash.

        Returns None if the token has already been consumed. Expiry is
        NOT checked here — the consume domain layer (B.2.3) compares
        `expires_at` against `now()` and emits a structured event on
        rejection.
        """
        return await self.find_one(
            token_hash=token_hash,
            consumed_at=None,
        )

    async def mark_consumed(self, token_id: UUID) -> bool:
        """Mark a token as consumed by setting `consumed_at = now()`.

        Returns True if a row was updated. Idempotent: an already-consumed
        token returns False.
        """
        stmt = update(MagicLinkToken).where(
            MagicLinkToken.id == token_id,
            MagicLinkToken.consumed_at.is_(None),
        )
        stmt = stmt.values(consumed_at=sa_func.now())
        result = await self.session.execute(stmt)
        return result.rowcount > 0
