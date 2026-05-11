"""Add `region` column to `account` (per ADR-046).

B.3.5: the multi-region commitment becomes load-bearing at the
logical layer. `account.region` is informational only in B.3 — no
routing, no replication, no cross-region anything. Future commits
(post-B.3) will read this column to drive region-aware behavior.

Allowlist `{'us', 'ca', 'uk'}` reflects the three regions named
explicitly in the Platform Directive v1. Adding a new region is a
follow-up migration (additive: extend the CHECK constraint).

ADR-027 (additive between deploys) satisfied: NOT NULL with
`server_default='us'` backfills every existing row in one DDL
statement, no multi-step expand/migrate/contract needed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_account_region"
down_revision: Union[str, None] = "0011_vertical_prompt_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account",
        sa.Column(
            "region",
            sa.String(),
            nullable=False,
            server_default="us",
        ),
    )
    op.create_check_constraint(
        "account_region_check",
        "account",
        "region IN ('us','ca','uk')",
    )


def downgrade() -> None:
    op.drop_constraint("account_region_check", "account", type_="check")
    op.drop_column("account", "region")
