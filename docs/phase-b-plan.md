# Phase B — Implementation Plan

| Field | Value |
|---|---|
| Status | **Planning locked, B.1 unblocked** |
| Date | 2026-05-09 |
| Scope of B.1 | Postgres + async SQLAlchemy + Alembic foundation + first migration (`account` only) + repository pattern boundary |
| Out of scope for B.1 | All other tables, auth, domain repositories, real-DB integration tests in CI, production Postgres |
| Supersedes | none |

This document locks the persistence-layer decisions before any code lands. Each B.1.X commit traces to a section here. Future B.2 / B.3 / B.4 sub-phases extend this plan rather than replacing it.

---

## 1. Inheritance from prior phases (re-stated for clarity)

Phase B inherits the following non-negotiables from the architecture lock:

| Constraint | Source |
|---|---|
| Postgres is the only datastore | ADR-002 |
| Tenancy via `account_id` on every owned/derived row | ADR-008 + Lock §2.1 |
| PII fields stored as `(hash, encrypted)` | ADR-013 |
| Soft-delete via `deleted_at` on user-owned tables | ADR-016 |
| Path-based API versioning preserved | ADR-017 |
| Magic-link auth (Phase B+ delivery, not B.1) | ADR-018 |
| Server-side entitlement (deferred to Phase E) | ADR-019 |
| Additive-only migrations between deploys | ADR-027 |
| Backups + PITR + tested restore | ADR-029 |
| Repository pattern is the only DB access | ADR-031 |
| Idempotency keys explicit on command-style tables | ADR-032 |
| UUIDv7 for all primary keys | ADR-033 |
| Schema target shapes already locked | ARCHITECTURE-LOCK §2.3 / §2.5 / §2.6 |

---

## 2. Postgres topology

