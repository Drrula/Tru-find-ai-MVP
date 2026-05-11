"""B.3.3 introspection tests for VerticalPromptVersion + 0011 migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import VerticalPromptVersion as A  # noqa: F401
    from app.db.models.vertical_prompt_version import VerticalPromptVersion  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.vertical_prompt_version import VerticalPromptVersion

    assert VerticalPromptVersion.__tablename__ == "vertical_prompt_version"
    assert "vertical_prompt_version" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.vertical_prompt_version import VerticalPromptVersion

    cols = {c.name for c in VerticalPromptVersion.__table__.columns}
    assert cols == {
        "id",
        "vertical_id",
        "prompt_key",
        "version",
        "prompt_text",
        "status",
        "created_at",
        "updated_at",
    }


def test_status_check_constraint() -> None:
    from app.db.models.vertical_prompt_version import VerticalPromptVersion

    checks = [
        c
        for c in VerticalPromptVersion.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    target = [
        c for c in checks if c.name == "vertical_prompt_version_status_check"
    ]
    assert len(target) == 1


def test_vertical_id_fk_references_vertical() -> None:
    from app.db.models.vertical_prompt_version import VerticalPromptVersion

    fkeys = list(
        VerticalPromptVersion.__table__.columns["vertical_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"


def test_unique_constraint_on_natural_key() -> None:
    from app.db.models.vertical_prompt_version import VerticalPromptVersion

    uniques = [
        c
        for c in VerticalPromptVersion.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = [
        c for c in uniques if c.name == "uq_vertical_prompt_version_natural"
    ]
    assert len(target) == 1
    cols = [c.name for c in target[0].columns]
    assert cols == ["vertical_id", "prompt_key", "version"]


def test_no_account_id_no_deleted_at() -> None:
    from app.db.models.vertical_prompt_version import VerticalPromptVersion

    cols = {c.name for c in VerticalPromptVersion.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols


# --- Migration 0011


def test_migration_0011_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0011_vertical_prompt_version.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0011", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0011_vertical_prompt_version"
    assert module.down_revision == "0010_vertical_template"


def test_migration_0011_creates_expected_table_check() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0011_vertical_prompt_version.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "vertical_prompt_version"' in code
    for col in (
        "id",
        "vertical_id",
        "prompt_key",
        "version",
        "prompt_text",
        "status",
        "created_at",
        "updated_at",
    ):
        assert f'"{col}"' in code
    assert "vertical_prompt_version_status_check" in code
    assert "uq_vertical_prompt_version_natural" in code
