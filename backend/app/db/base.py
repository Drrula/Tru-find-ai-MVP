"""SQLAlchemy declarative base.

Per docs/phase-b-plan.md §3. Single `Base` class for all model declarations
across the project. ORM models live under `app.db.models.*` and inherit
from this Base; they never live in `app.domain.*` (per ADR-007).

Per ADR-031, domain modules access the database only through repositories
(`app.db.repositories.*`), which receive an `AsyncSession` injected by
the FastAPI dependency. Domain code never imports this Base directly.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models in the project."""
