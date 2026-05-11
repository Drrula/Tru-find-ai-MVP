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
from app.db.models.lead import Lead
from app.db.models.magic_link_token import MagicLinkToken
from app.db.models.session import UserSession
from app.db.models.user import User
from app.db.models.vertical import Vertical
from app.db.models.vertical_copy import VerticalCopy
from app.db.models.vertical_prompt_version import VerticalPromptVersion
from app.db.models.vertical_signal_weight import VerticalSignalWeight
from app.db.models.vertical_template import VerticalTemplate

__all__ = [
    "Account",
    "Lead",
    "MagicLinkToken",
    "User",
    "UserSession",
    "Vertical",
    "VerticalCopy",
    "VerticalPromptVersion",
    "VerticalSignalWeight",
    "VerticalTemplate",
]
