"""B.2.2 introspection tests for the UserSession ORM model + 0004 migration.

NO database connection. Verifies model structure matches Lock §2.3
column-by-column and that the migration source mirrors the model.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Model presence + registration


def test_user_session_model_imports() -> None:
    from app.db.models import UserSession as USFromPackage  # noqa: F401
    from app.db.models.session import UserSession  # noqa: F401


def test_session_table_registered_with_metadata() -> None:
    """Class is `UserSession`; table is `session` (Lock §2.3)."""
    from app.db.base import Base
    from app.db.models.session import UserSession

    assert UserSession.__tablename__ == "session"
    assert "session" in Base.metadata.tables
    assert Base.metadata.tables["session"] is UserSession.__table__


# --- Column presence + nullability + types


def test_session_columns_match_lock_spec() -> None:
    from app.db.models.session import UserSession

    cols = {c.name for c in UserSession.__table__.columns}
    expected = {
        "id",
        "user_id",
        "account_id",
        "issued_at",
        "expires_at",
        "revoked_at",
        "ip_hash",
        "user_agent",
    }
    assert cols == expected


def test_session_has_no_deleted_at_column() -> None:
    """Per Lock §2.3: revoked_at is the soft-revoke field; NO deleted_at.

    BaseRepository's deleted_at-based soft-delete filter must therefore
    NOT apply to UserSession (no false-positive filter).
    """
    from app.db.models.session import UserSession

    assert "deleted_at" not in {c.name for c in UserSession.__table__.columns}


def test_session_nullability_matches_spec() -> None:
    from app.db.models.session import UserSession

    cols = {c.name: c for c in UserSession.__table__.columns}
    assert cols["id"].nullable is False
    assert cols["user_id"].nullable is False
    assert cols["account_id"].nullable is False
    assert cols["issued_at"].nullable is False
    assert cols["expires_at"].nullable is False
    # nullable
    assert cols["revoked_at"].nullable is True
    assert cols["ip_hash"].nullable is True
    assert cols["user_agent"].nullable is True


def test_session_id_is_uuid_pk_with_uuidv7_default() -> None:
    from uuid import UUID

    from app.db.models.session import UserSession

    id_col = UserSession.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default is not None
    generated = id_col.default.arg(None)
    assert isinstance(generated, UUID)
    assert generated.version == 7


def test_session_user_id_fk_references_user() -> None:
    from app.db.models.session import UserSession

    fkeys = list(UserSession.__table__.columns["user_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "user"
    assert fkeys[0].column.name == "id"


def test_session_account_id_fk_references_account() -> None:
    """Denormalized account_id has explicit FK for referential integrity."""
    from app.db.models.session import UserSession

    fkeys = list(UserSession.__table__.columns["account_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"
    assert fkeys[0].column.name == "id"


def test_session_ip_hash_is_bytea() -> None:
    """Per ADR-013: ip_hash is sha256(client_ip), stored as bytes."""
    from app.db.models.session import UserSession

    assert isinstance(UserSession.__table__.columns["ip_hash"].type, LargeBinary)


def test_session_user_agent_is_string_256() -> None:
    """user_agent column length matches the write-time truncation."""
    from app.db.models.session import UserSession

    ua = UserSession.__table__.columns["user_agent"]
    assert isinstance(ua.type, String)
    assert ua.type.length == 256


# --- Indexes


def test_session_composite_index_on_user_id_expires_at() -> None:
    """Per Lock §2.3: INDEX (user_id, expires_at)."""
    from app.db.models.session import UserSession

    indexes = {idx.name: idx for idx in UserSession.__table__.indexes}
    assert "ix_session_user_id_expires_at" in indexes
    idx = indexes["ix_session_user_id_expires_at"]
    cols = [c.name for c in idx.columns]
    assert cols == ["user_id", "expires_at"]


# --- Migration 0004


def test_migration_0004_present() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0004_session.py"
    assert path.is_file()


def test_migration_0004_chains_from_0003() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0004_session.py"
    spec = importlib.util.spec_from_file_location("alembic_0004_session_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0004_session"
    assert module.down_revision == "0003_user"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_0004_is_valid_python() -> None:
    code = (_REPO_ROOT / "backend" / "alembic" / "versions" / "0004_session.py").read_text(
        encoding="utf-8"
    )
    ast.parse(code)


def test_migration_0004_creates_expected_table_and_indexes() -> None:
    code = (_REPO_ROOT / "backend" / "alembic" / "versions" / "0004_session.py").read_text(
        encoding="utf-8"
    )
    assert 'op.create_table(\n        "session"' in code
    for col in (
        "id",
        "user_id",
        "account_id",
        "issued_at",
        "expires_at",
        "revoked_at",
        "ip_hash",
        "user_agent",
    ):
        assert f'"{col}"' in code, f"migration 0004 missing column {col!r}"
    assert "ix_session_user_id_expires_at" in code
    # Defensive: must NOT create a deleted_at column.
    assert '"deleted_at"' not in code
