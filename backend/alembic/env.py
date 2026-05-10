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
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base

# Future: `from app.db.models import *  # noqa` — added in B.1.4 once any model exists.

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
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
