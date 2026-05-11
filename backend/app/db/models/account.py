"""Account model — the tenancy root.

Per ADR-008 (every owned/derived row has `account_id` pointing here),
ADR-033 (UUIDv7 PK, application-side default via `app.core.ids.new_id`),
and ARCHITECTURE-LOCK §2.3 (column spec).

This is the FIRST domain model. Subsequent models add `account_id` as
a NOT NULL FK to this table; tenancy enforcement happens at the
repository layer (ADR-031 — lands in B.1.5).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class Account(Base):
    """Tenancy root. All owned data hangs off `account_id` -> `account.id`."""

    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','suspended','closed')",
            name="account_status_check",
        ),
        CheckConstraint(
            "region IN ('us','ca','uk')",
            name="account_region_check",
        ),
        Index(
            "ix_account_parent_account_id",
            "parent_account_id",
            postgresql_where=text("parent_account_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,  # UUIDv7 from app.core.ids
    )
    display_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    parent_account_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("account.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="active",
        server_default="active",
    )
    # B.3.5 (per ADR-046): informational region tag. Allowlist enforced
    # by the account_region_check CHECK constraint. No routing semantics
    # in B.3 — this column is read by future region-aware code paths.
    region: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="us",
        server_default="us",
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
