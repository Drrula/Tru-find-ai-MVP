"""LeadSignal model — append-only signal observations per lead.

Per ARCHITECTURE-LOCK §2.5.2 + ADR-036 + ADR-010 analog + ADR-047
(customer-owned: exportable via `/v1/account/export`).

APPEND-ONLY: no `updated_at`, no `deleted_at`. Each call to record
a signal writes a NEW row. The "current value" is resolved at read
time via `LeadSignalRepository.find_current` (latest observed_at
per (lead_id, signal_name)).

`signal_name` is the FK to `lead_signal_definition.name` (text, per
the catalog's non-UUID PK choice).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class LeadSignal(Base):
    __tablename__ = "lead_signal"
    __table_args__ = (
        Index(
            "ix_lead_signal_lead_name_observed",
            "lead_id",
            "signal_name",
            text("observed_at DESC"),
        ),
        Index(
            "ix_lead_signal_account_observed",
            "account_id",
            text("observed_at DESC"),
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
    signal_name: Mapped[str] = mapped_column(
        Text,
        ForeignKey("lead_signal_definition.name"),
        nullable=False,
    )
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    observed_at: Mapped[datetime] = mapped_column(
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
