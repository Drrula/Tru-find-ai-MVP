"""MagicLinkToken model — pre-account-binding bearer tokens for auth.

Per ARCHITECTURE-LOCK §2.3, ADR-018 (DIY magic-link auth) + ADR-032
(token_hash is the idempotency key; UNIQUE — see UniqueConstraint
below).

Intentionally pre-account: this model carries `email_hash` only, not
`account_id`. The consume step (B.2.3) resolves the email_hash to an
existing user (and reuses that user's account) or self-signs-up a new
account+user. Adding `account_id` here would require inventing it
during the request half of the flow before we know what account the
email belongs to.

email_encrypted (added in B.2.2-amend / migration 0006) stores the
AES-256-GCM ciphertext of the plaintext email — set by issue at
request time, decrypted by consume to recover the local-part-of-email
display_name and the email_encrypted value to write to the user row
during self-signup. Per ADR-013, the email is never plaintext at rest
and never appears in URLs.

token_hash stores sha256(plaintext_token). The plaintext only ever
exists in the email body; nothing in the DB can recover it. UNIQUE
constraint covers deduplication and idempotency (per ADR-032).

Soft-consume via `consumed_at` (nullable) — explicit consume
semantics, not soft-delete. BaseRepository's deleted_at-based
soft-delete filter does not apply here (column does not exist).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    LargeBinary,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class MagicLinkToken(Base):
    """An outstanding (or consumed) magic-link token."""

    __tablename__ = "magic_link_token"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_magic_link_token_hash"),
        Index(
            "ix_magic_link_token_active",
            "token_hash",
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    email_hash: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    email_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ip_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
