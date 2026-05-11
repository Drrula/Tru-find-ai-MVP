"""B.3.3 introspection tests for the Vertical ORM model + 0007 migration.

NO database connection — SQLAlchemy metadata introspection + ast +
importlib parsing only. The `alembic upgrade head` smoke against
docker-compose Postgres remains the manual gate per
phase-b-plan.md §11.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_vertical_model_imports() -> None:
    from app.db.models import Vertical as VFromPackage  # noqa: F401
    from app.db.models.vertical import Vertical  # noqa: F401


def test_vertical_table_registered_with_metadata() -> None:
    from app.db.base import Base
    from app.db.models.vertical import Vertical

    assert Vertical.__tablename__ == "vertical"
    assert "vertical" in Base.metadata.tables
    assert Base.metadata.tables["vertical"] is Vertical.__table__


def test_vertical_columns_match_lock_spec() -> None:
    from app.db.models.vertical import Vertical

    cols = {c.name for c in Vertical.__table__.columns}
    assert cols == {
        "id",
        "pack_id",
        "display_name",
        "schema_version",
        "created_at",
        "updated_at",
    }


def test_vertical_has_no_account_id_or_deleted_at() -> None:
    """Per ADR-047 (platform-owned) + version-and-replace lifecycle."""
    from app.db.models.vertical import Vertical

    cols = {c.name for c in Vertical.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols


def test_vertical_id_is_uuid_pk_with_uuidv7_default() -> None:
    from uuid import UUID

    from app.db.models.vertical import Vertical

    id_col = Vertical.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    generated = id_col.default.arg(None)
    assert isinstance(generated, UUID) and generated.version == 7


def test_vertical_pack_id_is_unique() -> None:
    from app.db.models.vertical import Vertical

    uniques = [
        c
        for c in Vertical.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert any(c.name == "uq_vertical_pack_id" for c in uniques)


# --- Migration 0007


def test_migration_0007_present() -> None:
    assert (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0007_vertical.py"
    ).is_file()


def test_migration_0007_chains_from_0006() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0007_vertical.py"
    spec = importlib.util.spec_from_file_location("alembic_0007_vertical", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0007_vertical"
    assert module.down_revision == "0006_magic_link_token_email_encrypted"
    assert callable(module.upgrade) and callable(module.downgrade)


def test_migration_0007_is_valid_python() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0007_vertical.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)


def test_migration_0007_creates_expected_columns_and_unique() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0007_vertical.py"
    ).read_text(encoding="utf-8")
    assert 'op.create_table(\n        "vertical"' in code
    for col in (
        "id",
        "pack_id",
        "display_name",
        "schema_version",
        "created_at",
        "updated_at",
    ):
        assert f'"{col}"' in code
    assert "uq_vertical_pack_id" in code
    # Platform-owned: no account_id, no deleted_at.
    assert '"account_id"' not in code
    assert '"deleted_at"' not in code
