"""B.1.3 introspection tests for alembic scaffolding.

Per docs/phase-b-plan.md §4. Real `alembic upgrade head` requires a
running Postgres — that's documented as manual verification (run
against the docker-compose DB) and not exercised in CI for B.1.

These tests verify file presence, syntax, and the baseline migration's
revision metadata. They do NOT execute the alembic env runner (which
would attempt to construct an engine).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

# Tests run from project root; pyproject.toml [tool.pytest.ini_options]
# sets testpaths=["tests"] but rootdir is `backend/`, so paths are
# relative to the repository root for these scaffolding-presence checks.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_ini_exists() -> None:
    """alembic.ini lives at backend/ root."""
    assert (_REPO_ROOT / "backend" / "alembic.ini").is_file()


def test_alembic_env_is_valid_python() -> None:
    """env.py parses cleanly (does not execute it — that would try to connect)."""
    code = (_REPO_ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    ast.parse(code)


def test_alembic_script_template_exists() -> None:
    """script.py.mako template is present so `alembic revision` can render it."""
    assert (_REPO_ROOT / "backend" / "alembic" / "script.py.mako").is_file()


def test_baseline_migration_present_with_expected_revision() -> None:
    """The 0001_baseline migration file exists with the expected revision string."""
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0001_baseline.py"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert 'revision: str = "0001_baseline"' in content
    assert "down_revision: Union[str, None] = None" in content


def test_baseline_migration_imports_as_module() -> None:
    """The baseline migration imports as a Python module with the right metadata."""
    path = _REPO_ROOT / "backend" / "alembic" / "versions" / "0001_baseline.py"
    spec = importlib.util.spec_from_file_location("alembic_0001_baseline_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0001_baseline"
    assert module.down_revision is None
    # upgrade/downgrade must exist and be callable
    assert callable(module.upgrade)
    assert callable(module.downgrade)
    # And must be no-ops (baseline) — calling them does not raise
    module.upgrade()
    module.downgrade()


def test_alembic_readme_exists() -> None:
    """README documenting the alembic workflow is present (operator handoff)."""
    assert (_REPO_ROOT / "backend" / "alembic" / "README.md").is_file()
