# `infra/railway`

Operator-facing Railway setup guide. Railway hosts the TruFindAI backend and frontend across **staging** and **production** environments in the **US East** region (per ARCHITECTURE-LOCK §10).

## Production URL

`https://pl300-production.up.railway.app` (Andrew, 2026-05-09).

> ⚠ **Do not deploy or mutate production without explicit approval.** Tag-driven deploys via `deploy-production.yml` will only fire when a `v*` tag is pushed; never push tags without Andrew's confirmation. Manual `railway up --environment production` is also forbidden without explicit approval.

Provisioning is out-of-band (Railway dashboard); CI/CD is in this repo. After one-time setup, deploys are automatic per ADR-026:

| Trigger | Target |
|---|---|
| Push to `main` (after CI passes) | Railway staging |
| Tag `v*` push (e.g. `v0.1.0`) | Railway production |

---

## One-time setup (Andrew)

### 1. Create the Railway project

1. https://railway.app/new
2. Project name: `trufindai`
3. Region: **US East** (per ARCHITECTURE-LOCK §10)

### 2. Create two environments

In project settings → Environments:
- `staging`
- `production`

### 3. Provision services per environment

For **EACH** environment, add two services from this GitHub repo:

#### `api` (backend)
- **Root directory:** `backend/`
- **Auto-detected:** Python (Nixpacks reads `pyproject.toml`)
- **Start command:** read from `backend/Procfile` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
- **Health check path:** `/v1/health`

#### `web` (frontend)
- **Root directory:** `frontend/`
- **Build command:** `npm ci && npm run build`
- **Service type:** Static Site, serving `dist/`
  - Or: Node service with start command `npx serve -s dist -l $PORT`
- **Health check path:** `/` (any 200)

### 4. Set environment variables per service per environment

Use the templates here as the schema. Set values in the Railway dashboard.

| Template | When to use |
|---|---|
| [`staging.env.template`](staging.env.template) | Staging service env vars (test-mode Stripe, sandbox Twilio, etc.) |
| [`production.env.template`](production.env.template) | Production env vars (live keys; coordinate with security policy) |

**Production secrets must never appear in this repo.** The templates are key-only.

### 5. Generate deploy tokens for GitHub Actions

For each environment:
1. Railway → Project → Settings → Tokens → Create new
2. Copy the token value

In GitHub repo settings → Secrets and variables → Actions → New repository secret:
- `RAILWAY_TOKEN_STAGING` — staging token
- `RAILWAY_TOKEN_PRODUCTION` — production token

### 6. Provision Postgres add-on + enable PITR

Per ADR-029 (backups + tested restore) and `docs/phase-b-plan.md` §7. Add-on the Railway Postgres service to each environment via the Railway dashboard (Project → environment → New service → Database → Postgres).

**Production:** PITR (point-in-time recovery) is **required before any production write traffic.** In Railway dashboard:

1. Project → `production` environment → Postgres service → Settings → Backups.
2. Enable point-in-time recovery (PITR).
3. Confirm the PITR retention window matches the Railway plan tier (consult Railway's current Postgres add-on docs for exact retention durations).

**Staging:** PITR is recommended before B.2 auth tables land (so any leaked credential rotation has a defensible recovery point), but optional for the empty `account`-only state in B.1.

**Quarterly restore drill** (per ADR-029):
1. Note the current Postgres LSN / latest backup timestamp.
2. Restore yesterday's snapshot into a scratch database via Railway dashboard.
3. Run smoke query: `SELECT count(*) FROM account;`.
4. Document elapsed time + any friction in `docs/ops/restore-drills/YYYY-QN.md`.

After provisioning, set `DATABASE_URL` on the `api` service per environment to the connection string Railway exposes (typically available as `${{ Postgres.DATABASE_URL }}` reference in the dashboard). The runtime engine + alembic share this URL via `Settings.database_url` (per docs/phase-b-plan.md §3).

### 7. Verify the pipeline

- Push any docs change to `main`. Watch:
  - GitHub Actions → CI runs (~1 min)
  - GitHub Actions → Deploy to Staging runs after CI passes
  - Railway staging → `api` service redeploys
  - `https://<staging-api-url>/v1/health` returns `{"status":"ok"}`
- Tag `v0.1.0` and push tags **(only with Andrew's explicit approval — see "Production URL" guard above)**. Watch:
  - GitHub Actions → Deploy to Production runs (no CI gate; tags are explicit)
  - Railway production → `api` service redeploys
  - `https://pl300-production.up.railway.app/v1/health` returns `{"status":"ok"}`

---

## Deploy flow (automatic after setup)

```
push to main
    ↓
CI workflow (.github/workflows/ci.yml) runs:
    backend pytest + frontend vitest + frontend build
    ↓ (only on success)
deploy-staging.yml runs:
    railway up --service api --environment staging   (uses RAILWAY_TOKEN_STAGING)
    railway up --service web --environment staging
    ↓
Railway staging redeploys both services
```

```
git tag v0.1.0 && git push --tags
    ↓
deploy-production.yml runs:
    railway up --service api --environment production   (uses RAILWAY_TOKEN_PRODUCTION)
    railway up --service web --environment production
    ↓
Railway production redeploys both services
```

Tags are the explicit promotion gate per ADR-026. Cutting a tag is a deliberate "this is production-ready" decision, not an automatic consequence of merging to `main`.

---

## Rollback

### Staging
- `git revert <bad-commit> && git push origin main` → CI → deploy-staging redeploys the prior good state.
- Or Railway dashboard → service → Deployments → Redeploy a previous build.

### Production
- Re-tag a previous known-good commit:
  ```
  git tag v0.1.1 v0.1.0   # tag the prior good ref
  git push --tags
  ```
- Or Railway dashboard → service → Deployments → Redeploy a previous production build.

Per ADR-027, all migrations are additive between deploys. A code rollback never requires a DB rollback.

---

## Costs (rough)

Phase A: 2 services × 2 environments = 4 Railway services. Idle: well under $20/month. Postgres + Redis (Phase B+) add ~$10–20/month each per environment.

---

## Troubleshooting

**Deploy fails with "service not found"**
- Service names in the workflows (`api`, `web`) must match Railway dashboard service names exactly.

**Backend build fails on Python import**
- `pip install -e backend` should succeed locally first. CI verifies this on every push.

**Frontend build fails on `npm ci`**
- `frontend/package-lock.json` must be committed (it is, since A.6).

**CI passes but deploy-staging doesn't run**
- The `deploy-staging.yml` uses `workflow_run` triggered by `CI`. Confirm the CI workflow is named `CI` (not `ci`) — GitHub matches by name.

**Tag push doesn't trigger deploy-production**
- Use `git push --tags` (not just `git push`). Tags don't auto-push.

**`RAILWAY_TOKEN_*` secret not found**
- Secret names must match exactly. Check repo Settings → Secrets and variables → Actions.

**Frontend baked the wrong API URL**
- `VITE_API_BASE_URL` is a build-time variable. Railway must have it set in the `web` service's env vars BEFORE the build runs. Set it per environment.
