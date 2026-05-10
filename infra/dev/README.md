# `infra/dev`

Local development infrastructure. **DEV ONLY** — these resources use hardcoded dev credentials and are not suitable for staging or production.

Per `docs/phase-b-plan.md` §2 (topology).

## Postgres

A single Postgres 16 container that the SQLAlchemy + asyncpg layer connects to when `DATABASE_URL` is unset and `APP_ENV=development`.

### Bring up

```bash
docker compose -f infra/dev/docker-compose.yml up -d postgres
```

### Verify it's healthy

```bash
docker compose -f infra/dev/docker-compose.yml exec postgres pg_isready -U trufindai -d trufindai
```

Or directly via psql (if installed):

```bash
psql "postgresql://trufindai:trufindai@localhost:5432/trufindai" -c "SELECT 1;"
```

### Tear down (preserve data)

```bash
docker compose -f infra/dev/docker-compose.yml down
```

### Tear down + delete data

```bash
docker compose -f infra/dev/docker-compose.yml down -v
```

This removes the named volume `trufindai_pg_data` and forces a clean re-init on next `up`.

## Connection details

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `trufindai` |
| User | `trufindai` |
| Password | `trufindai` |
| URL (asyncpg) | `postgresql+asyncpg://trufindai:trufindai@localhost:5432/trufindai` |

The `Settings` class auto-fills this URL when `DATABASE_URL` is unset and `APP_ENV=development`. For staging / production the URL is set per Railway environment per the `infra/railway/*.env.template` files (and is required — startup fails fast if absent in non-dev envs).

## What this is NOT

- Not for staging — Railway hosts staging Postgres.
- Not for production — Railway hosts production Postgres with PITR enabled (per ADR-029).
- Not a backup-tested instance — use `down -v` to reset; nothing here is durable beyond your local volume.
- Not auth-bearing — credentials are constants, suitable only for a dev laptop.
