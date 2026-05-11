"""vertical_template table — named JSON config blobs per vertical.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-048. Platform-owned
(per ADR-047).

Stores arbitrary JSON configuration keyed by `(vertical_id, name)`.
The seed utility uses three named templates:
- `tier_thresholds` — list of `(min_score, tier_name)` tuples.
- `competitor_pool` — list of competitor name strings.
- `category_mapping` — `signal_name -> presentation_category` dict.

UNIQUE(vertical_id, name) enforces one template per name per vertical.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_vertical_template"
down_revision: Union[str, None] = "0009_vertical_copy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertical_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
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
        sa.UniqueConstraint(
            "vertical_id", "name", name="uq_vertical_template_name"
        ),
    )


def downgrade() -> None:
    op.drop_table("vertical_template")
