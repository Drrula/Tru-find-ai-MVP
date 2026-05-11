"""lead_score_snapshot table — append-only score time-series.

Per ARCHITECTURE-LOCK §2.5 + ADR-010 (immutable + reproducible) +
ADR-036 (lead signals + dimensions) + ADR-047 (customer-owned).

APPEND-ONLY by design: no `updated_at`, no `deleted_at`. Each call
to record a score writes a NEW row. The "current" score for a lead
is the row with the latest `computed_at` (tie-broken by `id DESC`,
matching the `lead_signal.find_current` pattern from B.4.3).

ADR-010 replay semantics:
- `weight_version_at` is the timestamp used by `compute_lead_score`
  (B.5.2) to resolve "active" rows in `vertical_lead_signal_weight`
  history. Stored on the snapshot so an operator can re-query the
  historical weights via `WHERE effective_from <= weight_version_at
  AND (effective_to IS NULL OR effective_to > weight_version_at)`.
- `inputs` is a frozen JSONB copy of the `lead_signal` observations
  the score was computed from.
- Together: same `weight_version_at` + same `inputs` + same scoring
  logic = same score. Snapshots are replayable.

The CHECK constraint `score BETWEEN 0 AND 100` enforces range at DB
(numeric(5,2) alone would allow up to 999.99).

Two indexes per phase-b5-plan.md §5:
- (lead_id, computed_at DESC) — "latest score for this lead"
- (account_id, vertical_id, computed_at DESC) — account-wide history
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0019_lead_score_snapshot"
down_revision: Union[str, None] = "0018_vertical_lead_signal_weight"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_score_snapshot",
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
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=False),
        sa.Column(
            "weight_version_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column(
            "computed_at",
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
            "score BETWEEN 0 AND 100",
            name="lead_score_snapshot_score_range",
        ),
    )
    # "Latest score for this lead" — backs find_current_for_lead
    # and find_history_for_lead.
    op.create_index(
        "ix_lead_score_snapshot_lead_computed",
        "lead_score_snapshot",
        ["lead_id", sa.text("computed_at DESC")],
    )
    # Account-wide score history scoped to a vertical — backs
    # find_for_account_vertical.
    op.create_index(
        "ix_lead_score_snapshot_account_vertical_computed",
        "lead_score_snapshot",
        ["account_id", "vertical_id", sa.text("computed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lead_score_snapshot_account_vertical_computed",
        table_name="lead_score_snapshot",
    )
    op.drop_index(
        "ix_lead_score_snapshot_lead_computed",
        table_name="lead_score_snapshot",
    )
    op.drop_table("lead_score_snapshot")
