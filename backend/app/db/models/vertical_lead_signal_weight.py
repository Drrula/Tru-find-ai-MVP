"""VerticalLeadSignalWeight model — per-vertical signal weights with
effective_from/effective_to history.

Per ARCHITECTURE-LOCK §2.5.2 + ADR-011 + ADR-036 + ADR-047
(platform-owned: NOT exportable).

History pattern: each row has an explicit `effective_from`. When
retiring a weight, the active row's `effective_to` is set via
`VerticalLeadSignalWeightRepository.close_active`. The "active"
weight for `(vertical_id, signal_name, dimension)` is the row with
the latest `effective_from` where `effective_to IS NULL`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class VerticalLeadSignalWeight(Base):
    __tablename__ = "vertical_lead_signal_weight"
    __table_args__ = (
        CheckConstraint(
            "weight BETWEEN 0 AND 1",
            name="vertical_lead_signal_weight_range",
        ),
        UniqueConstraint(
            "vertical_id",
            "signal_name",
            "dimension",
            "effective_from",
            name="uq_vertical_lead_signal_weight_history",
        ),
        Index(
            "ix_vertical_lead_signal_weight_lookup",
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
        Text,
        ForeignKey("lead_signal_definition.name"),
        nullable=False,
    )
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
