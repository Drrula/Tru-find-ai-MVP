"""Alembic environment.

Per docs/phase-b-plan.md §4. Async-aware: uses an AsyncEngine and runs
migrations via `connection.run_sync()`. Reads `sqlalchemy.url` from
`app.core.config.Settings.database_url` so the URL discipline is shared
with the runtime engine (dev default in dev; required in staging /
production; fails fast otherwise).

Models live under `app.db.models.*` and inherit from `app.db.base.Base`.
The package may be empty at any given commit (B.1.3: empty; B.1.4+:
models registered as they're added). `target_metadata = Base.metadata`
sees whatever models have been imported by the time alembic runs.

B.6A.5-fix (2026-05-12): pre-create `alembic_version` with
VARCHAR(128) on fresh DBs. Alembic's default schema is VARCHAR(32);
some of our revision identifiers exceed that
(`0006_magic_link_token_email_encrypted` is 38 chars,
`0020_seed_demo_account_vertical_catalog` is 39 chars). The pre-flight
runs before alembic's own table bootstrap so alembic finds an
existing table and skips its (too-narrow) CREATE TABLE.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base

# Register ORM models with Base.metadata so alembic autogenerate sees them.
# B.1.4 adds the Account model; subsequent sub-phases extend models/__init__.py.
from app.db.models import *  # noqa: F401, F403

# Alembic Config object — read from alembic.ini
config = context.config

# Override sqlalchemy.url with the runtime-resolved value from Settings.
# Settings._resolve_database_url already enforces dev default + non-dev
# required; alembic just inherits that contract.
settings = get_settings()
assert settings.database_url is not None
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configure stdlib logging from the .ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without DBAPI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_alembic_version_wide_enough(connection: Connection) -> None:
    """Pre-create `alembic_version` with VARCHAR(128) on fresh DBs.

    Alembic's default `alembic_version.version_num` is `VARCHAR(32)`,
    which is too narrow for some revision identifiers in this
    codebase (`0006_magic_link_token_email_encrypted` = 38 chars,
    `0020_seed_demo_account_vertical_catalog` = 39 chars). Alembic
    uses "create only if it doesn't exist" semantics for the version
    table; if we pre-create it with a wider column, alembic skips
    its own creation and uses our schema.

    Idempotent: no-op if `alembic_version` already exists. Does NOT
    auto-ALTER a too-narrow existing column -- that's a manual
    operator step for any dev DB that ran migrations against the
    pre-fix VARCHAR(32) column:

        ALTER TABLE alembic_version
        ALTER COLUMN version_num TYPE VARCHAR(128);

    Fresh DBs (including CI's Postgres service) hit this code path
    BEFORE alembic's own bootstrap, so they get VARCHAR(128) from
    the start.
    """
    inspector = sa.inspect(connection)
    if inspector.has_table("alembic_version"):
        return
    connection.execute(
        sa.text(
            "CREATE TABLE alembic_version ("
            "version_num VARCHAR(128) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
    )
    # CRITICAL: explicit commit closes the autobegin transaction
    # triggered by the execute() above. Without this commit,
    # alembic's own `context.begin_transaction()` would nest inside
    # an open outer transaction; alembic's migration commits would
    # become savepoint releases, and the outer transaction would
    # roll back on connection close -- silently discarding every
    # CREATE TABLE the migrations ran (CI fix-2 surfaced this
    # exact failure 2026-05-12).
    connection.commit()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,            # detect column type changes during autogen
        compare_server_default=True,  # detect default changes during autogen
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against an AsyncEngine."""
    section = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        # Pre-flight: ensure alembic_version is wide enough BEFORE
        # alembic's own table bootstrap (see helper docstring).
        await connection.run_sync(_ensure_alembic_version_wide_enough)
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