| Layer | Posture |
|---|---|
| **Local dev** | `docker-compose.yml` (under `infra/dev/`) with one Postgres 16 service. Operator runs `docker compose up postgres` from repo root. Database name: `trufindai`, user: `trufindai`, password: dev-only constant. Port 5432 exposed to host. |
| **Staging** | Railway Postgres add-on attached to the `staging` environment. Provisioned **first** (per Andrew's direction) before production. Backups: Railway-default daily snapshots; PITR optional in B.1 (recommended before B.2 auth tables). |
| **Production** | Deferred until staging validation completes. Provisioned on Railway with PITR enabled (ADR-029 hard requirement before any write traffic). |
| **Test (CI)** | No real Postgres in B.1. Repository pattern tested with mock sessions; engine + session module tested via introspection. Real-DB integration tests deferred to a future commit (likely with testcontainers when more tables exist to test). |

Single primary, no read replicas in B.1. Region: US East per ARCHITECTURE-LOCK §10 (Railway-side).

---

## 3. SQLAlchemy — async setup

- **Driver:** `asyncpg` (sync `psycopg2`/`psycopg` not used).
- **API:** SQLAlchemy 2.x async (`AsyncEngine`, `AsyncSession`, `async_sessionmaker`).
- **Why async:** matches FastAPI's ASGI runtime (no thread-pool wrapping); aligns with future arq workers (ADR-004) which are also async.
- **Dependency declaration in `backend/pyproject.toml`:**
  ```
  "sqlalchemy>=2.0,<3",
  "asyncpg>=0.29,<1",
  "alembic>=1.13,<2",
  ```
- **Engine lifecycle:** one process-wide `AsyncEngine` constructed at import time in `app.db.engine`; FastAPI dependency `get_session()` yields a per-request `AsyncSession`.
- **Connection pool:** SQLAlchemy default `AsyncAdaptedQueuePool`. PgBouncer / pool-tuning deferred (YAGNI for B.1 traffic; revisit when Phase C workers add concurrency).
- **Type mapping:** `uuid.UUID` (UUIDv7 from `app.core.ids.new_id()`) maps to native Postgres `uuid` column. `datetime.datetime` (UTC) maps to `timestamptz`. JSON payloads use `JSONB` not `JSON`.
- **DeclarativeBase:** single `Base` class in `app.db.base` for all model declarations.

---

## 4. Alembic — migration strategy

### Layout
```
backend/
  alembic.ini
  alembic/
    env.py              # async-aware (uses AsyncEngine + run_sync())
    script.py.mako
    versions/
      0001_baseline.py  # empty; establishes alembic_version table
      0002_account.py   # first real table (Lock §2.3 account)
    README.md           # operator notes: how to create + apply migrations
```

### Naming & versioning rules

- **Filename pattern:** `<NNNN>_<short_slug>.py` where `NNNN` is a zero-padded sequential integer. Examples: `0001_baseline.py`, `0002_account.py`, `0003_user.py`.
- **`revision` string:** matches the prefix and slug, e.g. `revision = "0001_baseline"`. Alembic uses this as the canonical identity; the filename is just for sort order in the directory.
- **`down_revision`:** explicitly names the prior revision. Linear history only — no branches in B.1.
- **One logical change per migration.** Don't batch unrelated table additions into one file.
- **Per ADR-027 (additive between deploys):** a destructive change (DROP COLUMN, RENAME, type narrowing) is split into expand → migrate → contract migrations across at least two deploys. CI lint check for forbidden `DROP COLUMN` / `ALTER ... RENAME` in single migrations is deferred (manual review for B.1; automated check before any destructive migration ships).

### Up/down expectations

- Every migration has both `upgrade()` and `downgrade()` defined.
- `downgrade()` must successfully restore the prior schema state for the **most recent** migration. For older migrations, `downgrade()` may be empty/`pass` if the change is permanent (rare; document in the file header).
- Migrations never contain data backfills. Backfills are separate jobs/scripts; migrations only change schema.

### Apply / inspect commands (for the README)

- `alembic upgrade head` — apply all pending migrations.
- `alembic current` — show the currently-applied revision.
- `alembic history` — show the full revision graph.
- `alembic downgrade -1` — roll back one revision.
- `alembic check` — verify the model definitions match the migration head (no drift).

---

## 5. Repository pattern boundary (per ADR-031)

### Layout
```
backend/app/db/
  __init__.py
  base.py              # DeclarativeBase
  engine.py            # AsyncEngine + DATABASE_URL wiring
  session.py           # async_sessionmaker + get_session() dependency
  models/
    __init__.py
    account.py         # SQLAlchemy model for the account table
  repositories/
    __init__.py
    base.py            # BaseRepository (tenancy filter, soft-delete filter)
    account_repo.py    # AccountRepository (the only repo in B.1)
```

### `BaseRepository` contract

- Generic over the model type: `BaseRepository[ModelT]`.
- Constructor takes `(session: AsyncSession, account_id: UUID | None)`. `account_id=None` is reserved for system contexts (audit log writes, system events) and must be explicit.
- Default-filters every read by `account_id` and `deleted_at IS NULL` for tables that have those columns (introspected via SQLAlchemy column metadata).
- Provides primitive operations: `get(id)`, `find_one(**filters)`, `find_many(**filters)`, `add(model)`, `soft_delete(id)`. More specific operations live in subclasses.
- `force_include_deleted` and `force_cross_account` are explicit boolean kwargs that escape the defaults; both must be opted into and (when persistence-touching audit lands) write an `audit_log` entry.
- No raw SQL or ORM queries permitted in `app.domain.*` — they go through repos. CI lint check deferred.

### `AccountRepository` (only repo in B.1)

- Subclass of `BaseRepository[Account]`.
- Methods: `get(id)`, `create(display_name, parent_account_id=None)`, `soft_delete(id)`, `find_by_status(status)`.
- `account_id` filter is **off** for this repo (the account table IS the tenancy root; filtering by self would be circular). Explicit override in the subclass.

---

## 6. Env var contract (additions in B.1)

| Var | Required when | Notes |
|---|---|---|
| `DATABASE_URL` | `APP_ENV != "development"` (i.e. staging + production must set it) | Format: `postgresql+asyncpg://user:pass@host:port/dbname`. Local dev defaults to `postgresql+asyncpg://trufindai:trufindai@localhost:5432/trufindai` (matches docker-compose) when the env var is unset. |
| `DATABASE_ECHO` | optional | When `true`, SQLAlchemy logs all SQL statements. Default `false`. Use for local debugging only. |

No new env vars beyond these in B.1. `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` deferred — SQLAlchemy defaults are fine.

`backend/app/core/config.py` `Settings` class gains:
- A validator that requires `DATABASE_URL` when `app_env != "development"` (fails fast at startup).
- A computed `DATABASE_URL` default for local dev.

`.env.example` and the Railway `staging.env.template` / `production.env.template` already list `DATABASE_URL` — no template change needed.

---

## 7. Backup / PITR assumptions

| Environment | Backups | PITR | First restore drill |
|---|---|---|---|
| Local dev | None expected (ephemeral data) | N/A | N/A |
| Staging | Daily snapshots (Railway default) | Optional in B.1; **required before B.2 auth tables land** (so any leaked credential rotation has a defensible recovery point) | Quarterly per ADR-029, starting with first staging-real DB write |
| Production | Daily snapshots + **PITR enabled** before any write traffic (ADR-029) | Required from day one of production write access | Quarterly per ADR-029 |

Andrew enables PITR via Railway dashboard (Postgres add-on settings). The README at `infra/railway/README.md` will be updated in B.1.4 with the exact dashboard path.

---

## 8. Rollback expectations

Three layers, each with its own procedure:

### Code-level rollback (existing — Phase A drill verified)

`git revert <commit>` → CI runs → if `main` → deploy-staging redeploys. Recovery <1 sec to known-good test suite.

### Migration-level rollback

For the **most recent** migration: `alembic downgrade -1`. Verified in B.1.4 against the docker-compose Postgres before the migration is considered shipped.

For **older** migrations: per ADR-027, all migrations are additive between deploys, so reverting code never requires reverting the migration. The migration's `downgrade()` exists for completeness but is rarely exercised in production.

### Data-level rollback

- Staging: from the most recent daily snapshot. Acceptable data loss: up to 24h.
- Production (when provisioned): PITR → restore to a specific timestamp. Acceptable data loss: <5 min.
- Quarterly drill: restore yesterday's snapshot into a scratch database, run a smoke query (e.g. `SELECT count(*) FROM account`), document elapsed time + any friction in `docs/ops/restore-drills/YYYY-QN.md`.

---

## 9. Initial schema boundaries

### What B.1 creates
- `account` table only (Lock §2.3 spec):
  - `id uuid PK` (UUIDv7 application-side)
  - `display_name text NOT NULL`
  - `parent_account_id uuid NULL REFERENCES account(id)` (for future agency/white-label)
  - `status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed'))`
  - `created_at`, `updated_at`, `deleted_at` timestamptz
- `INDEX (parent_account_id) WHERE parent_account_id IS NOT NULL`
- `alembic_version` (alembic-managed, automatic)

### What B.1 does NOT create

| Phase | Tables (per Lock §2.3 / §2.5 / §2.6) | Sub-phase |
|---|---|---|
| B.2 | `user`, `session`, `magic_link_token` (identity + magic-link auth) | next |
| B.3 | `vertical`, `vertical_template`, `signal_definition`, `vertical_signal_weight`, `vertical_prompt_version`, `vertical_copy` (verticals as data per ADR-011) | after B.2 |
| B.3 | `business`, `analysis_run`, `signal_result`, `gap`, `competitor_snapshot`, `ai_probe`, `verification_result` (business + analysis machinery) | same sub-phase as verticals |
| B.4 | `lead`, `lead_signal_definition`, `vertical_lead_signal_weight`, `lead_signal`, `lead_dimension`, `lead_event_*`, `vertical_lead_event_weight`, `lead_event`, `lead_enrichment`, `lead_source_attribution` (lead intelligence per ADRs 035–040, 044) | **gated on §5.13 attorney-input recheck before lead persistence** |
| B.5 | `import_batch`, `import_row` | after B.3 |
| B.E (Phase E) | `purchase`, `entitlement`, `stripe_event`, `billing_subscription`, `invoice`, `invoice_line`, `refund`, `credit`, `billing_address`, `tax_jurisdiction`, `tax_exemption`, `billing_event` | Phase E |
| B.F (Phase F) | `lead`, `opt_out`, `sms_thread`, `sms_message`, `phone_record`, `phone_observation`, `phone_reassignment_check`, `compliance_policy`, `compliance_policy_evaluation`, `blocklist` | Phase F |
| System | `external_cache`, `audit_log`, `feature_flag`, `job_run` | as needed by consuming phase |

The aggregate target shape is already locked in ARCHITECTURE-LOCK §2; B.X sub-phases just deliver the migrations.

---

## 10. §5.13 GDPR-erase posture

Per Andrew's direction:
- **Do not block all of Phase B on §5.13 attorney input.**
- **Default working assumption:** soft-delete + auditability (per ADR-016 + ADR-015). Hard-erase / anonymize-in-place semantics revisited **before B.4 lead persistence** lands.
- B.1's `account` table follows the working assumption: `deleted_at` for soft-delete, no GDPR-erase routine yet.
- `audit_log` table doesn't exist yet (system-table category, lands when consuming phase needs it). Audit calls in B.1 repositories are stubs that log warnings until the table exists.

---

## 11. Intentionally deferred from B.1

| Item | Defer to | Reason |
|---|---|---|
| Tables beyond `account` | B.2+ (per §9 above) | Each is its own scoped migration |
| Auth (magic-link) | B.2 | Depends on `user` + `session` + `magic_link_token` tables |
| Domain repositories | Each table's introducing sub-phase | YAGNI: `BusinessRepository` lands with the `business` table |
| Real-DB integration tests in CI | Future sub-phase + testcontainers | Heavy CI runners; not worth it for one table |
| `audit_log` table + writes | System-table sub-phase, gated by first consumer | Stub the call surface for now |
| `external_cache` table | Phase D (real signals) | Not needed until external HTTP starts |
| PgBouncer | Phase C+ | YAGNI for B.1 traffic |
| Read replicas | Phase 3 | Not needed at B-phase scale |
| Production Postgres provisioning | After B.1 staging validation | Per Andrew's direction |
| Cross-region anything | Permanently out of v1 scope | Per ARCHITECTURE-LOCK §10 (US East only) |
| CI lint check for raw queries / forbidden migration patterns | Future cleanup commit | Manual review enforces for now |

---

## 12. B.1 sub-task breakdown

Each sub-task is one commit, verify-then-commit per the locked phase-gating rule.

| Sub | Title | Files (new/modified) | Verifies |
|---|---|---|---|
| **B.1.0** | Phase B planning doc | `docs/phase-b-plan.md` (this file) | Plan exists; future commits trace to it |
| **B.1.1** | Dependencies + DB config + docker-compose | `backend/pyproject.toml` (+sqlalchemy, asyncpg, alembic) · `backend/app/core/config.py` (+DATABASE_URL validator + dev default) · `infra/dev/docker-compose.yml` (new) · `infra/dev/README.md` (new) | `pip install -e "backend[dev]"` succeeds · existing 58/58 backend tests still pass · `docker compose up -d postgres` runs locally |
| **B.1.2** | SQLAlchemy engine + session module | `backend/app/db/__init__.py` · `backend/app/db/engine.py` · `backend/app/db/session.py` · `backend/app/db/base.py` · `backend/tests/test_db_engine.py` | Module imports cleanly · `get_session()` is an async generator yielding `AsyncSession` (introspection test, no DB call) |
| **B.1.3** | Alembic baseline + scaffolding | `backend/alembic.ini` · `backend/alembic/env.py` · `backend/alembic/script.py.mako` · `backend/alembic/versions/0001_baseline.py` · `backend/alembic/README.md` | `alembic upgrade head` runs cleanly against docker-compose Postgres (manual verify; not in CI) · `alembic history` shows just the baseline |
| **B.1.4** | First migration: `account` table + model | `backend/alembic/versions/0002_account.py` · `backend/app/db/models/__init__.py` · `backend/app/db/models/account.py` · update `infra/railway/README.md` with PITR-enable instructions | `alembic upgrade head` creates the table · `alembic downgrade -1` removes it cleanly · manual SELECT against the docker-compose DB shows the table |
| **B.1.5** | Repository pattern boundary | `backend/app/db/repositories/__init__.py` · `backend/app/db/repositories/base.py` · `backend/app/db/repositories/account_repo.py` · `backend/tests/test_db_repositories.py` (mock sessions; tenancy filter; soft-delete filter; UUIDv7 PK generation) | New tests pass; existing 58/58 still pass |

5 commits + 1 planning commit (this) = 6 total for B.1. Same per-commit discipline as Phase A.

---

## 13. What this plan explicitly does NOT lock

- The exact column types/constraints for tables beyond `account` (those are locked in ARCHITECTURE-LOCK §2.3, not here; B.X+ sub-phases just deliver them).
- The migration ordering for B.2+ sub-phases (depends on which table's introducing phase reaches its gate first).
- The CI lint rules (deferred per §11).
- The exact PgBouncer / pooling configuration (deferred per §11).
- The §5.13 final answer (defer-then-revisit per §10).

---

## 14. Sign-off

| Action | Locked | Notes |
|---|---|---|
| Async SQLAlchemy + asyncpg | ✓ | Per Andrew direction |
| Empty alembic baseline + separate `account` migration | ✓ | Cleaner separation |
| Mock-session repository tests; no real-DB CI | ✓ | YAGNI for one-table B.1 |
| docker-compose for local dev | ✓ | Per Andrew direction |
| Default SQLAlchemy pool | ✓ | YAGNI |
| `account` only in B.1 | ✓ | Per scope discipline |
| Sequential `NNNN_slug.py` migration naming | ✓ | Sort order + readability |
| Soft-delete + audit working assumption (§5.13 deferred) | ✓ | Per Andrew direction; revisit before B.4 |
| Staging Postgres before production | ✓ | Per Andrew direction |
| PITR required before B.2 auth tables (staging) and from day-one (production) | ✓ | Per ADR-029 + Andrew direction |

## 15. Next gate

| Action | Requires |
|---|---|
| Commit this plan | (this commit) |
| Push | `push` |
| Begin B.1.1 (deps + config + docker-compose) | `proceed B.1.1` |

No auto-proceed beyond this planning commit.
