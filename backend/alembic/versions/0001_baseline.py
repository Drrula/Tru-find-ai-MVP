"""Empty baseline migration.

Establishes the `alembic_version` tracking table without any schema
change. The first real table (`account`) lands in `0002_account.py`
per docs/phase-b-plan.md §9.

Per ADR-027 (additive between deploys): every B.X migration is a single
logical change; destructive operations split into expand → migrate →
contract. This empty baseline carries no schema risk.
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op. Baseline only registers the alembic_version row."""
    pass


def downgrade() -> None:
    """No-op. Baseline cannot be reverted (it IS the empty state)."""
    pass
