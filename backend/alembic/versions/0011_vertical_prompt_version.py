"""vertical_prompt_version table — versioned prompts per vertical.

Per ARCHITECTURE-LOCK §2.3 + ADR-020 (versioned prompts as DB rows)
+ ADR-011 + ADR-048. Platform-owned (per ADR-047).

Status lifecycle (CHECK constraint):
- `draft`     — author iterating; not used by runtime.
- `active`    — the prompt the engine currently resolves to.
- `archived`  — historical record; not resolved by runtime.

Exactly-one-active per (vertical_id, prompt_key) is application
discipline, NOT enforced by a partial unique index in B.3.3 (deferred
until prompt-management UI lands; today there are zero prompt rows
because the local_business_ai_visibility pack carries none).

UNIQUE(vertical_id, prompt_key, version) prevents collisions on
the natural key.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011_vertical_prompt_version"
down_revision: Union[str, None] = "0010_vertical_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertical_prompt_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=False,
        ),
        sa.Column("prompt_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('draft','active','archived')",
            name="vertical_prompt_version_status_check",
        ),
        sa.UniqueConstraint(
            "vertical_id",
            "prompt_key",
            "version",
            name="uq_vertical_prompt_version_natural",
        ),
    )


def downgrade() -> None:
    op.drop_table("vertical_prompt_version")
