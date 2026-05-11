"""vertical table — config root for each vertical pack.

Per ARCHITECTURE-LOCK §2.3 + ADR-011 (verticals as data, not code) +
ADR-048 (pack lifecycle). Platform-owned (per ADR-047): no
account_id; vertical_* config is platform IP, not customer data.

Soft-delete is NOT used here — verticals follow a version-and-replace
lifecycle (bump `schema_version`, re-seed) rather than soft-delete.
The `created_at` / `updated_at` columns cover audit needs; admin
hard-delete is a rare operation handled out-of-band.

B.3.3 lands the schema; B.3.4 wires the scoring engine to read from
these tables via repositories. Until then, the scoring engine reads
from the pack module (`app/vertical/packs/<pack_id>/`) and these
rows are aspirational — populated by the seed utility but not yet
consumed at runtime.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_vertical"
down_revision: Union[str, None] = "0006_magic_link_token_email_encrypted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertical",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint("pack_id", name="uq_vertical_pack_id"),
    )


def downgrade() -> None:
    op.drop_table("vertical")
