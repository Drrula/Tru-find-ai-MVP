"""User model — first non-root tenancy-scoped table.

Per ARCHITECTURE-LOCK §2.3, ADR-008 (account_id NOT NULL FK to
account.id; tenancy filtering activates here for the first time —
BaseRepository._has_account_id_column was False for Account, becomes
True for User), ADR-013 (PII columns: email_hash + email_encrypted),
ADR-016 (soft-delete via deleted_at; partial unique index on
email_hash WHERE deleted_at IS NULL allows re-signup after
soft-delete), ADR-018 (DIY magic-link auth; external_auth_id reserved
for the future hosted-provider escape hatch — column lands here, no
value set in B.2), and ADR-033 (UUIDv7 PK, application-side default).

The CHECK constraint on `role` enforces the closed enum at the DB
layer. B.2 stores the role but does NOT enforce per-role gating on
any endpoint (per phase-b2-plan.md §2 decision #13).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class User(Base):
    """Authenticated principal. Always belongs to exactly one account."""

    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner','admin','member')",
            name="user_role_check",
        ),
        Index(
            "ix_user_email_hash_active",
            "email_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_user_account_id",
            "account_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("account.id"),
        nullable=False,
    )
    email_hash: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    email_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    external_auth_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="owner",
        server_default="owner",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
