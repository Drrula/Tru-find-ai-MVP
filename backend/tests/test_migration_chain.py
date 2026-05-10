"""B.2.2 strict migration smoke gates — chain integrity across all migrations.

Verifies:
- Every migration file under backend/alembic/versions/ parses, imports,
  and has callable upgrade + downgrade.
- Revision ids are unique.
- The chain is linear and unbroken: every non-baseline migration's
  down_revision points to a previously-defined revision; exactly ONE
  baseline (down_revision is None); exactly ONE head (no other
  migration points to its revision).
- Expected B.2.2 head is `0005_magic_link_token`.
- env.py picks up the model package (so target_metadata sees the new
  models added in B.2.2).

NO database connection. The actual `alembic upgrade head` smoke against
docker-compose Postgres is the manual operator gate per
docs/phase-b-plan.md §11.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS_DIR = _REPO_ROOT / "backend" / "alembic" / "versions"


def _load_all_migrations() -> list[tuple[str, ModuleType]]:
    """Import every migration as a module; return (filename, module) pairs.

    Sorted by filename so the chain ordering is deterministic and matches
    operator expectations (lexical = chronological by our naming convention).
    """
    paths = sorted(_VERSIONS_DIR.glob("*.py"))
    out: list[tuple[str, ModuleType]] = []
    for p in paths:
        if p.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(
            f"alembic_chain_test_{p.stem}", p
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out.append((p.name, module))
    return out


def test_migrations_directory_exists() -> None:
    assert _VERSIONS_DIR.is_dir()


def test_every_migration_has_required_attributes() -> None:
    """Each migration declares revision + down_revision + upgrade + downgrade."""
    for filename, m in _load_all_migrations():
        assert hasattr(m, "revision"), f"{filename}: missing revision"
        assert hasattr(m, "down_revision"), f"{filename}: missing down_revision"
        assert callable(getattr(m, "upgrade", None)), (
            f"{filename}: upgrade is not callable"
        )
        assert callable(getattr(m, "downgrade", None)), (
            f"{filename}: downgrade is not callable"
        )


def test_revision_ids_are_unique() -> None:
    revisions = [m.revision for _, m in _load_all_migrations()]
    assert len(revisions) == len(set(revisions)), (
        f"duplicate revision ids: {revisions}"
    )


def test_exactly_one_baseline() -> None:
    """Exactly one migration has down_revision is None (the baseline)."""
    baselines = [
        (filename, m)
        for filename, m in _load_all_migrations()
        if m.down_revision is None
    ]
    assert len(baselines) == 1, (
        f"expected 1 baseline (down_revision=None); found {len(baselines)}: "
        f"{[f for f, _ in baselines]}"
    )
    assert baselines[0][1].revision == "0001_baseline"


def test_chain_is_linear_and_unbroken() -> None:
    """For every non-baseline migration, down_revision points to a known revision.

    Builds the graph of (revision -> migration) and (parent -> child)
    edges, then walks from the baseline forward expecting exactly one
    successor at each step. Catches:
      - Orphans (down_revision points to a revision that doesn't exist)
      - Forks (two migrations sharing a down_revision)
      - Multiple heads (more than one revision with no successor)
    """
    migrations = _load_all_migrations()
    by_revision = {m.revision: m for _, m in migrations}
    assert len(by_revision) == len(migrations)  # already covered, defensive

    # Validate every down_revision is known.
    for filename, m in migrations:
        if m.down_revision is None:
            continue
        assert m.down_revision in by_revision, (
            f"{filename}: down_revision {m.down_revision!r} is not a known revision"
        )

    # Build child map: revision -> list of revisions whose down_revision == it.
    children: dict[str, list[str]] = {rev: [] for rev in by_revision}
    for _, m in migrations:
        if m.down_revision is not None:
            children[m.down_revision].append(m.revision)

    # No forks: each revision has at most one child.
    for parent, kids in children.items():
        assert len(kids) <= 1, (
            f"fork detected: revision {parent!r} has multiple successors: {kids}"
        )

    # Walk from baseline. Visited count must equal the total migration count.
    cursor: str | None = "0001_baseline"
    visited: list[str] = []
    while cursor is not None:
        visited.append(cursor)
        kids = children[cursor]
        cursor = kids[0] if kids else None

    assert len(visited) == len(migrations), (
        f"chain incomplete: visited {len(visited)} of {len(migrations)} "
        f"({visited})"
    )


def test_current_head_is_magic_link_token_email_encrypted() -> None:
    """After B.2.2-amend the chain head is 0006_magic_link_token_email_encrypted.

    (B.2.2 originally headed at 0005; a design gap surfaced during B.2.3
    planning required adding email_encrypted to magic_link_token —
    see docs/phase-b2-plan.md §4 + the 0006 migration docstring.)
    """
    migrations = _load_all_migrations()
    revisions = {m.revision for _, m in migrations}
    children: dict[str, list[str]] = {rev: [] for rev in revisions}
    for _, m in migrations:
        if m.down_revision is not None:
            children[m.down_revision].append(m.revision)

    heads = [rev for rev, kids in children.items() if not kids]
    assert heads == ["0006_magic_link_token_email_encrypted"], (
        f"expected single head 0006_magic_link_token_email_encrypted; "
        f"found {heads}"
    )


def test_expected_revisions_present() -> None:
    """All revisions through B.2.2-amend land in this branch."""
    revisions = {m.revision for _, m in _load_all_migrations()}
    expected = {
        "0001_baseline",
        "0002_account",
        "0003_user",
        "0004_session",
        "0005_magic_link_token",
        "0006_magic_link_token_email_encrypted",
    }
    assert expected.issubset(revisions), (
        f"missing revisions: {expected - revisions}"
    )


def test_alembic_env_imports_models_package() -> None:
    """env.py must `from app.db.models import *` so target_metadata sees
    User, UserSession, MagicLinkToken (added in B.2.2) without manual edit."""
    code = (_REPO_ROOT / "backend" / "alembic" / "env.py").read_text(
        encoding="utf-8"
    )
    assert "from app.db.models import *" in code


def test_models_package_reexports_b22_models() -> None:
    """Re-exports must include the B.2.2 models or env.py won't see them."""
    from app.db.models import __all__ as exports

    for name in ("Account", "User", "UserSession", "MagicLinkToken"):
        assert name in exports, f"app.db.models.__all__ missing {name!r}"
