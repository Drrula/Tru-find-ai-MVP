"""magic_link_token table — pre-account-binding bearer tokens.

Per ARCHITECTURE-LOCK §2.3 + ADR-018 (DIY magic-link auth) + ADR-032
(token_hash is the idempotency key; UNIQUE).

Intentionally pre-account: this table carries email_hash only, not
account_id. The consume step (B.2.3) resolves the email_hash to an
existing user (and reuses that user's account) or self-signs-up a new
account+user. Any account_id on this table would have to be invented
during the request half of the flow before we know what account the
user belongs to.

token_hash stores sha256(plaintext_token). The plaintext only ever
exists in the email body (and briefly in app memory between mint and
send). UNIQUE constraint covers both deduplication and idempotency
(per ADR-032).

Soft-consume via consumed_at (nullable). The partial index on
token_hash WHERE consumed_at IS NULL keeps the active-token lookup
small while still allowing historical queries against consumed rows.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_magic_link_token"
down_revision: Union[str, None] = "0004_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "magic_link_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_hash", sa.LargeBinary(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("ip_hash", sa.LargeBinary(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_magic_link_token_hash"),
    )
    # Partial index per Lock §2.3: keeps the active-token lookup small.
    op.create_index(
        "ix_magic_link_token_active",
        "magic_link_token",
        ["token_hash"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_magic_link_token_active", table_name="magic_link_token")
    op.drop_table("magic_link_token")
