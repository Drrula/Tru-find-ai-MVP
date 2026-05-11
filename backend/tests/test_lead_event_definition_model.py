"""B.4.2 introspection tests for LeadEventDefinition + 0014 migration.

NO database connection — SQLAlchemy metadata + ast/importlib parsing.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import LeadEventDefinition as A  # noqa: F401
    from app.db.models.lead_event_definition import LeadEventDefinition  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.lead_event_definition import LeadEventDefinition

    assert LeadEventDefinition.__tablename__ == "lead_event_definition"
    assert "lead_event_definition" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.lead_event_definition import LeadEventDefinition

    cols = {c.name for c in LeadEventDefinition.__table__.columns}
    assert cols == {
        "id",
        "event_type",
        "version",
        "status",
        "category",
        "source",
        "default_weight",
        "freshness_ttl_seconds",
        "description",
        "payload_schema",
        "lenient",
        "created_at",
        "updated_at",
    }


def test_no_account_id_no_deleted_at() -> None:
    """Per ADR-047: platform-owned. Retirement via status, not soft-delete."""
    from app.db.models.lead_event_definition import LeadEventDefinition

    cols = {c.name for c in LeadEventDefinition.__table__.columns}
    assert "account_id" not in cols
    assert "deleted_at" not in cols


def test_default_weight_is_numeric() -> None:
    from app.db.models.lead_event_definition import LeadEventDefinition

    col = LeadEventDefinition.__table__.columns["default_weight"]
    assert isinstance(col.type, Numeric)
    assert col.type.precision == 4
    assert col.type.scale == 3


def test_payload_schema_is_jsonb() -> None:
    from app.db.models.lead_event_definition import LeadEventDefinition

    assert isinstance(
        LeadEventDefinition.__table__.columns["payload_schema"].type, JSONB
    )


def test_status_check_constraint() -> None:
    from app.db.models.lead_event_definition import LeadEventDefinition

    checks = [
        c
        for c in LeadEventDefinition.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any(
        c.name == "lead_event_definition_status_check" for c in checks
    )
    assert any(
        c.name == "lead_event_definition_default_weight_range" for c in checks
    )


def test_unique_constraint_on_natural_key() -> None:
    from app.db.models.lead_event_definition import LeadEventDefinition

    uniques = [
        c
        for c in LeadEventDefinition.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = [
        c for c in uniques if c.name == "uq_lead_event_definition_natural"
    ]
    assert len(target) == 1
    cols = [c.name for c in target[0].columns]
    assert cols == ["event_type", "version"]


def test_active_partial_index() -> None:
    """ix_lead_event_definition_active is a partial index gated on
    `status = 'active'` — backs the find_active_by_event_type lookup."""
    from app.db.models.lead_event_definition import LeadEventDefinition

    indexes = {
        idx.name: idx for idx in LeadEventDefinition.__table__.indexes
    }
    idx = indexes["ix_lead_event_definition_active"]
    where = str(idx.dialect_options["postgresql"]["where"])
    assert "status = 'active'" in where


# --- Migration 0014


def test_migration_0014_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0014_lead_event_definition.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0014", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0014_lead_event_definition"
    assert module.down_revision == "0013_lead"


def test_migration_0014_creates_expected_table() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0014_lead_event_definition.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "lead_event_definition"' in code
    for col in (
        "event_type",
        "version",
        "status",
        "category",
        "source",
        "default_weight",
        "freshness_ttl_seconds",
        "payload_schema",
        "lenient",
    ):
        assert f'"{col}"' in code
    assert "lead_event_definition_status_check" in code
    assert "lead_event_definition_default_weight_range" in code
    assert "uq_lead_event_definition_natural" in code
    assert "ix_lead_event_definition_active" in code
    # Platform-owned: no account_id, no deleted_at.
    assert '"account_id"' not in code
    assert '"deleted_at"' not in code
