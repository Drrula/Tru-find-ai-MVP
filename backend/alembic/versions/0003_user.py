"""user table — first table to enforce tenancy via account_id.

Per ARCHITECTURE-LOCK §2.3 + ADR-008 (account_id NOT NULL FK to
account.id), ADR-013 (PII columns: email_hash for indexed lookup,
email_encrypted for AES-256-GCM ciphertext), ADR-016 (soft-delete via
deleted_at; partial unique index excludes soft-deleted rows so
re-signup with a previously-deleted email succeeds), ADR-018 (DIY
magic-link auth; external_auth_id reserved for the future
hosted-provider escape hatch — column lands here, no value set in
B.2), and ADR-033 (UUIDv7 PK, application-side).

Note: "user" is reserved in PostgreSQL. SQLAlchemy + alembic auto-quote
reserved identifiers via the dialect's IdentifierPreparer, so the
generated DDL/DML will reference "user" with quotes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_user"
down_revision: Union[str, None] = "0002_account"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id"),
            nullable=False,
        ),
        sa.Column("email_hash", sa.LargeBinary(), nullable=False),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("external_auth_id", sa.String(), nullable=True),
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default="owner",
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "role IN ('owner','admin','member')",
            name="user_role_check",
        ),
    )
    # Partial unique index per Lock §2.3: enforce email uniqueness only
    # over non-soft-deleted rows so re-signup after soft-delete works.
    op.create_index(
        "ix_user_email_hash_active",
        "user",
        ["email_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Plain index on account_id for tenancy-scoped lookups.
    op.create_index(
        "ix_user_account_id",
        "user",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_account_id", table_name="user")
    op.drop_index("ix_user_email_hash_active", table_name="user")
    op.drop_table("user")
