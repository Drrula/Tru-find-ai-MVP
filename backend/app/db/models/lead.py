"""Lead model — the customer-owned lead record.

Per ARCHITECTURE-LOCK §2.5.1 + ADR-035 (lead intelligence first-class)
+ ADR-008 (tenancy via account_id) + ADR-013 (PII: hash + encrypted)
+ ADR-016 (soft-delete via deleted_at) + ADR-037 (lifecycle state
machine) + ADR-047 (customer-owned: exportable via
`/v1/account/export`).

Combines v1.2 + v1.3 columns. The Python-side `default='cold'` mirrors
the DB `server_default='cold'` so an unflushed Lead instance shows the
lifecycle attribute correctly at construction time — needed because
domain code reads `lead.lifecycle_state` before flush in some
read-after-write paths.

DEFERRED columns (per phase-b4-plan.md §2 #2): `business_id` and
`contact_phone_record_id`. Added by additive migrations per ADR-027
when their target tables ship.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class Lead(Base):
    """One row per lead. Customer-owned per ADR-047."""

    __tablename__ = "lead"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('cold','warm','engaged','qualified',"
            "'opportunity','customer','dormant','unsubscribed')",
            name="lead_lifecycle_state_check",
        ),
        Index(
            "ix_lead_account_id_active",
            "account_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_lead_account_vertical_active",
            "account_id",
            "vertical_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_lead_account_lifecycle_active",
            "account_id",
            "lifecycle_state",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_lead_email_hash_active",
            "email_hash",
            postgresql_where=text(
                "deleted_at IS NULL AND email_hash IS NOT NULL"
            ),
        ),
        Index(
            "ix_lead_phone_hash_active",
            "phone_hash",
            postgresql_where=text(
                "deleted_at IS NULL AND phone_hash IS NOT NULL"
            ),
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
    vertical_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vertical.id"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="cold",
        server_default="cold",
    )

    # PII columns per ADR-013. Nullable because not every lead has
    # both email and phone observed.
    email_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    email_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    phone_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    phone_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )

    # Consent fields. Defaults match the DB server_default ('false')
    # so unflushed instances reflect the explicit-opt-in posture.
    consent_sms: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    consent_email: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    consent_source: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    consent_ip_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_engaged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
