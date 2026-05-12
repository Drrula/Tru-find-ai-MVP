"""B.6A.1 introspection tests for migration 0020 (demo seed).

NO database connection -- AST + importlib parsing only. Mirrors the
B.5.1 test_lead_score_snapshot_model.py pattern. The actual
`alembic upgrade head` smoke against docker-compose Postgres is the
manual operator gate.

These tests assert:
  - revision + down_revision wiring
  - deterministic UUID5 ids are reproducible
  - all 4 legacy signal names present in upgrade()
  - weight values match the legacy pack (0.300/0.300/0.200/0.200)
  - dimension = 'lead_quality' (audit-corrected from 'overall')
  - contributes_to = ['lead_quality'] (audit-corrected from
    'business_visibility')
  - ON CONFLICT DO NOTHING idempotency on each INSERT
  - provenance comment block is present in the module docstring
  - upgrade insert order satisfies FK ordering
  - downgrade reverses in the correct order

Per phase-b6a-plan.md §5.1 + §6 smoke gate for B.6A.1.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = (
    _REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "0020_seed_demo_account_vertical_catalog.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "alembic_0020_seed", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_source() -> str:
    return _MIGRATION_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existence + chain wiring
# ---------------------------------------------------------------------------


def test_migration_0020_present() -> None:
    assert _MIGRATION_PATH.is_file()
    # AST parses (defends against accidental syntax breakage).
    ast.parse(_read_source())


def test_migration_0020_revision_and_chain() -> None:
    module = _load_migration()
    assert module.revision == "0020_seed_demo_account_vertical_catalog"
    assert module.down_revision == "0019_lead_score_snapshot"


def test_migration_0020_has_callable_upgrade_and_downgrade() -> None:
    module = _load_migration()
    assert callable(getattr(module, "upgrade", None))
    assert callable(getattr(module, "downgrade", None))


# ---------------------------------------------------------------------------
# Deterministic identities
# ---------------------------------------------------------------------------


def test_deterministic_uuid5_ids_reproducible() -> None:
    """Loading the module twice yields the same DEMO_ACCOUNT_ID and
    DEMO_VERTICAL_ID -- proves the seed identity is stable."""
    a = _load_migration()
    b = _load_migration()
    assert a.DEMO_ACCOUNT_ID == b.DEMO_ACCOUNT_ID
    assert a.DEMO_VERTICAL_ID == b.DEMO_VERTICAL_ID
    # And distinct from each other.
    assert a.DEMO_ACCOUNT_ID != a.DEMO_VERTICAL_ID


def test_demo_pack_id_matches_legacy_pack() -> None:
    """DEMO_PACK_ID must equal the legacy pack module's pack_id so
    the canonical stack resolves vertical_id from settings via the
    existing vertical.pack_id column."""
    module = _load_migration()
    assert module.DEMO_PACK_ID == "local_business_ai_visibility"


def test_effective_from_is_seed_anchor() -> None:
    """The frozen historical bootstrap timestamp per
    phase-b6a-plan.md §2 decision #4."""
    module = _load_migration()
    assert module.EFFECTIVE_FROM.year == 2026
    assert module.EFFECTIVE_FROM.month == 5
    assert module.EFFECTIVE_FROM.day == 11
    assert module.EFFECTIVE_FROM.tzinfo is not None


# ---------------------------------------------------------------------------
# Signal catalog content
# ---------------------------------------------------------------------------


def test_four_legacy_signals_present() -> None:
    module = _load_migration()
    names = [entry[0] for entry in module._SIGNAL_CATALOG]
    assert names == [
        "website_presence",
        "google_business_presence",
        "content_signals",
        "reviews",
    ]


def test_weight_values_match_legacy_pack() -> None:
    """Mirror parity: weights must equal WEIGHTS in
    backend/app/vertical/packs/local_business_ai_visibility/weights.py
    so canonical and legacy paths agree numerically once compute_lead_score
    consumes these rows."""
    module = _load_migration()
    weights_by_name = {
        entry[0]: entry[2] for entry in module._SIGNAL_CATALOG
    }
    assert weights_by_name == {
        "website_presence": 0.300,
        "google_business_presence": 0.300,
        "content_signals": 0.200,
        "reviews": 0.200,
    }
    # Sum to 1.000 per the pack invariant (weights.py module docstring).
    assert sum(weights_by_name.values()) == 1.0


