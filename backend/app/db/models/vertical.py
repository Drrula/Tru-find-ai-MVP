"""Vertical model — config root for each vertical pack.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-048 + ADR-047
(platform-owned: no `account_id`, NOT exportable via
`/v1/account/export`).

No `deleted_at` — verticals follow a version-and-replace lifecycle
via `schema_version`, not soft-delete.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class Vertical(Base):
    """One row per registered vertical pack."""

    __tablename__ = "vertical"
    __table_args__ = (
        UniqueConstraint("pack_id", name="uq_vertical_pack_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    pack_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
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
