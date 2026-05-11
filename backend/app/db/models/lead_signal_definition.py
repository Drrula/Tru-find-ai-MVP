"""LeadSignalDefinition model — catalog of valid lead signal names.

Per ARCHITECTURE-LOCK §2.5.2 + ADR-036 + ADR-047 (platform-owned:
NOT exportable via `/v1/account/export`).

DIVERGES from the UUIDv7-PK convention: `name` is the text PK
because signals are referenced by name throughout the codebase
(matches LOCK §2.5.2 exactly). This is the first non-UUID PK in
the model layer.

`contributes_to` is a Postgres `ARRAY(Text)` — first ARRAY column
in the codebase.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LeadSignalDefinition(Base):
    __tablename__ = "lead_signal_definition"
    __table_args__ = (
        CheckConstraint(
            "default_weight BETWEEN 0 AND 1",
            name="lead_signal_definition_default_weight_range",
        ),
    )

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    contributes_to: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
    )
    freshness_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    default_weight: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
    )
    default_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
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
