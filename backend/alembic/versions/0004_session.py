"""session table — issued bearer rows backing the HttpOnly cookie.

Per ARCHITECTURE-LOCK §2.3 + ADR-008 (account_id denormalized from
user.account_id so session-scoped reads avoid a join — set at
creation, never updated), ADR-018 (DB-backed sessions, the cookie
carries session.id signed by SESSION_SECRET), and ADR-033 (UUIDv7 PK).

Soft-revoke via revoked_at (nullable) per the Lock; deliberately NOT
named deleted_at — sessions have explicit revoke semantics, not
soft-delete semantics.

ip_hash stores sha256(client_ip) (32 bytes). Plaintext IP is never
persisted (per ADR-013 PII posture).

user_agent is truncated to 256 chars at write time (write-side
discipline, not a column-length CHECK — keeps the column flexible if a
future migration ever needs to widen).

Note: account_id has an explicit FK to account.id even though the Lock
spec text only says "NOT NULL". Referential integrity at the DB layer
is cheap insurance; the tenancy filter still works without it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_session"
down_revision: Union[str, None] = "0003_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id"),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("ip_hash", sa.LargeBinary(), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
    )
    # Composite index per Lock §2.3: optimizes the dominant query
    # ("active sessions for this user" — sorts by expiry).
    op.create_index(
        "ix_session_user_id_expires_at",
        "session",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_user_id_expires_at", table_name="session")
    op.drop_table("session")
