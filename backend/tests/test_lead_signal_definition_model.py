"""B.4.3 introspection tests for LeadSignalDefinition + 0016
migration. NO database connection."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import LeadSignalDefinition as A  # noqa: F401
    from app.db.models.lead_signal_definition import LeadSignalDefinition  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    assert LeadSignalDefinition.__tablename__ == "lead_signal_definition"
    assert "lead_signal_definition" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    cols = {c.name for c in LeadSignalDefinition.__table__.columns}
    assert cols == {
        "name",
        "description",
        "contributes_to",
        "freshness_ttl_seconds",
        "source_kind",
        "default_weight",
        "default_enabled",
        "created_at",
        "updated_at",
    }


def test_name_is_text_pk() -> None:
    """Diverges from UUIDv7-PK convention -- the signal name IS the
    natural key (per LOCK §2.5.2)."""
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    name_col = LeadSignalDefinition.__table__.columns["name"]
    assert name_col.primary_key is True
    assert isinstance(name_col.type, Text)


def test_no_account_id_no_deleted_at() -> None:
    """Platform-owned per ADR-047. Retirement via default_enabled, not
    soft-delete."""
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    cols = {c.name for c in LeadSignalDefinition.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols
    assert "id" not in cols  # `name` IS the PK; no UUID id column


def test_contributes_to_is_array_text() -> None:
    """First ARRAY column in the codebase."""
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    col = LeadSignalDefinition.__table__.columns["contributes_to"]
    assert isinstance(col.type, ARRAY)


def test_default_weight_is_numeric_4_3() -> None:
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    col = LeadSignalDefinition.__table__.columns["default_weight"]
    assert isinstance(col.type, Numeric)
    assert col.type.precision == 4
    assert col.type.scale == 3


def test_default_weight_check_constraint() -> None:
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    checks = [
        c
        for c in LeadSignalDefinition.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any(
        c.name == "lead_signal_definition_default_weight_range" for c in checks
    )


def test_default_enabled_server_default_true() -> None:
    from app.db.models.lead_signal_definition import LeadSignalDefinition

    col = LeadSignalDefinition.__table__.columns["default_enabled"]
    assert col.server_default is not None
    assert "true" in str(col.server_default.arg).lower()


# --- Migration 0016


def test_migration_0016_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0016_lead_signal_definition.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0016", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0016_lead_signal_definition"
    assert module.down_revision == "0015_lead_event"


def test_migration_0016_creates_expected_table() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0016_lead_signal_definition.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "lead_signal_definition"' in code
    for col in (
        "name",
        "description",
        "contributes_to",
        "freshness_ttl_seconds",
        "source_kind",
        "default_weight",
        "default_enabled",
        "created_at",
        "updated_at",
    ):
        assert f'"{col}"' in code
    assert "lead_signal_definition_default_weight_range" in code
    assert "ARRAY" in code  # contributes_to is ARRAY(Text)
    # Platform-owned + no UUID id column.
    assert '"account_id"' not in code
    assert '"deleted_at"' not in code