def test_signal_descriptions_nonempty() -> None:
    module = _load_migration()
    for name, description, _weight in module._SIGNAL_CATALOG:
        assert isinstance(description, str)
        assert len(description) > 0, f"empty description for {name!r}"


# ---------------------------------------------------------------------------
# SQL content: dimension + contributes_to (audit corrections)
# ---------------------------------------------------------------------------


def test_dimension_is_lead_quality_in_weights_insert() -> None:
    """Audit-corrected from 'overall' to match
    LEAD_SIGNAL_WEIGHT_DEFAULT_DIMENSION in app/vertical/seed.py:60."""
    code = _read_source()
    # The literal 'lead_quality' must appear in the weights INSERT.
    assert "'lead_quality'" in code
    # The pre-audit literal must NOT appear in any INSERT.
    assert "'overall'" not in code


def test_contributes_to_is_lead_quality() -> None:
    """Audit-corrected from ['business_visibility'] to ['lead_quality']."""
    code = _read_source()
    assert "ARRAY['lead_quality']::text[]" in code
    assert "business_visibility" not in code


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_every_insert_has_on_conflict_do_nothing() -> None:
    """Idempotency contract per phase-b6a-plan.md §5.1: every INSERT
    in upgrade() must end with ON CONFLICT ... DO NOTHING so a re-run
    is a no-op."""
    code = _read_source()
    # 4 categories of INSERT (account, vertical, signal def, weight)
    # plus the catalog/weight loops produce 1 + 1 + 4 + 4 = 10 total
    # INSERT statements. We don't assert the count (loops compress
    # source text) but we DO assert that every INSERT-bearing block
    # carries an ON CONFLICT clause.
    insert_count = code.count("INSERT INTO ")
    conflict_count = code.count("ON CONFLICT ")
    assert insert_count >= 4, (
        f"expected at least 4 distinct INSERT INTO; got {insert_count}"
    )
    assert conflict_count >= 4, (
        f"expected at least 4 ON CONFLICT clauses; got {conflict_count}"
    )
    # Each INSERT must be matched by an ON CONFLICT in the same source
    # span (loose check: count parity).
    assert conflict_count >= insert_count, (
        "every INSERT must carry an ON CONFLICT clause for idempotency "
        f"({conflict_count} ON CONFLICT vs {insert_count} INSERT INTO)"
    )


def test_on_conflict_targets_natural_keys() -> None:
    """Each conflict clause must target the natural key, not just (id),
    so re-running the migration after a row was modified does not
    silently insert a duplicate via a different id."""
    code = _read_source()
    # vertical conflicts on pack_id (UNIQUE in 0007)
    assert "ON CONFLICT (pack_id) DO NOTHING" in code
    # lead_signal_definition conflicts on name (PK)
    assert "ON CONFLICT (name) DO NOTHING" in code
    # vertical_lead_signal_weight conflicts on the natural-key tuple
    assert "vertical_id, signal_name, dimension, effective_from" in code


# ---------------------------------------------------------------------------
# Provenance + module-level discipline
# ---------------------------------------------------------------------------


def test_provenance_comment_present() -> None:
    """The provenance block in the module docstring cites the legacy
    pack source explicitly, per phase-b6a-plan.md §5.1."""
    module = _load_migration()
    doc = module.__doc__ or ""
    # Normalize whitespace so line wrapping in the docstring does not
    # break the phrase match.
    doc_flat = " ".join(doc.split()).lower()
    assert "weights.py" in doc_flat, (
        "provenance comment must cite weights.py source file"
    )
    assert "frozen historical bootstrap" in doc_flat, (
        "provenance comment must invoke the 'frozen historical "
        "bootstrap artifact' framing per decision #4"
    )
    # All 4 source values must appear in the comment block.
    for value in ("0.300", "0.200"):
        assert value in doc


