"""vertical_lead_signal_weight table — per-vertical signal weights
with effective_from/effective_to history.

Per ARCHITECTURE-LOCK §2.5.2 + ADR-011 (verticals are data, not
code) + ADR-036 + ADR-047 (platform-owned).

Weight history: each row has an explicit `effective_from`. When
retiring a weight, `effective_to` is set on the active row (one-line
UPDATE via `VerticalLeadSignalWeightRepository.close_active`).
The "active" weight for `(vertical_id, signal_name, dimension)` is
the row with the latest `effective_from` AND `effective_to IS NULL`.

UNIQUE (vertical_id, signal_name, dimension, effective_from)
prevents accidental duplicate-start entries.

No `account_id` (platform-owned). No `deleted_at` (retirement via
effective_to, not soft-delete).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0018_vertical_lead_signal_weight"
down_revision: Union[str, None] = "0017_lead_signal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertical_lead_signal_weight",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=False,
        ),
        sa.Column(
            "signal_name",
            sa.Text(),
            sa.ForeignKey("lead_signal_definition.name"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(), nullable=False),
        sa.Column(
            "weight",
            sa.Numeric(4, 3),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "effective_to",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "weight BETWEEN 0 AND 1",
            name="vertical_lead_signal_weight_range",
        ),
        sa.UniqueConstraint(
            "vertical_id",
            "signal_name",
            "dimension",
            "effective_from",
            name="uq_vertical_lead_signal_weight_history",
        ),
    )
    # Backs find_active lookups.
    op.create_index(
        "ix_vertical_lead_signal_weight_lookup",
        "vertical_lead_signal_weight",
        ["vertical_id", "signal_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vertical_lead_signal_weight_lookup",
        table_name="vertical_lead_signal_weight",
    )
    op.drop_table("vertical_lead_signal_weight")
