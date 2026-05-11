"""B.1.4 introspection tests for the Account ORM model + 0002 migration.

NO database connection — uses SQLAlchemy metadata introspection +
ast/importlib parsing only. The `alembic upgrade head` smoke against
docker-compose Postgres is the manual gate per docs/phase-b-plan.md §11.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Model presence + registration


def test_account_model_imports() -> None:
    """Direct import + package re-export both work."""
    from app.db.models import Account as AccountFromPackage  # noqa: F401
    from app.db.models.account import Account  # noqa: F401


def test_account_table_registered_with_metadata() -> None:
    """Account is registered against Base.metadata under 'account' tablename."""
    from app.db.base import Base
    from app.db.models.account import Account

    assert Account.__tablename__ == "account"
    assert "account" in Base.metadata.tables
    assert Base.metadata.tables["account"] is Account.__table__


# --- Column presence + nullability + types


def test_account_columns_match_lock_spec() -> None:
    """Per ARCHITECTURE-LOCK §2.3: id, display_name, parent_account_id, status,
    created_at, updated_at, deleted_at + region (B.3.5 per ADR-046)."""
    from app.db.models.account import Account

    cols = {c.name for c in Account.__table__.columns}
    expected = {
        "id",
        "display_name",
        "parent_account_id",
        "status",
        "region",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert cols == expected


def test_account_nullability_matches_spec() -> None:
    """display_name + status + region + created_at + updated_at NOT NULL;
    parent_account_id + deleted_at nullable."""
    from app.db.models.account import Account

    cols = {c.name: c for c in Account.__table__.columns}
    assert cols["id"].nullable is False  # PK
    assert cols["display_name"].nullable is False
    assert cols["status"].nullable is False
    assert cols["region"].nullable is False  # B.3.5
    assert cols["created_at"].nullable is False
    assert cols["updated_at"].nullable is False
    assert cols["parent_account_id"].nullable is True
    assert cols["deleted_at"].nullable is True


def test_account_id_is_uuid_pk_with_uuidv7_default() -> None:
    """Per ADR-033: id is UUID, application-side default that produces a UUIDv7.

    Behavior check (not identity) — invoking the default callable yields a
    valid version-7 UUID. This is what actually matters for inserts; the
    callable's exact module-import identity is incidental.
    """
    from uuid import UUID

    from app.db.models.account import Account

    id_col = Account.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default is not None
    # SQLAlchemy wraps zero-arg callables to accept a context arg
    # (DefaultExecutionContext at runtime). Pass None for the test.
    assert id_col.default.is_callable is True
    generated = id_col.default.arg(None)
    assert isinstance(generated, UUID)
    assert generated.version == 7  # UUIDv7 per ADR-033 / app.core.ids.new_id


def test_account_parent_fk_self_references_account() -> None:
    """parent_account_id REFERENCES account(id)."""
    from app.db.models.account import Account

    fkeys = list(Account.__table__.columns["parent_account_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"
    assert fkeys[0].column.name == "id"


# --- Constraints + indexes


def test_account_status_check_constraint() -> None:
    """Per Lock §2.3: CHECK (status IN ('active','suspended','closed'))."""
    from app.db.models.account import Account

    checks = [
        c for c in Account.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    named = [c for c in checks if c.name == "account_status_check"]
    assert len(named) == 1


def test_account_status_default_active() -> None:
    """Per Lock §2.3: status NOT NULL DEFAULT 'active' (server-side)."""
    from app.db.models.account import Account

    status = Account.__table__.columns["status"]
    assert status.server_default is not None
    # server_default holds a DefaultClause whose .arg is a string or text() expr.
    assert "active" in str(status.server_default.arg)


def test_account_partial_index_on_parent_account_id() -> None:
    """Per Lock §2.3: INDEX (parent_account_id) WHERE parent_account_id IS NOT NULL."""
    from app.db.models.account import Account

    indexes = {idx.name: idx for idx in Account.__table__.indexes}
    assert "ix_account_parent_account_id" in indexes
    idx = indexes["ix_account_parent_account_id"]
    where_clause = idx.dialect_options.get("postgresql", {}).get("where")
    assert where_clause is not None  # partial index has a WHERE


# --- B.3.5: account.region column (per ADR-046)


def test_account_region_check_constraint() -> None:
    """Allowlist {'us','ca','uk'} enforced at the DB layer."""
    from app.db.models.account import Account

    checks = [
        c for c in Account.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    named = [c for c in checks if c.name == "account_region_check"]
    assert len(named) == 1


def test_account_region_default_us() -> None:
    """server_default='us' so existing rows backfill + new rows omit
    the column safely."""
    from app.db.models.account import Account

    region = Account.__table__.columns["region"]
    assert region.server_default is not None
    assert "us" in str(region.server_default.arg)


# --- Migration 0002


def test_migration_0002_present() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0002_account.py"
    assert path.is_file()


def test_migration_0002_chains_from_baseline() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0002_account.py"
    spec = importlib.util.spec_from_file_location("alembic_0002_account_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0002_account"
    assert module.down_revision == "0001_baseline"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_0002_is_valid_python() -> None:
    code = (_REPO_ROOT / "backend" / "alembic" / "versions" / "0002_account.py").read_text(
        encoding="utf-8"
    )
    ast.parse(code)


# --- Alembic env wiring


def test_env_imports_models_for_autogenerate() -> None:
    """env.py must import the models package so Base.metadata sees them."""
    code = (_REPO_ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "from app.db.models import *" in code


# --- B.3.5: migration 0012_account_region


def test_migration_0012_present() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0012_account_region.py"
    )
    assert path.is_file()


def test_migration_0012_chains_from_0011() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0012_account_region.py"
    )
    spec = importlib.util.spec_from_file_location(
        "alembic_0012_account_region", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0012_account_region"
    assert module.down_revision == "0011_vertical_prompt_version"
    assert callable(module.upgrade) and callable(module.downgrade)


def test_migration_0012_is_valid_python() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0012_account_region.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)


def test_migration_0012_adds_region_column_and_check() -> None:
    """Strict source-text gate: op.add_column on account, NOT NULL,
    server_default 'us', plus a CHECK constraint with the allowlist."""
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0012_account_region.py"
    ).read_text(encoding="utf-8")
    assert 'op.add_column(\n        "account"' in code
    assert '"region"' in code
    assert 'nullable=False' in code
    assert 'server_default="us"' in code
    assert "account_region_check" in code
    assert "region IN ('us','ca','uk')" in code
    # Downgrade drops constraint then column.
    assert "op.drop_constraint" in code
    assert 'op.drop_column("account", "region")' in code