def test_module_does_not_import_settings_or_pack() -> None:
    """Runtime coupling is forbidden per phase-b6a-plan.md §2
    decision #4. The migration must NOT import settings, the pack
    module, or the app domain layer -- treat the migration as a
    frozen artifact."""
    code = _read_source()
    forbidden = (
        "from app.core.config import",
        "from app.vertical.packs",
        "from app.domain",
        "import app.vertical",
        "import app.domain",
    )
    for imp in forbidden:
        assert imp not in code, (
            f"migration must not import {imp!r} -- runtime coupling "
            "violates decision #4 (frozen historical bootstrap)"
        )


# ---------------------------------------------------------------------------
# Upgrade insert order (FK satisfaction)
# ---------------------------------------------------------------------------


def test_upgrade_insert_order_satisfies_fks() -> None:
    """Insert order in upgrade() must be:
        account -> vertical -> lead_signal_definition -> vertical_lead_signal_weight
    so FKs are satisfied at INSERT time."""
    code = _read_source()
    # Position of each first INSERT INTO <table>:
    pos_account = code.find("INSERT INTO account")
    pos_vertical = code.find("INSERT INTO vertical ")
    pos_signal_def = code.find("INSERT INTO lead_signal_definition")
    pos_weight = code.find("INSERT INTO vertical_lead_signal_weight")
    assert pos_account != -1, "missing account INSERT"
    assert pos_vertical != -1, "missing vertical INSERT"
    assert pos_signal_def != -1, "missing lead_signal_definition INSERT"
    assert pos_weight != -1, "missing vertical_lead_signal_weight INSERT"
    assert pos_account < pos_vertical < pos_signal_def < pos_weight, (
        f"FK-satisfying insert order violated: account={pos_account} "
        f"vertical={pos_vertical} signal_def={pos_signal_def} "
        f"weight={pos_weight}"
    )


# ---------------------------------------------------------------------------
# Downgrade reverses correctly
# ---------------------------------------------------------------------------


def test_downgrade_delete_order_reverses_upgrade() -> None:
    """Downgrade must DELETE in reverse FK order:
        weight -> signal_def -> vertical -> account."""
    code = _read_source()
    downgrade_start = code.find("def downgrade(")
    assert downgrade_start != -1
    down_body = code[downgrade_start:]
    pos_weight = down_body.find("DELETE FROM vertical_lead_signal_weight")
    pos_signal_def = down_body.find("DELETE FROM lead_signal_definition")
    pos_vertical = down_body.find("DELETE FROM vertical ")
    pos_account = down_body.find("DELETE FROM account")
    assert pos_weight != -1, "downgrade missing weight DELETE"
    assert pos_signal_def != -1, "downgrade missing signal_def DELETE"
    assert pos_vertical != -1, "downgrade missing vertical DELETE"
    assert pos_account != -1, "downgrade missing account DELETE"
    assert (
        pos_weight < pos_signal_def < pos_vertical < pos_account
    ), (
        f"downgrade order violated: weight={pos_weight} "
        f"signal_def={pos_signal_def} vertical={pos_vertical} "
        f"account={pos_account}"
    )


def test_downgrade_targets_seed_rows_only() -> None:
    """Downgrade must NOT mass-delete; each DELETE targets the
    specific seeded rows by deterministic identity (id / pack_id /
    natural-key tuple). A reckless `DELETE FROM <table>` with no
    WHERE clause must not appear."""
    code = _read_source()
    downgrade_start = code.find("def downgrade(")
    down_body = code[downgrade_start:]
    # Each DELETE must include a WHERE clause.
    for table in (
        "vertical_lead_signal_weight",
        "lead_signal_definition",
        "vertical ",
        "account",
    ):
        delete_pos = down_body.find(f"DELETE FROM {table}")
        if delete_pos == -1:
            continue
        # Look for WHERE within the next 200 chars after the DELETE.
        window = down_body[delete_pos : delete_pos + 200]
        assert "WHERE" in window, (
            f"DELETE FROM {table.strip()!r} must carry a WHERE clause"
        )
