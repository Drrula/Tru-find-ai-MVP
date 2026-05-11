"""LeadEventDefinition model — catalog of valid lead event types.

Per ARCHITECTURE-LOCK §2.5.3 + ADR-040 + ADR-047 (platform-owned:
NOT exportable). Rows are catalog entries inserted by operator step
or test fixture; `lead_event` rows reference them via
`event_definition_id` FK.

No `account_id` (platform-owned). No `deleted_at` — retirement is
via `status='retired'`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class LeadEventDefinition(Base):
    __tablename__ = "lead_event_definition"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','retired')",
            name="lead_event_definition_status_check",
        ),
        CheckConstraint(
            "default_weight BETWEEN 0 AND 1",
            name="lead_event_definition_default_weight_range",
        ),
        UniqueConstraint(
            "event_type",
            "version",
            name="uq_lead_event_definition_natural",
        ),
        Index(
            "ix_lead_event_definition_active",
            "event_type",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    default_weight: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
    )
    freshness_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    lenient: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
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
