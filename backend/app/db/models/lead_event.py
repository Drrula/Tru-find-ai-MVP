"""LeadEvent model — append-only event timeline per lead.

Per ARCHITECTURE-LOCK §2.5.3 + ADR-035 + ADR-040 + ADR-044 +
ADR-047 (customer-owned: exportable via `/v1/account/export`).

APPEND-ONLY: no `updated_at`, no `deleted_at`. The timeline is
immutable. BaseRepository.soft_delete refuses (no deleted_at column).
Domain code records a row at occurrence time; nothing mutates after.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class LeadEvent(Base):
    __tablename__ = "lead_event"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user','system','webhook','job','ai')",
            name="lead_event_actor_kind_check",
        ),
        Index(
            "ix_lead_event_lead_occurred",
            "lead_id",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_lead_event_account_type_occurred",
            "account_id",
            "event_type",
            text("occurred_at DESC"),
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
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead.id"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_definition_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead_event_definition.id"),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
