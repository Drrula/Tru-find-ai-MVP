"""B.2.2 introspection tests for the MagicLinkToken ORM model + 0005 migration.

NO database connection. Verifies the table is intentionally pre-account
(no account_id column) and that token_hash carries a UNIQUE constraint
plus the active-token partial index.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Model presence + registration


def test_magic_link_token_model_imports() -> None:
    from app.db.models import MagicLinkToken as MLTFromPackage  # noqa: F401
    from app.db.models.magic_link_token import MagicLinkToken  # noqa: F401


def test_magic_link_token_table_registered_with_metadata() -> None:
    from app.db.base import Base
    from app.db.models.magic_link_token import MagicLinkToken

    assert MagicLinkToken.__tablename__ == "magic_link_token"
    assert "magic_link_token" in Base.metadata.tables
    assert (
        Base.metadata.tables["magic_link_token"] is MagicLinkToken.__table__
    )


# --- Column presence + nullability + types


def test_magic_link_token_columns_match_lock_spec() -> None:
    """Per ARCHITECTURE-LOCK §2.3 + B.2.2-amend (email_encrypted column
    added in migration 0006 to support self-signup at consume time —
    see docs/phase-b2-plan.md §4)."""
    from app.db.models.magic_link_token import MagicLinkToken

    cols = {c.name for c in MagicLinkToken.__table__.columns}
    expected = {
        "id",
        "email_hash",
        "email_encrypted",
        "token_hash",
        "issued_at",
        "expires_at",
        "consumed_at",
        "ip_hash",
    }
    assert cols == expected


def test_magic_link_token_intentionally_has_no_account_id() -> None:
    """Per Lock §2.3 + phase-b2-plan.md: pre-account-binding by design.

    The repo therefore has _has_account_id_column == False and reads
    do NOT require a tenant scope.
    """
    from app.db.models.magic_link_token import MagicLinkToken

    assert "account_id" not in {
        c.name for c in MagicLinkToken.__table__.columns
    }


def test_magic_link_token_intentionally_has_no_deleted_at() -> None:
    """Per Lock §2.3: explicit consumed_at semantics; no soft-delete column."""
    from app.db.models.magic_link_token import MagicLinkToken

    assert "deleted_at" not in {
        c.name for c in MagicLinkToken.__table__.columns
    }


def test_magic_link_token_nullability_matches_spec() -> None:
    from app.db.models.magic_link_token import MagicLinkToken

    cols = {c.name: c for c in MagicLinkToken.__table__.columns}
    assert cols["id"].nullable is False
    assert cols["email_hash"].nullable is False
    assert cols["email_encrypted"].nullable is False  # B.2.2-amend
    assert cols["token_hash"].nullable is False
    assert cols["issued_at"].nullable is False
    assert cols["expires_at"].nullable is False
    # nullable
    assert cols["consumed_at"].nullable is True
    assert cols["ip_hash"].nullable is True


def test_magic_link_token_hash_columns_are_bytea() -> None:
    """Per ADR-013 + ADR-018: email_hash + token_hash are sha256 bytes."""
    from app.db.models.magic_link_token import MagicLinkToken

    assert isinstance(
        MagicLinkToken.__table__.columns["email_hash"].type, LargeBinary
    )
    assert isinstance(
        MagicLinkToken.__table__.columns["token_hash"].type, LargeBinary
    )


def test_magic_link_token_email_encrypted_is_bytea() -> None:
    """Per ADR-013: email_encrypted is AES-256-GCM ciphertext stored as bytes.

    Added in B.2.2-amend (migration 0006) so consume can recover the
    plaintext email for self-signup.
    """
    from app.db.models.magic_link_token import MagicLinkToken

    assert isinstance(
        MagicLinkToken.__table__.columns["email_encrypted"].type, LargeBinary
    )


def test_magic_link_token_id_is_uuid_pk_with_uuidv7_default() -> None:
    from uuid import UUID

    from app.db.models.magic_link_token import MagicLinkToken

    id_col = MagicLinkToken.__table__.columns["id"]
    assert id_col.primary_key is True
    assert isinstance(id_col.type, PG_UUID)
    assert id_col.default is not None
    generated = id_col.default.arg(None)
    assert isinstance(generated, UUID)
    assert generated.version == 7


# --- Constraints + indexes


def test_magic_link_token_hash_unique_constraint() -> None:
    """Per Lock §2.3 + ADR-032: UNIQUE (token_hash) — idempotency key."""
    from app.db.models.magic_link_token import MagicLinkToken

    uniques = [
        c
        for c in MagicLinkToken.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    named = [c for c in uniques if c.name == "uq_magic_link_token_hash"]
    assert len(named) == 1
    cols = [c.name for c in named[0].columns]
    assert cols == ["token_hash"]


def test_magic_link_token_partial_index_on_token_hash_active() -> None:
    """Per Lock §2.3: INDEX (token_hash) WHERE consumed_at IS NULL."""
    from app.db.models.magic_link_token import MagicLinkToken

    indexes = {idx.name: idx for idx in MagicLinkToken.__table__.indexes}
    assert "ix_magic_link_token_active" in indexes
    idx = indexes["ix_magic_link_token_active"]
    where_clause = idx.dialect_options.get("postgresql", {}).get("where")
    assert where_clause is not None


# --- Migration 0005


def test_migration_0005_present() -> None:
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0005_magic_link_token.py"
    assert path.is_file()


def test_migration_0005_chains_from_0004() -> None:
    path = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0005_magic_link_token.py"
    )
    spec = importlib.util.spec_from_file_location(
        "alembic_0005_magic_link_token_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0005_magic_link_token"
    assert module.down_revision == "0004_session"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_0005_is_valid_python() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0005_magic_link_token.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)


def test_migration_0005_creates_expected_table_constraints_indexes() -> None:
    code = (
        _REPO_ROOT / "backend" / "alembic" / "versions" / "0005_magic_link_token.py"
    ).read_text(encoding="utf-8")
    assert 'op.create_table(\n        "magic_link_token"' in code
    for col in (
        "id",
        "email_hash",
        "token_hash",
        "issued_at",
        "expires_at",
        "consumed_at",
        "ip_hash",
    ):
        assert f'"{col}"' in code, f"migration 0005 missing column {col!r}"
    assert "uq_magic_link_token_hash" in code
    assert "ix_magic_link_token_active" in code
    assert "consumed_at IS NULL" in code
    # Defensive: must NOT have account_id (pre-account-binding) or deleted_at.
    assert '"account_id"' not in code
    assert '"deleted_at"' not in code


# --- Migration 0006 (B.2.2-amend: add email_encrypted column)


def test_migration_0006_present() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0006_magic_link_token_email_encrypted.py"
    )
    assert path.is_file()


def test_migration_0006_chains_from_0005() -> None:
    path = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0006_magic_link_token_email_encrypted.py"
    )
    spec = importlib.util.spec_from_file_location(
        "alembic_0006_magic_link_token_email_encrypted_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0006_magic_link_token_email_encrypted"
    assert module.down_revision == "0005_magic_link_token"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_0006_is_valid_python() -> None:
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0006_magic_link_token_email_encrypted.py"
    ).read_text(encoding="utf-8")
    ast.parse(code)


def test_migration_0006_adds_email_encrypted_not_null() -> None:
    """Strict source-text gate: migration must add the column NOT NULL
    via op.add_column on the magic_link_token table."""
    code = (
        _REPO_ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "0006_magic_link_token_email_encrypted.py"
    ).read_text(encoding="utf-8")
    assert 'op.add_column(\n        "magic_link_token"' in code
    assert '"email_encrypted"' in code
    assert "LargeBinary" in code
    assert "nullable=False" in code
    # Downgrade must drop the column.
    assert (
        'op.drop_column("magic_link_token", "email_encrypted")' in code
    )
