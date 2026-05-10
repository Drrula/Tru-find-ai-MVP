"""account table — the tenancy root.

Per ADR-008 (tenancy root; every owned/derived row carries account_id
referencing here), ADR-033 (UUIDv7 PK), and ARCHITECTURE-LOCK §2.3
(column spec). First real migration; chains from the empty 0001_baseline.

UUIDv7 generation is application-side via `app.core.ids.new_id` (the
ORM model's Python default). The migration creates the column without
a server-side UUID default — Postgres receives the UUID from the
application on every INSERT.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_account"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column(
            "parent_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="active",
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
            "status IN ('active','suspended','closed')",
            name="account_status_check",
        ),
    )
    # Partial index per Lock §2.3: only rows where parent_account_id IS NOT NULL.
    op.create_index(
        "ix_account_parent_account_id",
        "account",
        ["parent_account_id"],
        postgresql_where=sa.text("parent_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_account_parent_account_id", table_name="account")
    op.drop_table("account")
