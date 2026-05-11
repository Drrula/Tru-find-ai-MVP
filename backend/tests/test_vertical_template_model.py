"""B.3.3 introspection tests for VerticalTemplate + 0010 migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import VerticalTemplate as A  # noqa: F401
    from app.db.models.vertical_template import VerticalTemplate  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.vertical_template import VerticalTemplate

    assert VerticalTemplate.__tablename__ == "vertical_template"
    assert "vertical_template" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.vertical_template import VerticalTemplate

    cols = {c.name for c in VerticalTemplate.__table__.columns}
    assert cols == {
        "id",
        "vertical_id",
        "name",
        "config_json",
        "created_at",
        "updated_at",
    }


def test_config_json_is_jsonb() -> None:
    """JSONB (not JSON) so Postgres operators + indexes are usable later."""
    from app.db.models.vertical_template import VerticalTemplate

    assert isinstance(
        VerticalTemplate.__table__.columns["config_json"].type, JSONB
    )


def test_vertical_id_fk_references_vertical() -> None:
    from app.db.models.vertical_template import VerticalTemplate

    fkeys = list(
        VerticalTemplate.__table__.columns["vertical_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"


def test_unique_constraint_on_name() -> None:
    from app.db.models.vertical_template import VerticalTemplate

    uniques = [
        c
        for c in VerticalTemplate.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = [c for c in uniques if c.name == "uq_vertical_template_name"]
    assert len(target) == 1
    cols = [c.name for c in target[0].columns]
    assert cols == ["vertical_id", "name"]


def test_no_account_id_no_deleted_at() -> None:
    from app.db.models.vertical_template import VerticalTemplate

    cols = {c.name for c in VerticalTemplate.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols


# --- Migration 0010


def test_migration_0010_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0010_vertical_template.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0010", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0010_vertical_template"
    assert module.down_revision == "0009_vertical_copy"


def test_migration_0010_creates_expected_table_jsonb() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0010_vertical_template.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "vertical_template"' in code
    for col in (
        "id",
        "vertical_id",
        "name",
        "config_json",
        "created_at",
        "updated_at",
    ):
        assert f'"{col}"' in code
    assert "JSONB" in code
    assert "uq_vertical_template_name" in code
