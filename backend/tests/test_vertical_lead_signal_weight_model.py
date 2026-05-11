"""B.4.3 introspection tests for VerticalLeadSignalWeight + 0018
migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import VerticalLeadSignalWeight as A  # noqa: F401
    from app.db.models.vertical_lead_signal_weight import (  # noqa: F401
        VerticalLeadSignalWeight,
    )


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    assert (
        VerticalLeadSignalWeight.__tablename__ == "vertical_lead_signal_weight"
    )
    assert "vertical_lead_signal_weight" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    cols = {c.name for c in VerticalLeadSignalWeight.__table__.columns}
    assert cols == {
        "id",
        "vertical_id",
        "signal_name",
        "dimension",
        "weight",
        "enabled",
        "effective_from",
        "effective_to",
        "created_at",
    }


def test_no_account_id_no_deleted_at_no_updated_at() -> None:
    """Platform-owned per ADR-047. History via effective_from/_to;
    no soft-delete + no row mutation other than close_active (which
    is the ONE allowed mutator per B.4.3 design)."""
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    cols = {c.name for c in VerticalLeadSignalWeight.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols
    assert "updated_at" not in cols


def test_weight_is_numeric_4_3() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    col = VerticalLeadSignalWeight.__table__.columns["weight"]
    assert isinstance(col.type, Numeric)
    assert col.type.precision == 4
    assert col.type.scale == 3


def test_weight_check_constraint() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    checks = [
        c
        for c in VerticalLeadSignalWeight.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any(
        c.name == "vertical_lead_signal_weight_range" for c in checks
    )


def test_unique_constraint_on_history_key() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    uniques = [
        c
        for c in VerticalLeadSignalWeight.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = [
        c for c in uniques if c.name == "uq_vertical_lead_signal_weight_history"
    ]
    assert len(target) == 1
    cols = [c.name for c in target[0].columns]
    assert cols == ["vertical_id", "signal_name", "dimension", "effective_from"]


def test_vertical_id_fk_references_vertical() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    fkeys = list(
        VerticalLeadSignalWeight.__table__.columns["vertical_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"


def test_signal_name_fk_references_lead_signal_definition() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    fkeys = list(
        VerticalLeadSignalWeight.__table__.columns["signal_name"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "lead_signal_definition"
    assert fkeys[0].column.name == "name"


def test_lookup_index_present() -> None:
    from app.db.models.vertical_lead_signal_weight import (
        VerticalLeadSignalWeight,
    )

    names = {idx.name for idx in VerticalLeadSignalWeight.__table__.indexes}
    assert "ix_vertical_lead_signal_weight_lookup" in names


# --- Migration 0018


def test_migration_0018_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0018_vertical_lead_signal_weight.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0018", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0018_vertical_lead_signal_weight"
    assert module.down_revision == "0017_lead_signal"


def test_migration_0018_creates_expected_table_constraints() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0018_vertical_lead_signal_weight.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert (
        'op.create_table(\n        "vertical_lead_signal_weight"' in code
    )
    for col in (
        "vertical_id",
        "signal_name",
        "dimension",
        "weight",
        "enabled",
        "effective_from",
        "effective_to",
        "created_at",
    ):
        assert f'"{col}"' in code
    assert "vertical_lead_signal_weight_range" in code
    assert "uq_vertical_lead_signal_weight_history" in code
    assert "ix_vertical_lead_signal_weight_lookup" in code
    # Platform-owned + no row-mutation columns beyond effective_to.
    assert '"account_id"' not in code
    assert '"deleted_at"' not in code
    assert '"updated_at"' not in code
