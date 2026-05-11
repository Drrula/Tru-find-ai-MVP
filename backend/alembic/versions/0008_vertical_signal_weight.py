"""vertical_signal_weight table — per-vertical signal weights with history.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 + ADR-048. Platform-owned (per
ADR-047).

`effective_from` allows weight history: multiple rows for the same
(vertical_id, signal_name) at different times. The "current" weight
is the row with the latest `effective_from <= now()`. The UNIQUE
constraint on (vertical_id, signal_name, effective_from) prevents
two rows from claiming the same effective_from for the same signal.

B.3.3 seeds initial rows from the pack; B.3.4 wires the scoring
engine to read from this table.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008_vertical_signal_weight"
down_revision: Union[str, None] = "0007_vertical"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertical_signal_weight",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=False,
        ),
        sa.Column("signal_name", sa.String(), nullable=False),
        sa.Column("weight", sa.Numeric(), nullable=False),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
        sa.UniqueConstraint(
            "vertical_id",
            "signal_name",
            "effective_from",
            name="uq_vertical_signal_weight_history",
        ),
    )
    # Index on (vertical_id, signal_name) for the "current weight"
    # lookup pattern; effective_from ordering handled at query time.
    op.create_index(
        "ix_vertical_signal_weight_vertical_signal",
        "vertical_signal_weight",
        ["vertical_id", "signal_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vertical_signal_weight_vertical_signal",
        table_name="vertical_signal_weight",
    )
    op.drop_table("vertical_signal_weight")
