"""lead_signal table — append-only signal observations per lead.

Per ARCHITECTURE-LOCK §2.5.2 + ADR-036 + ADR-010 analog (immutable +
reproducible per-observation rows) + ADR-047 (customer-owned).

APPEND-ONLY: no `updated_at`, no `deleted_at`. Each call to record
a signal writes a NEW row; the "current value" is the row with the
latest `observed_at` per `(lead_id, signal_name)` — resolved at read
time by `LeadSignalRepository.find_current`.

FK to `lead_signal_definition.name` ensures every signal_name is in
the catalog. `value` is JSONB — flexible payload per signal_kind.

`observed_at` vs `recorded_at`:
- observed_at: when the actual observation happened (can be in the
  past for backfilled signals).
- recorded_at: when the system became aware of it (>= observed_at).

Two indexes per LOCK §2.5.2:
- (lead_id, signal_name, observed_at DESC) -- backs find_current +
  find_history.
- (account_id, observed_at DESC) -- durable index for future
  account-wide signal-history queries; no B.4.3 method uses it yet.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0017_lead_signal"
down_revision: Union[str, None] = "0016_lead_signal_definition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_signal",
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
            "signal_name",
            sa.Text(),
            sa.ForeignKey("lead_signal_definition.name"),
            nullable=False,
        ),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "source_ref_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "observed_at",
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
    )
    # Backs find_current + find_history.
    op.create_index(
        "ix_lead_signal_lead_name_observed",
        "lead_signal",
        ["lead_id", "signal_name", sa.text("observed_at DESC")],
    )
    # Durable index for future account-wide signal queries.
    op.create_index(
        "ix_lead_signal_account_observed",
        "lead_signal",
        ["account_id", sa.text("observed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_signal_account_observed", table_name="lead_signal")
    op.drop_index(
        "ix_lead_signal_lead_name_observed", table_name="lead_signal"
    )
    op.drop_table("lead_signal")
