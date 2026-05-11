"""lead_event table — append-only event timeline per lead.

Per ARCHITECTURE-LOCK §2.5.3 + ADR-035 (lead intelligence
first-class) + ADR-040 (definition-driven event taxonomy) +
ADR-044 (canonical event envelope — `lead_event` is the projection
table for events with `target_table='lead_event'`) + ADR-047
(customer-owned: exportable via `/v1/account/export`).

APPEND-ONLY by design: no `updated_at`, no `deleted_at`. Domain
code records a lead_event row once at occurrence time; the timeline
never mutates. BaseRepository.soft_delete naturally refuses
(no deleted_at column).

`occurred_at` vs `recorded_at`:
- occurred_at: when the actual event happened (can be in the past
  for backfill imports).
- recorded_at: when the system became aware of it (>= occurred_at,
  usually equal at real-time recording).

FK to `lead_event_definition` enforces that every event_type +
version pair was registered in the catalog before any row using
it can be written. Two indexes for the dominant query patterns:
"timeline for one lead" and "events of one type within an account".
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015_lead_event"
down_revision: Union[str, None] = "0014_lead_event_definition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "event_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead_event_definition.id"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("actor_kind", sa.String(), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user','system','webhook','job','ai')",
            name="lead_event_actor_kind_check",
        ),
    )
    # Timeline for one lead: ORDER BY occurred_at DESC.
    op.create_index(
        "ix_lead_event_lead_occurred",
        "lead_event",
        ["lead_id", sa.text("occurred_at DESC")],
    )
    # Events of one type across an account: ORDER BY occurred_at DESC.
    op.create_index(
        "ix_lead_event_account_type_occurred",
        "lead_event",
        ["account_id", "event_type", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lead_event_account_type_occurred", table_name="lead_event"
    )
    op.drop_index("ix_lead_event_lead_occurred", table_name="lead_event")
    op.drop_table("lead_event")
