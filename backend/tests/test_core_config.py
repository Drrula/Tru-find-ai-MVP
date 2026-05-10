"""B.1.1 tests for Settings: DATABASE_URL validator + DATABASE_ECHO field.

Per docs/phase-b-plan.md §6 (env-var contract). The validator:
  - dev: auto-fills with the docker-compose default when unset.
  - staging / production: requires DATABASE_URL explicitly; fails fast otherwise.

All tests `monkeypatch.delenv("DATABASE_URL")` defensively — pydantic-settings
reads from os.environ, and a stray DATABASE_URL in the test shell would
silently override the test scenario.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

_DEV_URL = "postgresql+asyncpg://trufindai:trufindai@localhost:5432/trufindai"


def test_database_url_dev_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development")
    assert s.database_url == _DEV_URL


def test_database_url_dev_explicit_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    explicit = "postgresql+asyncpg://other:pass@host:5432/db"
    s = Settings(_env_file=None, app_env="development", database_url=explicit)
    assert s.database_url == explicit


def test_database_url_required_in_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, app_env="staging")


def test_database_url_required_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, app_env="production")


def test_database_url_provided_in_staging_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    explicit = "postgresql+asyncpg://prod:pass@host:5432/db"
    s = Settings(_env_file=None, app_env="staging", database_url=explicit)
    assert s.database_url == explicit


def test_database_echo_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_ECHO", raising=False)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development")
    assert s.database_echo is False


def test_database_echo_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development", database_echo=True)
    assert s.database_echo is True
