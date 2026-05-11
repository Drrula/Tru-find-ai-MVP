"""VerticalCopy model — locale-keyed strings per vertical.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-046 (locale-keyed schema)
+ ADR-048 + ADR-047 (platform-owned).

Natural key: (vertical_id, locale, key). The UNIQUE constraint
enforces one text per tuple.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class VerticalCopy(Base):
    __tablename__ = "vertical_copy"
    __table_args__ = (
        UniqueConstraint(
            "vertical_id", "locale", "key", name="uq_vertical_copy_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    vertical_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vertical.id"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    key: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(
        Text,
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
