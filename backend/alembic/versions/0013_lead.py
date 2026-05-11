"""lead table — the customer-owned lead record.

Per ARCHITECTURE-LOCK §2.5.1 + ADR-035 (lead intelligence first-class)
+ ADR-008 (tenancy via account_id) + ADR-013 (PII as hash + encrypted)
+ ADR-016 (soft-delete via deleted_at) + ADR-037 (lifecycle state
machine) + ADR-047 (customer-owned: exportable via
`/v1/account/export` when implementation lands).

Combines v1.2 + v1.3 columns in a single CREATE TABLE (no
ALTER-from-prior-shape needed since v1.2 lead table never existed).

DEFERRED columns (per phase-b4-plan.md §2 #2): `business_id` and
`contact_phone_record_id`. Target tables (`business`, `phone_record`)
don't exist yet; adding nullable FK-less placeholders risks orphan
drift. Added by additive migrations per ADR-027 when those tables
ship.

Lifecycle states (per ADR-037): closed enum of 8 states. DB CHECK
enforces the enum; Python-side `app.domain.leads.lifecycle.LIFECYCLE_STATES`
mirrors it (lands in B.4.4). Default `'cold'`.

Five partial indexes per §4 — all gated on `deleted_at IS NULL` so
soft-deleted leads don't bloat the active-lookup paths.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013_lead"
down_revision: Union[str, None] = "0012_account_region"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id"),
            nullable=False,
        ),
        sa.Column(
            "vertical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vertical.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "lifecycle_state",
            sa.String(),
            nullable=False,
            server_default="cold",
        ),
        sa.Column("email_hash", sa.LargeBinary(), nullable=True),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("phone_hash", sa.LargeBinary(), nullable=True),
        sa.Column("phone_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "consent_sms",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "consent_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("consent_source", sa.String(), nullable=True),
        sa.Column(
            "consent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("consent_ip_hash", sa.LargeBinary(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_engaged_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('cold','warm','engaged','qualified',"
            "'opportunity','customer','dormant','unsubscribed')",
            name="lead_lifecycle_state_check",
        ),
    )
    # Five partial indexes per phase-b4-plan.md §4. All gated on
    # deleted_at IS NULL so soft-deleted rows stay out of active
    # query paths.
    op.create_index(
        "ix_lead_account_id_active",
        "lead",
        ["account_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_lead_account_vertical_active",
        "lead",
        ["account_id", "vertical_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_lead_account_lifecycle_active",
        "lead",
        ["account_id", "lifecycle_state"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_lead_email_hash_active",
        "lead",
        ["email_hash"],
        postgresql_where=sa.text(
            "deleted_at IS NULL AND email_hash IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_lead_phone_hash_active",
        "lead",
        ["phone_hash"],
        postgresql_where=sa.text(
            "deleted_at IS NULL AND phone_hash IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_lead_phone_hash_active", table_name="lead")
    op.drop_index("ix_lead_email_hash_active", table_name="lead")
    op.drop_index("ix_lead_account_lifecycle_active", table_name="lead")
    op.drop_index("ix_lead_account_vertical_active", table_name="lead")
    op.drop_index("ix_lead_account_id_active", table_name="lead")
    op.drop_table("lead")
