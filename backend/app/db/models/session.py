"""UserSession model — DB-backed session backing the HttpOnly cookie.

Per ARCHITECTURE-LOCK §2.3, ADR-008 (account_id denormalized from
user.account_id — set at session creation, never updated), ADR-018
(DB-backed sessions: cookie carries session.id signed by
SESSION_SECRET; session row is the source of truth), and ADR-033
(UUIDv7 PK).

Class name is `UserSession` (not `Session`) to avoid clashing with
SQLAlchemy's `Session`/`AsyncSession`. The TABLE name is "session"
per the Lock spec.

Soft-revoke via `revoked_at` (nullable) — explicit revoke semantics,
NOT soft-delete. BaseRepository's deleted_at-based soft-delete filter
deliberately does not apply here (column does not exist); revocation
is a domain-level concept handled in B.2.3.

ip_hash stores sha256(client_ip) (32 bytes). Plaintext IP is never
persisted (per ADR-013 PII posture).

user_agent is truncated to 256 chars at write time by callers; the
String(256) column length enforces the upper bound at the DB layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class UserSession(Base):
    """An issued session. Bound to exactly one user (and one account)."""

    __tablename__ = "session"
    __table_args__ = (
        Index(
            "ix_session_user_id_expires_at",
            "user_id",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user.id"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("account.id"),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ip_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
