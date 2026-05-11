"""B.4.3 introspection tests for LeadSignal + 0017 migration."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_imports() -> None:
    from app.db.models import LeadSignal as A  # noqa: F401
    from app.db.models.lead_signal import LeadSignal  # noqa: F401


def test_table_registered() -> None:
    from app.db.base import Base
    from app.db.models.lead_signal import LeadSignal

    assert LeadSignal.__tablename__ == "lead_signal"
    assert "lead_signal" in Base.metadata.tables


def test_columns_match_spec() -> None:
    from app.db.models.lead_signal import LeadSignal

    cols = {c.name for c in LeadSignal.__table__.columns}
    assert cols == {
        "id",
        "account_id",
        "lead_id",
        "signal_name",
        "value",
        "source",
        "source_ref_id",
        "observed_at",
        "recorded_at",
        "created_at",
    }


def test_append_only_no_updated_at_no_deleted_at() -> None:
    """Per plan §4: APPEND-ONLY. Signals are immutable observations;
    the "current value" is resolved at read time, not via UPDATE."""
    from app.db.models.lead_signal import LeadSignal

    cols = {c.name for c in LeadSignal.__table__.columns}
    assert "updated_at" not in cols
    assert "deleted_at" not in cols


def test_value_is_jsonb() -> None:
    from app.db.models.lead_signal import LeadSignal

    assert isinstance(LeadSignal.__table__.columns["value"].type, JSONB)


def test_id_is_uuidv7() -> None:
    from uuid import UUID

    from app.db.models.lead_signal import LeadSignal

    id_col = LeadSignal.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default.arg(None).version == 7


def test_lead_id_fk_references_lead() -> None:
    from app.db.models.lead_signal import LeadSignal

    fkeys = list(LeadSignal.__table__.columns["lead_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "lead"


def test_account_id_fk_references_account() -> None:
    from app.db.models.lead_signal import LeadSignal

    fkeys = list(LeadSignal.__table__.columns["account_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"


def test_signal_name_fk_references_lead_signal_definition() -> None:
    """FK target is .name (text PK), not .id."""
    from app.db.models.lead_signal import LeadSignal

    fkeys = list(LeadSignal.__table__.columns["signal_name"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "lead_signal_definition"
    assert fkeys[0].column.name == "name"


def test_two_history_indexes() -> None:
    """Composite `(lead_id, signal_name, observed_at DESC)` backs
    find_current/find_history; `(account_id, observed_at DESC)` is the
    durable account-scoped index for future queries."""
    from app.db.models.lead_signal import LeadSignal

    names = {idx.name for idx in LeadSignal.__table__.indexes}
    assert names == {
        "ix_lead_signal_lead_name_observed",
        "ix_lead_signal_account_observed",
    }


# --- Migration 0017


def test_migration_0017_present_and_chains() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0017_lead_signal.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("alembic_0017", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0017_lead_signal"
    assert module.down_revision == "0016_lead_signal_definition"


def test_migration_0017_creates_expected_table_indexes() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0017_lead_signal.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)
    assert 'op.create_table(\n        "lead_signal"' in code
    for col in (
        "account_id",
        "lead_id",
        "signal_name",
        "value",
        "source",
        "source_ref_id",
        "observed_at",
        "recorded_at",
        "created_at",
    ):
        assert f'"{col}"' in code
    assert "ix_lead_signal_lead_name_observed" in code
    assert "ix_lead_signal_account_observed" in code
    # APPEND-ONLY: no updated_at, no deleted_at.
    assert '"updated_at"' not in code
    assert '"deleted_at"' not in code
