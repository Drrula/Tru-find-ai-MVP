"""B.4.1 introspection tests for the Lead ORM model + 0013 migration.

NO database connection — SQLAlchemy metadata introspection +
ast/importlib parsing only. The `alembic upgrade head` smoke against
docker-compose Postgres is the manual gate per phase-b-plan.md §11
(carried into B.4 by reference).

Mirrors the B.2.2 test_user_model pattern.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import Boolean, CheckConstraint, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Model presence + registration


def test_lead_model_imports() -> None:
    from app.db.models import Lead as LeadFromPackage  # noqa: F401
    from app.db.models.lead import Lead  # noqa: F401


def test_lead_table_registered_with_metadata() -> None:
    from app.db.base import Base
    from app.db.models.lead import Lead

    assert Lead.__tablename__ == "lead"
    assert "lead" in Base.metadata.tables
    assert Base.metadata.tables["lead"] is Lead.__table__


# --- Column presence + nullability + types


def test_lead_columns_match_plan_spec() -> None:
    """Per docs/phase-b4-plan.md §4. Combined v1.2 + v1.3 columns.
    `business_id` + `contact_phone_record_id` deferred per §2 #2."""
    from app.db.models.lead import Lead

    cols = {c.name for c in Lead.__table__.columns}
    expected = {
        "id",
        "account_id",
        "vertical_id",
        "source",
        "lifecycle_state",
        "email_hash",
        "email_encrypted",
        "phone_hash",
        "phone_encrypted",
        "consent_sms",
        "consent_email",
        "consent_source",
        "consent_at",
        "consent_ip_hash",
        "first_seen_at",
        "last_engaged_at",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert cols == expected


def test_lead_deferred_columns_absent() -> None:
    """Per phase-b4-plan.md §2 #2: business_id + contact_phone_record_id
    are deferred until target tables (business, phone_record) ship."""
    from app.db.models.lead import Lead

    cols = {c.name for c in Lead.__table__.columns}
    assert "business_id" not in cols
    assert "contact_phone_record_id" not in cols


def test_lead_nullability_matches_spec() -> None:
    from app.db.models.lead import Lead

    cols = {c.name: c for c in Lead.__table__.columns}
    # NOT NULL
    assert cols["id"].nullable is False  # PK
    assert cols["account_id"].nullable is False
    assert cols["source"].nullable is False
    assert cols["lifecycle_state"].nullable is False
    assert cols["consent_sms"].nullable is False
    assert cols["consent_email"].nullable is False
    assert cols["first_seen_at"].nullable is False
    assert cols["created_at"].nullable is False
    assert cols["updated_at"].nullable is False
    # NULLABLE
    assert cols["vertical_id"].nullable is True
    assert cols["email_hash"].nullable is True
    assert cols["email_encrypted"].nullable is True
    assert cols["phone_hash"].nullable is True
    assert cols["phone_encrypted"].nullable is True
    assert cols["consent_source"].nullable is True
    assert cols["consent_at"].nullable is True
    assert cols["consent_ip_hash"].nullable is True
    assert cols["last_engaged_at"].nullable is True
    assert cols["deleted_at"].nullable is True


def test_lead_pii_columns_are_bytea() -> None:
    """Per ADR-013: PII stored as (hash, encrypted) bytea pairs."""
    from app.db.models.lead import Lead

    cols = Lead.__table__.columns
    for col_name in ("email_hash", "email_encrypted", "phone_hash",
                     "phone_encrypted", "consent_ip_hash"):
        assert isinstance(cols[col_name].type, LargeBinary), (
            f"{col_name} is not LargeBinary"
        )


def test_lead_consent_columns_are_boolean() -> None:
    from app.db.models.lead import Lead

    cols = Lead.__table__.columns
    assert isinstance(cols["consent_sms"].type, Boolean)
    assert isinstance(cols["consent_email"].type, Boolean)


def test_lead_id_is_uuid_pk_with_uuidv7_default() -> None:
    """Per ADR-033: UUIDv7 PK, application-side default."""
    from uuid import UUID

    from app.db.models.lead import Lead

    id_col = Lead.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    generated = id_col.default.arg(None)
    assert isinstance(generated, UUID) and generated.version == 7


def test_lead_account_id_fk_references_account() -> None:
    from app.db.models.lead import Lead

    fkeys = list(Lead.__table__.columns["account_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "account"
    assert fkeys[0].column.name == "id"


def test_lead_vertical_id_fk_references_vertical() -> None:
    from app.db.models.lead import Lead

    fkeys = list(Lead.__table__.columns["vertical_id"].foreign_keys)
    assert len(fkeys) == 1
    assert fkeys[0].column.table.name == "vertical"
    assert fkeys[0].column.name == "id"


# --- Constraints


def test_lead_lifecycle_state_check_constraint() -> None:
    """Per ADR-037 + phase-b4-plan.md §2 #3: 8-state enum at DB."""
    from app.db.models.lead import Lead

    checks = [
        c for c in Lead.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    named = [c for c in checks if c.name == "lead_lifecycle_state_check"]
    assert len(named) == 1


def test_lead_lifecycle_state_default_cold() -> None:
    """server_default='cold' so new rows + existing rows backfill safely."""
    from app.db.models.lead import Lead

    state = Lead.__table__.columns["lifecycle_state"]
    assert state.server_default is not None
    assert "cold" in str(state.server_default.arg)


def test_lead_consent_defaults_false() -> None:
    """Explicit-opt-in posture: consent flags default to false."""
    from app.db.models.lead import Lead

    cols = Lead.__table__.columns
    for name in ("consent_sms", "consent_email"):
        assert cols[name].server_default is not None


# --- Indexes (5 partial indexes per plan §4)


def test_lead_has_five_partial_indexes() -> None:
    from app.db.models.lead import Lead

    indexes = {idx.name: idx for idx in Lead.__table__.indexes}
    expected = {
        "ix_lead_account_id_active",
        "ix_lead_account_vertical_active",
        "ix_lead_account_lifecycle_active",
        "ix_lead_email_hash_active",
        "ix_lead_phone_hash_active",
    }
    assert set(indexes.keys()) == expected
    # Every index is partial (postgresql_where present).
    for name, idx in indexes.items():
        where = idx.dialect_options.get("postgresql", {}).get("where")
        assert where is not None, f"{name} should be a partial index"


def test_lead_email_hash_index_includes_not_null_predicate() -> None:
    """The email_hash partial index excludes both soft-deleted AND
    null-email rows (a typical lead has no email)."""
    from app.db.models.lead import Lead

    idx = next(
        i for i in Lead.__table__.indexes if i.name == "ix_lead_email_hash_active"
    )
    where = str(idx.dialect_options["postgresql"]["where"])
    assert "deleted_at IS NULL" in where
    assert "email_hash IS NOT NULL" in where


# --- Migration 0013


def test_migration_0013_present() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0013_lead.py"
    assert path.is_file()


def test_migration_0013_chains_from_0012() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0013_lead.py"
    spec = importlib.util.spec_from_file_location("alembic_0013_lead", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0013_lead"
    assert module.down_revision == "0012_account_region"
    assert callable(module.upgrade) and callable(module.downgrade)


def test_migration_0013_is_valid_python() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0013_lead.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)


def test_migration_0013_creates_expected_table_and_indexes() -> None:
    """Strict source-text gate: every column + index + constraint
    that the model declares must appear in the migration."""
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0013_lead.py"
    ).read_text(encoding="utf-8")
    assert 'op.create_table(\n        "lead"' in code
    for col in (
        "id",
        "account_id",
        "vertical_id",
        "source",
        "lifecycle_state",
        "email_hash",
        "email_encrypted",
        "phone_hash",
        "phone_encrypted",
        "consent_sms",
        "consent_email",
        "consent_source",
        "consent_at",
        "consent_ip_hash",
        "first_seen_at",
        "last_engaged_at",
        "created_at",
        "updated_at",
        "deleted_at",
    ):
        assert f'"{col}"' in code, f"migration 0013 missing column {col!r}"
    assert "lead_lifecycle_state_check" in code
    for index_name in (
        "ix_lead_account_id_active",
        "ix_lead_account_vertical_active",
        "ix_lead_account_lifecycle_active",
        "ix_lead_email_hash_active",
        "ix_lead_phone_hash_active",
    ):
        assert index_name in code, f"migration 0013 missing index {index_name!r}"
    # Deferred columns must NOT appear.
    assert '"business_id"' not in code
    assert '"contact_phone_record_id"' not in code
