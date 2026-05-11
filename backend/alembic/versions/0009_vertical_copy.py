"""vertical_copy table — locale-keyed user-visible strings per vertical.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-046 (locale-keyed
schema — copy is never US/English-only) + ADR-048. Platform-owned
(per ADR-047).

Three-tuple natural key: (vertical_id, locale, key). The UNIQUE
constraint guarantees one text per (vertical, locale, key).
Re-seeding a changed pack would require explicit UPSERT semantics
which B.3.3 does not implement — the seed utility is idempotent by
pack_id and skips re-population.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009_vertical_copy"
down_revision: Union[str, None] = "0008_vertical_signal_weight"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertical_copy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
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
            "vertical_id", "locale", "key", name="uq_vertical_copy_key"
        ),
    )
    # Lookup pattern: WHERE vertical_id = :vid AND locale = :loc AND key = :k.
    # The UNIQUE constraint above auto-creates a backing index that covers
    # this; no additional index needed.


def downgrade() -> None:
    op.drop_table("vertical_copy")
