"""VerticalSignalWeight model — per-vertical signal weights with history.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-048 + ADR-047
(platform-owned).

`effective_from` carries the time-versioning: multiple rows for the
same (vertical_id, signal_name) at different times. The "current"
weight is the row with the latest `effective_from <= now()`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class VerticalSignalWeight(Base):
    __tablename__ = "vertical_signal_weight"
    __table_args__ = (
        UniqueConstraint(
            "vertical_id",
            "signal_name",
            "effective_from",
            name="uq_vertical_signal_weight_history",
        ),
        Index(
            "ix_vertical_signal_weight_vertical_signal",
            "vertical_id",
            "signal_name",
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
    signal_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    weight: Mapped[Decimal] = mapped_column(
        Numeric,
        nullable=False,
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
