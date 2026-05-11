"""B.3.3 introspection tests for VerticalSignalWeight + 0008 migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import VerticalSignalWeight as A  # noqa: F401
    from app.db.models.vertical_signal_weight import VerticalSignalWeight  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    assert VerticalSignalWeight.__tablename__ == "vertical_signal_weight"
    assert "vertical_signal_weight" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    cols = {c.name for c in VerticalSignalWeight.__table__.columns}
    assert cols == {
        "id",
        "vertical_id",
        "signal_name",
        "weight",
        "effective_from",
        "created_at",
        "updated_at",
    }


def test_weight_column_is_numeric() -> None:
    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    assert isinstance(
        VerticalSignalWeight.__table__.columns["weight"].type, Numeric
    )


def test_vertical_id_fk_references_vertical() -> None:
    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    fkeys = list(
        VerticalSignalWeight.__table__.columns["vertical_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"


def test_unique_constraint_on_history_natural_key() -> None:
    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    uniques = [
        c
        for c in VerticalSignalWeight.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = [c for c in uniques if c.name == "uq_vertical_signal_weight_history"]
    assert len(target) == 1
    cols = [c.name for c in target[0].columns]
    assert cols == ["vertical_id", "signal_name", "effective_from"]


def test_id_is_uuidv7() -> None:
    from uuid import UUID

    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    id_col = VerticalSignalWeight.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default.arg(None).version == 7


def test_no_account_id_no_deleted_at() -> None:
    from app.db.models.vertical_signal_weight import VerticalSignalWeight

    cols = {c.name for c in VerticalSignalWeight.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols


# --- Migration 0008


def test_migration_0008_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0008_vertical_signal_weight.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0008", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0008_vertical_signal_weight"
    assert module.down_revision == "0007_vertical"


def test_migration_0008_creates_expected_table_constraint_index() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0008_vertical_signal_weight.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "vertical_signal_weight"' in code
    for col in (
        "id",
        "vertical_id",
        "signal_name",
        "weight",
        "effective_from",
        "created_at",
        "updated_at",
    ):
        assert f'"{col}"' in code
    assert "uq_vertical_signal_weight_history" in code
    assert "ix_vertical_signal_weight_vertical_signal" in code
