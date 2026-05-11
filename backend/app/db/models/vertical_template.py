"""VerticalTemplate model — named JSON config blobs per vertical.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-048 + ADR-047
(platform-owned). Stores arbitrary JSON keyed by (vertical_id, name).

Seed-utility template names:
- `tier_thresholds`   — list of (min_score, tier_name) pairs
- `competitor_pool`   — list of competitor name strings
- `category_mapping`  — signal_name -> presentation_category dict
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class VerticalTemplate(Base):
    __tablename__ = "vertical_template"
    __table_args__ = (
        UniqueConstraint(
            "vertical_id", "name", name="uq_vertical_template_name"
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
    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
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
