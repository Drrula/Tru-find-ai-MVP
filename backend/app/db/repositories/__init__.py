"""Repository pattern boundary for DB access.

Per ADR-031: every read or write that touches the database goes through
a repository. Domain code receives a session via `Depends(get_session)`,
constructs a repository, and calls its methods. Domain code never
imports SQLAlchemy directly, never writes raw SQL, never executes a
session statement.

`BaseRepository` provides default tenancy + soft-delete filtering driven
by introspecting the model's columns. Subclasses (one per aggregate
root) add domain-specific operations.
"""

from __future__ import annotations

from app.db.repositories.account_repo import AccountRepository
from app.db.repositories.base import BaseRepository

__all__ = ["BaseRepository", "AccountRepository"]
