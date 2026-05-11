"""lead_signal_definition table — catalog of valid lead signal names.

Per ARCHITECTURE-LOCK §2.5.2 + ADR-036 (lead signals + dimensions +
explainability) + ADR-047 (platform-owned: NOT exportable).

Catalog of every signal name the system knows about. `lead_signal`
rows and `vertical_lead_signal_weight` rows reference this table via
`signal_name` FK (text, NOT a UUID — the natural key IS the name,
matching how signals are referenced throughout the codebase). This
diverges from the UUIDv7-PK convention used elsewhere; the choice
matches LOCK §2.5.2 exactly.

`contributes_to` is a Postgres `text[]` (first ARRAY column in the
codebase) listing the dimension names this signal feeds into.

NOT account-scoped; no soft-delete column. Retirement via setting
`default_enabled = false` rather than deletion.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0016_lead_signal_definition"
down_revision: Union[str, None] = "0015_lead_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_signal_definition",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "contributes_to",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "freshness_ttl_seconds",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column(
            "default_weight",
            sa.Numeric(4, 3),
            nullable=False,
        ),
        sa.Column(
            "default_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.CheckConstraint(
            "default_weight BETWEEN 0 AND 1",
            name="lead_signal_definition_default_weight_range",
        ),
    )


def downgrade() -> None:
    op.drop_table("lead_signal_definition")
