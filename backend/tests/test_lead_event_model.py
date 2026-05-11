"""B.4.2 introspection tests for LeadEvent + 0015 migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import LeadEvent as A  # noqa: F401
    from app.db.models.lead_event import LeadEvent  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.lead_event import LeadEvent

    assert LeadEvent.__tablename__ == "lead_event"
    assert "lead_event" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.lead_event import LeadEvent

    cols = {c.name for c in LeadEvent.__table__.columns}
    assert cols == {
        "id",
        "account_id",
        "lead_id",
        "event_type",
        "event_definition_id",
        "payload",
        "actor_kind",
        "actor_user_id",
        "occurred_at",
        "recorded_at",
        "created_at",
    }


def test_append_only_no_updated_at_no_deleted_at() -> None:
    """Per plan §4: APPEND-ONLY by design. The timeline is immutable.
    No `updated_at`, no `deleted_at` -- the absence is the contract."""
    from app.db.models.lead_event import LeadEvent

    cols = {c.name for c in LeadEvent.__table__.columns}
    assert "updated_at" not in cols
    assert "deleted_at" not in cols


def test_payload_is_jsonb() -> None:
    from app.db.models.lead_event import LeadEvent

    assert isinstance(LeadEvent.__table__.columns["payload"].type, JSONB)


def test_id_is_uuidv7() -> None:
    from uuid import UUID

    from app.db.models.lead_event import LeadEvent

    id_col = LeadEvent.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default.arg(None).version == 7


def test_account_id_fk_references_account() -> None:
    from app.db.models.lead_event import LeadEvent

    fkeys = list(LeadEvent.__table__.columns["account_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"


def test_lead_id_fk_references_lead() -> None:
    from app.db.models.lead_event import LeadEvent

    fkeys = list(LeadEvent.__table__.columns["lead_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "lead"


def test_event_definition_id_fk_references_lead_event_definition() -> None:
    from app.db.models.lead_event import LeadEvent

    fkeys = list(
        LeadEvent.__table__.columns["event_definition_id"].foreign_keys
    )
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "lead_event_definition"


def test_actor_kind_check_constraint() -> None:
    """Closed enum at DB: user / system / webhook / job / ai (per
    ADR-044 envelope shape)."""
    from app.db.models.lead_event import LeadEvent

    checks = [
        c for c in LeadEvent.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    assert any(c.name == "lead_event_actor_kind_check" for c in checks)


def test_two_timeline_indexes() -> None:
    """Two access patterns -> two indexes."""
    from app.db.models.lead_event import LeadEvent

    names = {idx.name for idx in LeadEvent.__table__.indexes}
    assert names == {
        "ix_lead_event_lead_occurred",
        "ix_lead_event_account_type_occurred",
    }


# --- Migration 0015


def test_migration_0015_present_and_chains() -> None:
    path = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0015_lead_event.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0015", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0015_lead_event"
    assert module.down_revision == "0014_lead_event_definition"


def test_migration_0015_creates_expected_table_indexes_check() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0015_lead_event.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "lead_event"' in code
    for col in (
        "account_id",
        "lead_id",
        "event_type",
        "event_definition_id",
        "payload",
        "actor_kind",
        "actor_user_id",
        "occurred_at",
        "recorded_at",
        "created_at",
    ):
        assert f'"{col}"' in code
    assert "lead_event_actor_kind_check" in code
    assert "ix_lead_event_lead_occurred" in code
    assert "ix_lead_event_account_type_occurred" in code
    # APPEND-ONLY: no updated_at, no deleted_at columns.
    assert '"updated_at"' not in code
    assert '"deleted_at"' not in code
