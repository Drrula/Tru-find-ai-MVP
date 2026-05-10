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
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    from app.core.config import Settings

    explicit = "postgresql+asyncpg://prod:pass@host:5432/db"
    s = Settings(
        _env_file=None,
        app_env="staging",
        database_url=explicit,
        encryption_key="dGVzdA==",
        session_secret="ssss",
    )
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


# --- B.2.1: ENCRYPTION_KEY + SESSION_SECRET validators
# Per docs/phase-b2-plan.md §8.


def _clear_secret_envs(mp: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "ENCRYPTION_KEY", "SESSION_SECRET"):
        mp.delenv(name, raising=False)


def test_encryption_key_dev_default_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_secret_envs(monkeypatch)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development")
    # Dev default is set (a 32-byte zero key, base64-encoded).
    assert s.encryption_key is not None
    assert len(s.encryption_key) > 0


def test_session_secret_dev_default_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_secret_envs(monkeypatch)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development")
    assert s.session_secret is not None
    assert len(s.session_secret) > 0


def test_encryption_key_required_in_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_secret_envs(monkeypatch)
    from app.core.config import Settings

    # database_url provided so the validator advances past it.
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            app_env="staging",
            database_url="postgresql+asyncpg://x:y@h:5432/d",
            session_secret="ssss",  # set so validator doesn't fail on it first
        )


def test_session_secret_required_in_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_secret_envs(monkeypatch)
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(
            _env_file=None,
            app_env="staging",
            database_url="postgresql+asyncpg://x:y@h:5432/d",
            encryption_key="dGVzdA==",
        )


def test_all_required_secrets_provided_in_production_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_secret_envs(monkeypatch)
    from app.core.config import Settings

    s = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+asyncpg://x:y@h:5432/d",
        encryption_key="dGVzdA==",
        session_secret="ssss",
    )
    assert s.app_env == "production"
    assert s.encryption_key == "dGVzdA=="
    assert s.session_secret == "ssss"
