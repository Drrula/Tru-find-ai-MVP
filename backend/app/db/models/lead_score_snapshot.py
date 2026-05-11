"""LeadScoreSnapshot model — append-only score time-series.

Per ARCHITECTURE-LOCK §2.5 + ADR-010 (immutable + reproducible) +
ADR-036 (lead signals + dimensions) + ADR-047 (customer-owned:
exportable via `/v1/account/export`).

APPEND-ONLY: no `updated_at`, no `deleted_at`. Each scoring
computation writes a NEW row; the timeline is immutable.
BaseRepository.soft_delete naturally refuses (no deleted_at column).

The `weight_version_at` column + frozen `inputs` payload together
provide ADR-010 replay semantics: same inputs + same weight version
= same score, deterministically.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class LeadScoreSnapshot(Base):
    __tablename__ = "lead_score_snapshot"
    __table_args__ = (
        CheckConstraint(
            "score BETWEEN 0 AND 100",
            name="lead_score_snapshot_score_range",
        ),
        Index(
            "ix_lead_score_snapshot_lead_computed",
            "lead_id",
            text("computed_at DESC"),
        ),
        Index(
            "ix_lead_score_snapshot_account_vertical_computed",
            "account_id",
            "vertical_id",
            text("computed_at DESC"),
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
    vertical_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vertical.id"),
        nullable=False,
    )
    score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    #: Full audit of how the score was computed: per-signal
    #: contributions, per-dimension contributions, weights, total
    #: weight, unobserved signals. Numerics serialized as strings to
    #: preserve Decimal precision through JSONB round-trip.
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    #: The timestamp used to resolve "active" rows in
    #: vertical_lead_signal_weight history at compute time. Stored
    #: so an operator can re-query the historical weights and verify
    #: the score replays deterministically.
    weight_version_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    #: Frozen JSONB copy of the lead_signal observations the score
    #: was computed from. Replay-safe.
    inputs: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
