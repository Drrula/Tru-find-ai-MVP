# `backend/alembic`

Alembic migrations. Per `docs/phase-b-plan.md` §4.

## Run from `backend/` directory

All commands assume CWD is `backend/`. The async engine + Settings integration is wired in `alembic/env.py` — `sqlalchemy.url` reads from `Settings.database_url` (dev default in dev; required in staging / production).

### Apply migrations

```bash
cd backend
alembic upgrade head
```

In dev this targets `postgresql+asyncpg://trufindai:trufindai@localhost:5432/trufindai`. Bring up the DB first (see `infra/dev/README.md`):

```bash
docker compose -f infra/dev/docker-compose.yml up -d postgres
```

### Inspect

```bash
alembic current   # currently-applied revision
alembic history   # full revision graph
alembic heads     # current head(s)
```

### Roll back

```bash
alembic downgrade -1     # one revision back
alembic downgrade base   # all the way to baseline (empty schema)
```

### Create a new migration

```bash
alembic revision --rev-id NNNN_slug -m "human description"
```

The `--rev-id` is the canonical revision string AND the filename (per `alembic.ini` `file_template = %(rev)s`). Examples:

- `alembic revision --rev-id 0003_user -m "user table"` → `versions/0003_user.py`
- `alembic revision --rev-id 0004_session -m "session table"` → `versions/0004_session.py`

Per `docs/phase-b-plan.md` §4 naming rules: zero-padded sequential `NNNN_slug`. Single linear history; no branching in B.1.

After generating, edit:
- `down_revision` → the prior revision string (alembic auto-fills based on `heads`).
- `upgrade()` → the schema change.
- `downgrade()` → the inverse.

Per ADR-027: each migration is one logical change. Destructive operations (DROP COLUMN, RENAME, type narrowing) split into expand → migrate → contract migrations across at least two deploys.

### What lives here in B.1.3

- `alembic.ini` (at `backend/`) — config; URL placeholder overridden by `env.py`.
- `env.py` — async-aware runner; reads `Settings.database_url`.
- `script.py.mako` — template for new revisions.
- `versions/0001_baseline.py` — empty baseline migration. Establishes the `alembic_version` tracking table; no schema change.

### What lands later

- `versions/0002_account.py` — first real table (`account`), with the matching `app.db.models.account.Account` model. B.1.4.
- Per-table migrations follow as new tables come online (per `docs/phase-b-plan.md` §9 boundaries).

### Manual smoke (run before each migration ships)

```bash
cd backend
docker compose -f ../infra/dev/docker-compose.yml up -d postgres
alembic upgrade head
alembic current
alembic downgrade -1
alembic upgrade head
```

If the up/down/up cycle completes without error, the migration is shippable. CI does not run alembic against a real DB in B.1 (per plan §3 / §11 — testcontainers deferred); manual smoke is the gate.
