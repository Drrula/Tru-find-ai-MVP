"""B.5.1 introspection tests for LeadScoreSnapshot + 0019 migration.

NO database connection — SQLAlchemy metadata + ast/importlib parsing.
Mirrors the B.4.2 test_lead_event_model.py pattern.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import LeadScoreSnapshot as A  # noqa: F401
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    assert LeadScoreSnapshot.__tablename__ == "lead_score_snapshot"
    assert "lead_score_snapshot" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    cols = {c.name for c in LeadScoreSnapshot.__table__.columns}
    assert cols == {
        "id",
        "account_id",
        "lead_id",
        "vertical_id",
        "score",
        "score_breakdown",
        "weight_version_at",
        "inputs",
        "computed_at",
        "created_at",
    }


def test_append_only_no_updated_at_no_deleted_at() -> None:
    """Per phase-b5-plan.md §2 #2: APPEND-ONLY by design. The snapshot
    timeline is immutable. The absence of these columns IS the
    contract -- BaseRepository.soft_delete naturally refuses."""
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    cols = {c.name for c in LeadScoreSnapshot.__table__.columns}
    assert "updated_at" not in cols
    assert "deleted_at" not in cols


def test_score_is_numeric_5_2() -> None:
    """Per phase-b5-plan.md §2 #8."""
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    col = LeadScoreSnapshot.__table__.columns["score"]
    assert isinstance(col.type, Numeric)
    assert col.type.precision == 5
    assert col.type.scale == 2


def test_score_range_check_constraint() -> None:
    """`score BETWEEN 0 AND 100` -- numeric(5,2) alone allows 999.99."""
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    checks = [
        c
        for c in LeadScoreSnapshot.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any(c.name == "lead_score_snapshot_score_range" for c in checks)


def test_score_breakdown_and_inputs_are_jsonb() -> None:
    """JSONB (not JSON) so Postgres operators + future indexing are
    available."""
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    cols = LeadScoreSnapshot.__table__.columns
    assert isinstance(cols["score_breakdown"].type, JSONB)
    assert isinstance(cols["inputs"].type, JSONB)


def test_id_is_uuidv7() -> None:
    from uuid import UUID

    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    id_col = LeadScoreSnapshot.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default.arg(None).version == 7


def test_account_id_fk_references_account() -> None:
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    fkeys = list(
        LeadScoreSnapshot.__table__.columns["account_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"


def test_lead_id_fk_references_lead() -> None:
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    fkeys = list(
        LeadScoreSnapshot.__table__.columns["lead_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "lead"


def test_vertical_id_fk_references_vertical() -> None:
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    fkeys = list(
        LeadScoreSnapshot.__table__.columns["vertical_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"


def test_two_history_indexes() -> None:
    """Two access patterns -> two indexes."""
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    names = {idx.name for idx in LeadScoreSnapshot.__table__.indexes}
    assert names == {
        "ix_lead_score_snapshot_lead_computed",
        "ix_lead_score_snapshot_account_vertical_computed",
    }


def test_weight_version_at_is_required() -> None:
    """ADR-010 replay semantics depend on weight_version_at being
    NON-NULL: every snapshot must be replayable against the
    historical weight rows at that timestamp."""
    from app.db.models.lead_score_snapshot import LeadScoreSnapshot

    col = LeadScoreSnapshot.__table__.columns["weight_version_at"]
    assert col.nullable is False


# --- Migration 0019


def test_migration_0019_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0019_lead_score_snapshot.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0019", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0019_lead_score_snapshot"
    assert module.down_revision == "0018_vertical_lead_signal_weight"


def test_migration_0019_creates_expected_table_indexes_check() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0019_lead_score_snapshot.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "lead_score_snapshot"' in code
    for col in (
        "account_id",
        "lead_id",
        "vertical_id",
        "score",
        "score_breakdown",
        "weight_version_at",
        "inputs",
        "computed_at",
        "created_at",
    ):
        assert f'"{col}"' in code, (
            f"migration 0019 missing column {col!r}"
        )
    assert "lead_score_snapshot_score_range" in code
    assert "ix_lead_score_snapshot_lead_computed" in code
    assert "ix_lead_score_snapshot_account_vertical_computed" in code
    # APPEND-ONLY: no updated_at, no deleted_at columns.
    assert '"updated_at"' not in code
    assert '"deleted_at"' not in code
