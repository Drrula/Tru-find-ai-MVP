"""Add email_encrypted column to magic_link_token.

B.2.2-amend: a design gap surfaced during B.2.3 planning. The locked
flow says self-signup at consume time creates a user with
`email_encrypted` and an account whose `display_name = local part of
email` (per docs/phase-b2-plan.md §4 + decision #6) — but consume
only has the opaque token from the URL, no plaintext email. The fix:
store the encrypted email on the magic_link_token row at issue time
so consume can decrypt and recover it.

Per ADR-013 PII posture preserved: the email is still never plaintext
at rest (AES-256-GCM ciphertext via app.core.crypto.encrypt) and never
in URLs (only the opaque token is in the consume URL).

Per ADR-027 (additive between deploys): NOT NULL is safe here because
B.2.2 (which created this table) has not deployed to staging or
production yet — the table is empty wherever this migration runs, and
adding a NOT NULL column to an empty table is a single-statement
DDL with no backfill.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_magic_link_token_email_encrypted"
down_revision: Union[str, None] = "0005_magic_link_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "magic_link_token",
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("magic_link_token", "email_encrypted")
