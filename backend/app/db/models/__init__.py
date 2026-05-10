"""ORM models package.

All model modules under `app.db.models` register classes against
`app.db.base.Base` via SQLAlchemy's DeclarativeBase metaclass. Importing
this package (or any of its members) is what makes models visible to
alembic's `target_metadata` during autogenerate — see `alembic/env.py`.

Per docs/phase-b-plan.md §5 + ADR-031: domain code never imports from
here. Repositories under `app.db.repositories` (B.1.5) are the only
public surface for DB access.
"""

from __future__ import annotations

from app.db.models.account import Account

__all__ = ["Account"]
