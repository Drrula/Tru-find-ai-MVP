"""VerticalPromptVersion model — versioned prompts per vertical.

Per ARCHITECTURE-LOCK §2.3 + ADR-020 (versioned prompts) + ADR-011 +
ADR-048 + ADR-047 (platform-owned).

Status lifecycle: 'draft' | 'active' | 'archived' (CHECK constraint).
Exactly-one-active per (vertical_id, prompt_key) is application
discipline; no partial unique index yet (zero prompt rows in B.3.3 —
the local_business_ai_visibility pack carries none).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class VerticalPromptVersion(Base):
    __tablename__ = "vertical_prompt_version"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','archived')",
            name="vertical_prompt_version_status_check",
        ),
        UniqueConstraint(
            "vertical_id",
            "prompt_key",
            "version",
            name="uq_vertical_prompt_version_natural",
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
    prompt_key: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    prompt_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String,
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
