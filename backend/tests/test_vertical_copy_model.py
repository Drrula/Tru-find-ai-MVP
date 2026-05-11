"""B.3.3 introspection tests for VerticalCopy + 0009 migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import Text, UniqueConstraint

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import VerticalCopy as A  # noqa: F401
    from app.db.models.vertical_copy import VerticalCopy  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.vertical_copy import VerticalCopy

    assert VerticalCopy.__tablename__ == "vertical_copy"
    assert "vertical_copy" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.vertical_copy import VerticalCopy

    cols = {c.name for c in VerticalCopy.__table__.columns}
    assert cols == {
        "id",
        "vertical_id",
        "locale",
        "key",
        "text",
        "created_at",
        "updated_at",
    }


def test_text_column_is_text_type() -> None:
    from app.db.models.vertical_copy import VerticalCopy

    assert isinstance(VerticalCopy.__table__.columns["text"].type, Text)


def test_vertical_id_fk_references_vertical() -> None:
    from app.db.models.vertical_copy import VerticalCopy

    fkeys = list(VerticalCopy.__table__.columns["vertical_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"


def test_unique_constraint_on_locale_key() -> None:
    from app.db.models.vertical_copy import VerticalCopy

    uniques = [
        c
        for c in VerticalCopy.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = [c for c in uniques if c.name == "uq_vertical_copy_key"]
    assert len(target) == 1
    cols = [c.name for c in target[0].columns]
    assert cols == ["vertical_id", "locale", "key"]


def test_no_account_id_no_deleted_at() -> None:
    from app.db.models.vertical_copy import VerticalCopy

    cols = {c.name for c in VerticalCopy.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols


# --- Migration 0009


def test_migration_0009_present_and_chains() -> None:
    path = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0009_vertical_copy.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0009", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0009_vertical_copy"
    assert module.down_revision == "0008_vertical_signal_weight"


def test_migration_0009_creates_expected_table_constraint() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0009_vertical_copy.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "vertical_copy"' in code
    for col in (
        "id",
        "vertical_id",
        "locale",
        "key",
        "text",
        "created_at",
        "updated_at",
    ):
        assert f'"{col}"' in code
    assert "uq_vertical_copy_key" in code
