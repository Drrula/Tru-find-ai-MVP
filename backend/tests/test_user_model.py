"""B.2.2 introspection tests for the User ORM model + 0003 migration.

NO database connection — uses SQLAlchemy metadata introspection +
ast/importlib parsing only. The `alembic upgrade head` smoke against
docker-compose Postgres is the manual gate per
docs/phase-b-plan.md §11 (carried into B.2 by reference).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Model presence + registration


def test_user_model_imports() -> None:
    """Direct import + package re-export both work."""
    from app.db.models import User as UserFromPackage  # noqa: F401
    from app.db.models.user import User  # noqa: F401


def test_user_table_registered_with_metadata() -> None:
    """User is registered against Base.metadata under 'user' tablename."""
    from app.db.base import Base
    from app.db.models.user import User

    assert User.__tablename__ == "user"
    assert "user" in Base.metadata.tables
    assert Base.metadata.tables["user"] is User.__table__


# --- Column presence + nullability + types


def test_user_columns_match_lock_spec() -> None:
    """Per ARCHITECTURE-LOCK §2.3."""
    from app.db.models.user import User

    cols = {c.name for c in User.__table__.columns}
    expected = {
        "id",
        "account_id",
        "email_hash",
        "email_encrypted",
        "display_name",
        "external_auth_id",
        "role",
        "last_login_at",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert cols == expected


def test_user_nullability_matches_spec() -> None:
    from app.db.models.user import User

    cols = {c.name: c for c in User.__table__.columns}
    # NOT NULL
    assert cols["id"].nullable is False
    assert cols["account_id"].nullable is False
    assert cols["email_hash"].nullable is False
    assert cols["email_encrypted"].nullable is False
    assert cols["role"].nullable is False
    assert cols["created_at"].nullable is False
    assert cols["updated_at"].nullable is False
    # NULLABLE
    assert cols["display_name"].nullable is True
    assert cols["external_auth_id"].nullable is True
    assert cols["last_login_at"].nullable is True
    assert cols["deleted_at"].nullable is True


def test_user_email_columns_are_bytea() -> None:
    """Per ADR-013: email_hash + email_encrypted are stored as bytes."""
    from app.db.models.user import User

    assert isinstance(User.__table__.columns["email_hash"].type, LargeBinary)
    assert isinstance(User.__table__.columns["email_encrypted"].type, LargeBinary)


def test_user_id_is_uuid_pk_with_uuidv7_default() -> None:
    """Per ADR-033: id is UUID, application-side default produces UUIDv7."""
    from uuid import UUID

    from app.db.models.user import User

    id_col = User.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default is not None
    assert id_col.default.is_callable is True
    generated = id_col.default.arg(None)
    assert isinstance(generated, UUID)
    assert generated.version == 7


def test_user_account_id_fk_references_account() -> None:
    from app.db.models.user import User

    fkeys = list(User.__table__.columns["account_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"
    assert fkeys[0].column.name == "id"


# --- Constraints + indexes


def test_user_role_check_constraint() -> None:
    """Per Lock §2.3: CHECK (role IN ('owner','admin','member'))."""
    from app.db.models.user import User

    checks = [
        c for c in User.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    named = [c for c in checks if c.name == "user_role_check"]
    assert len(named) == 1


def test_user_role_default_owner() -> None:
    """server_default='owner' per Lock §2.3."""
    from app.db.models.user import User

    role = User.__table__.columns["role"]
    assert role.server_default is not None
    assert "owner" in str(role.server_default.arg)


def test_user_partial_unique_index_on_email_hash_active() -> None:
    """Per Lock §2.3: UNIQUE (email_hash) WHERE deleted_at IS NULL.

    Partial unique gate: re-signup after soft-delete works because the
    index excludes soft-deleted rows.
    """
    from app.db.models.user import User

    indexes = {idx.name: idx for idx in User.__table__.indexes}
    assert "ix_user_email_hash_active" in indexes
    idx = indexes["ix_user_email_hash_active"]
    assert idx.unique is True
    where_clause = idx.dialect_options.get("postgresql", {}).get("where")
    assert where_clause is not None  # partial index


def test_user_index_on_account_id() -> None:
    """Per Lock §2.3: INDEX (account_id) for tenancy-scoped reads."""
    from app.db.models.user import User

    indexes = {idx.name: idx for idx in User.__table__.indexes}
    assert "ix_user_account_id" in indexes


# --- Migration 0003


def test_migration_0003_present() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0003_user.py"
    assert path.is_file()


def test_migration_0003_chains_from_0002() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0003_user.py"
    spec = importlib.util.spec_from_file_location("alembic_0003_user_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0003_user"
    assert module.down_revision == "0002_account"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_0003_is_valid_python() -> None:
    code = (_REPO_ROOT / "backend" / "alembic" / "versions" / "0003_user.py").read_text(
        encoding="utf-8"
    )
    ast.parse(code)


def test_migration_0003_creates_expected_table_and_indexes() -> None:
    """Strict source-text gate: migration mentions every column +
    constraint + index name the model declares."""
    code = (_REPO_ROOT / "backend" / "alembic" / "versions" / "0003_user.py").read_text(
        encoding="utf-8"
    )
    assert 'op.create_table(\n        "user"' in code
    for col in (
        "id",
        "account_id",
        "email_hash",
        "email_encrypted",
        "display_name",
        "external_auth_id",
        "role",
        "last_login_at",
        "created_at",
        "updated_at",
        "deleted_at",
    ):
        assert f'"{col}"' in code, f"migration 0003 missing column {col!r}"
    assert "user_role_check" in code
    assert "ix_user_email_hash_active" in code
    assert "ix_user_account_id" in code
    assert "deleted_at IS NULL" in code  # partial index WHERE
