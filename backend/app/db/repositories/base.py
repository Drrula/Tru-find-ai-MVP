"""Base repository — tenancy + soft-delete filters via column introspection.

Per ADR-031, ADR-008 (tenancy via `account_id`), ADR-016 (soft-delete via
`deleted_at`). The base inspects the model's column set:

- If the model has an `account_id` column, every read filters by
  `account_id == self.account_id`. Constructor REQUIRES `account_id`
  for such models; passing `None` raises a `ValueError` at first read
  unless `force_cross_account=True` (audited bypass).

- If the model has a `deleted_at` column, every read filters out rows
  where `deleted_at IS NOT NULL`. Caller can opt in via
  `force_include_deleted=True` (audited bypass).

For models WITHOUT either column (e.g. `Account` itself, or system
tables like `external_cache`), the corresponding filter is naturally
skipped — no subclass override needed.

Force-bypass kwargs exist as escape hatches. Phase B+ will add
`audit_log` writes when these are used; for B.1.5 they're plumbed but
unaudited.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class BaseRepository[ModelT: Base]:
    """Generic repository over a SQLAlchemy model.

    Subclasses set `model_class` (a class attribute) and add
    domain-specific methods. The base provides primitive operations
    (get / find_one / find_many / add / soft_delete) with default
    tenancy + soft-delete filtering applied automatically.
    """

    # Set by subclasses, e.g. `model_class = Account`.
    model_class: type[ModelT]

    def __init__(self, session: AsyncSession, account_id: UUID | None) -> None:
        """Construct.

        Args:
            session: an AsyncSession (typically from `get_session()` dependency).
            account_id: the tenant scope. Required for models with an
                `account_id` column unless `force_cross_account=True` is
                used at the call site. Pass `None` only for system
                contexts (audit log writes, system events).
        """
        self.session = session
        self.account_id = account_id

    # --- Column introspection (cached at the class level via __table__).

    @property
    def _has_account_id_column(self) -> bool:
        return "account_id" in {c.name for c in self.model_class.__table__.columns}

    @property
    def _has_deleted_at_column(self) -> bool:
        return "deleted_at" in {c.name for c in self.model_class.__table__.columns}

    # --- Statement construction with default filters.

    def _base_select(
        self,
        *,
        force_include_deleted: bool = False,
        force_cross_account: bool = False,
    ) -> Any:
        """Build a SELECT with tenancy + soft-delete filters applied."""
        stmt = select(self.model_class)

        # Tenancy filter (ADR-008).
        if self._has_account_id_column and not force_cross_account:
            if self.account_id is None:
                raise ValueError(
                    f"{type(self).__name__} requires account_id to read "
                    f"{self.model_class.__name__}; pass an account_id or set "
                    "force_cross_account=True (audited bypass)."
                )
            stmt = stmt.where(self.model_class.account_id == self.account_id)  # type: ignore[attr-defined]

        # Soft-delete filter (ADR-016).
        if self._has_deleted_at_column and not force_include_deleted:
            stmt = stmt.where(self.model_class.deleted_at.is_(None))  # type: ignore[attr-defined]

        return stmt

    # --- Primitive operations.

    async def get(
        self,
        id: UUID,
        *,
        force_include_deleted: bool = False,
    ) -> ModelT | None:
        """Fetch a single row by primary key."""
        stmt = self._base_select(
            force_include_deleted=force_include_deleted,
        ).where(self.model_class.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_one(
        self,
        *,
        force_include_deleted: bool = False,
        force_cross_account: bool = False,
        **filters: Any,
    ) -> ModelT | None:
        """Fetch a single row matching the given column filters."""
        stmt = self._base_select(
            force_include_deleted=force_include_deleted,
            force_cross_account=force_cross_account,
        )
        for col_name, value in filters.items():
            stmt = stmt.where(getattr(self.model_class, col_name) == value)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_many(
        self,
        *,
        force_include_deleted: bool = False,
        force_cross_account: bool = False,
        **filters: Any,
    ) -> list[ModelT]:
        """Fetch all rows matching the given column filters."""
        stmt = self._base_select(
            force_include_deleted=force_include_deleted,
            force_cross_account=force_cross_account,
        )
        for col_name, value in filters.items():
            stmt = stmt.where(getattr(self.model_class, col_name) == value)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def add(self, model: ModelT) -> None:
        """Stage a new model for INSERT on the next flush/commit."""
        self.session.add(model)

    async def soft_delete(self, id: UUID) -> bool:
        """Mark a row as deleted by setting `deleted_at = now()`.

        Returns True if a row was updated (idempotent: already-deleted
        rows return False since the WHERE clause excludes them).

        Raises NotImplementedError for models without a `deleted_at`
        column — those need a hard-delete path or an explicit override.
        """
        if not self._has_deleted_at_column:
            raise NotImplementedError(
                f"{self.model_class.__name__} has no deleted_at column; "
                "override soft_delete or use a hard-delete path."
            )
        stmt = update(self.model_class).where(
            self.model_class.id == id,  # type: ignore[attr-defined]
            self.model_class.deleted_at.is_(None),  # type: ignore[attr-defined]
        )
        if self._has_account_id_column and self.account_id is not None:
            stmt = stmt.where(self.model_class.account_id == self.account_id)  # type: ignore[attr-defined]
        stmt = stmt.values(deleted_at=sa_func.now())
        result = await self.session.execute(stmt)
        return result.rowcount > 0
