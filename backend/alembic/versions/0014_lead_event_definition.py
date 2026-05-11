"""lead_event_definition table — catalog of valid lead event types.

Per ARCHITECTURE-LOCK §2.5.3 + ADR-040 (definition-driven event
taxonomy) + ADR-047 (platform-owned: NOT exportable via
`/v1/account/export`).

Catalog of every lead event type the system knows about, versioned.
`lead_event` rows reference this table via `event_definition_id` FK,
so the catalog must hold an active row before any lead_event can be
written. Catalog rows are inserted by operator step (or B.4 test
fixtures) — no auto-seed at app startup in B.4.

UNIQUE (event_type, version) prevents accidental duplicates at the
natural key. Partial index on (event_type) WHERE status='active' is
the lookup path for `find_active_by_event_type`.

No `account_id` (platform-owned). No `deleted_at` — definitions
retire via `status='retired'`, not soft-delete.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014_lead_event_definition"
down_revision: Union[str, None] = "0013_lead"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_event_definition",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "default_weight",
            sa.Numeric(4, 3),
            nullable=False,
        ),
        sa.Column(
            "freshness_ttl_seconds",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payload_schema", postgresql.JSONB(), nullable=False),
        sa.Column(
            "lenient",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
            "status IN ('draft','active','retired')",
            name="lead_event_definition_status_check",
        ),
        sa.CheckConstraint(
            "default_weight BETWEEN 0 AND 1",
            name="lead_event_definition_default_weight_range",
        ),
        sa.UniqueConstraint(
            "event_type",
            "version",
            name="uq_lead_event_definition_natural",
        ),
    )
    # Partial index for the dominant lookup pattern: "active definition
    # for this event_type at the latest version".
    op.create_index(
        "ix_lead_event_definition_active",
        "lead_event_definition",
        ["event_type"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lead_event_definition_active",
        table_name="lead_event_definition",
    )
    op.drop_table("lead_event_definition")
