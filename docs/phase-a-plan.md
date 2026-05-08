# Phase A — Implementation Plan (final)

This document is the per-task breakdown for Phase A. It is the authoritative reference once execution begins. The architecture lock (`docs/adr/ARCHITECTURE-LOCK.md`) governs *what* we do; this plan governs *how and in what order*.

## Goal

Establish the foundations every locked ADR will rely on, without changing observable behavior of the current MVP. The existing `/analyze-business` endpoint and the React form continue working throughout.

## Entry conditions (must hold before A.2)

1. `docs/adr/ARCHITECTURE-LOCK.md` committed.
2. 34 ADR files committed at `docs/adr/ADR-NNN-*.md`.
3. `pre-phase-a-baseline` git tag exists at the pre-A.1 HEAD.
4. Railway region confirmed as US East.
5. Andrew has acknowledged the commit boundaries in `ARCHITECTURE-LOCK.md` Part 7.

## Exit conditions (Phase A is "done" when)

- All 30 ADRs structurally satisfiable in the repo (no contradicting code paths).
- Staging environment live on Railway with `api` + `web` services.
- CI green on every merge to `main`.
- Sentry receiving events from both backend and frontend.
- Rollback drill performed and documented.

## Task breakdown

### A.0 — Tag baseline (no commit)

**What.** `git tag -a pre-phase-a-baseline -m "..."` at current HEAD.
**Done when.** Tag exists; visible via `git tag --list`.
**Status.** Complete.

### A.1 — Root hygiene + ADR docs (this commit)

**What.** Append Python/editor/OS/Claude block to `.gitignore` (preserving existing 144 lines). Create `docs/adr/ARCHITECTURE-LOCK.md`, `docs/adr/README.md`, 34 `ADR-NNN-*.md` files. Create `CONTRIBUTING.md`, `docs/phase-a-plan.md`, `docs/rollback-assumptions.md`, `docs/migration-assumptions.md`, `docs/scaling-assumptions.md`. Update `README.md` (pending verification).
**Touches.** `.gitignore`, `docs/`, `CONTRIBUTING.md`, `README.md`.
**Done when.** All files committed. CI passes (CI not yet wired; trivial pass).
**Reverts cleanly.** Yes — single commit, can be reverted with `git revert <sha>`.

### A.2 — Commit existing untracked sources at baseline

**What.** `git add app/ frontend/ requirements.txt run_batch_test.py` and commit. Captures the current behavior as a tracked baseline before any restructuring.
**Touches.** Adds `app/**`, `frontend/**` (excluding ignored), `requirements.txt`, `run_batch_test.py` to git.
**Risk check.** Verify no `.env*`, secrets, or `node_modules/` slip in (gitignore from A.1 prevents most). Verify `frontend/node_modules/` is ignored. Verify `.venv/` is ignored.
**Done when.** Single commit, working tree clean except `.claude/settings.local.json` (now ignored).
**Reverts cleanly.** Yes — `git reset --hard HEAD~1` or revert.

### A.3 — Move backend, adopt pyproject.toml

**What.**
- Create `backend/` directory.
- Move `app/__init__.py`, `app/main.py`, `app/schemas.py`, `app/scoring.py`, `app/signals.py`, `app/clients/__init__.py`, `app/clients/google_business.py` to `backend/app/...` (with new subdirs `domain/`, `clients/`, `api/`, `core/`).
- Move `app/scoring.py` and `app/signals.py` into `backend/app/domain/`.
- Create `backend/pyproject.toml` declaring package = `app`, package-dir = `.` so existing `from app.X` imports continue to resolve.
- `pip install -e backend/` works locally.
- Delete root `requirements.txt` (replaced by pyproject).

**Risk check.** Run `uvicorn app.main:app --reload` from `backend/` and POST to `/analyze-business`; result must equal pre-move output for a known input.
**Done when.** Same behavior, new layout. CI green.
**Reverts cleanly.** `git revert` restores `app/` at root and `requirements.txt`.

### A.4 — Core layer (config, logging, errors, middleware)

**What.** Create:
- `backend/app/core/config.py` — pydantic-settings, reads every env var enumerated in `.env.example`.
- `backend/app/core/logging.py` — structlog JSON config.
- `backend/app/core/errors.py` — global exception handler + stable error envelope.
- `backend/app/core/middleware.py` — request-ID middleware, CORS, in-process token-bucket rate limit.
- `backend/app/core/observability.py` (stub for A.12).
- `.env.example` (root).

`backend/app/main.py` updated to register middleware + handlers.

**Risk check.** All previous routes still respond identically. Errors return JSON envelope, not Python tracebacks.
**Done when.** Tests in A.9 pass; manual smoke clean.
**Reverts cleanly.** Yes.

### A.5 — Versioned API + legacy alias

**What.**
- Create `backend/app/api/__init__.py`, `backend/app/api/v1/__init__.py`.
- Create `backend/app/api/v1/health.py` (`GET /v1/health`).
- Create `backend/app/api/v1/analyses_legacy.py` (`POST /v1/analyses-legacy`).
- Keep alias `POST /analyze-business` mapped to the same handler for backward compat.
- Remove old `GET /health` (replaced by `/v1/health`).
- OpenAPI configured at `/v1/openapi.json`.

**Risk check.** Frontend still works via the alias. Batch script still works against `/analyze-business`.
**Done when.** Both routes return identical responses.
**Reverts cleanly.** Yes.

### A.6 — Frontend api client

**What.**
- Create `frontend/src/lib/api.js` exporting `apiFetch(path, init)` that reads `VITE_API_BASE_URL` and emits `X-Request-ID`.
- Update `frontend/src/App.jsx` to use `apiFetch("/v1/analyses-legacy", ...)` (or alias).
- Create `frontend/.env.example` with `VITE_API_BASE_URL`.
- Update `frontend/vite.config.js` to read base URL from env; preserve dev proxy for backward compat.

**Risk check.** `npm run dev` still loads form; submission still works.
**Done when.** Manual test in browser passes.
**Reverts cleanly.** Yes.

### A.7 — Frontend layout cleanup

**What.**
- Move `frontend/ResultsPage.jsx` → `frontend/src/ResultsPage.jsx`.
- Update `frontend/tailwind.config.js` to remove the `./ResultsPage.jsx` special case.
- Update `frontend/src/App.jsx` import path.

**Risk check.** Form → results page navigation works identically.
**Done when.** Manual test passes; Tailwind builds without warnings.
**Reverts cleanly.** Yes.

### A.8 — Batch script relocation

**What.**
- Move `run_batch_test.py` → `infra/scripts/batch_score.py`.
- Replace hardcoded paths with `argparse` (`--input`, `--output`, `--base-url`).
- Add `infra/scripts/README.md`.

**Risk check.** Batch script can be invoked with explicit args and produces identical output for a known CSV.
**Done when.** README documents usage; smoke run on small CSV produces correct scored output.
**Reverts cleanly.** Yes.

### A.9 — Test harness

**What.**
- `backend/tests/conftest.py` — fixtures.
- `backend/tests/test_health.py` — `GET /v1/health` returns 200.
- `backend/tests/test_analyses_legacy.py` — happy path POST.
- `backend/tests/test_signals.py` — at least one signal pure-function test.
- `frontend/vitest.config.js`.
- `frontend/src/lib/api.test.js` — apiFetch wrapper test.
- `frontend/src/ResultsPage.test.jsx` — render smoke test.

**Risk check.** `pytest` and `npm test` both green locally.
**Done when.** Both test runners exit 0.
**Reverts cleanly.** Yes (just removes tests).

### A.10 — CI workflows

**What.**
- `.github/workflows/ci.yml` — on PR + push to main: lint, type check (mypy strict on `core/` only initially), pytest, vitest.
- `.github/workflows/deploy-staging.yml` — on push to `main`, deploy to Railway staging.
- `.github/workflows/deploy-production.yml` — on `v*` tag push, deploy to Railway production.

**Risk check.** Run a no-op PR; confirm CI runs and passes.
**Done when.** Workflows visible in GitHub Actions tab; staging deploy triggers on main merge.
**Reverts cleanly.** Yes.

### A.11 — Railway environment scaffolding

**What.**
- `infra/railway/README.md` — describes services, env vars, region.
- `infra/railway/staging.env.template` and `production.env.template` — keys only, never values.
- Provision Railway project + environments via Railway dashboard (out-of-band; documented in README).
- Services per environment: `api` and `web` only (no Postgres/Redis until Phase B).
- Region: US East.

**Risk check.** Staging deploys successfully; production exists but is empty until first tag.
**Done when.** Staging URL responds; documented.
**Reverts cleanly.** N/A for Railway provisioning; can tear down environments.

### A.12 — Observability

**What.**
- `backend/app/core/observability.py` — Sentry init, called from `main.py`.
- `frontend/src/lib/sentry.js` — Sentry browser init, called from `main.jsx`.
- Sentry DSN env vars set per Railway environment.

**Risk check.** Throw a deliberate test error from a temporary endpoint; verify it appears in Sentry with `request_id`.
**Done when.** Test event visible; remove temporary endpoint.
**Reverts cleanly.** Yes.

### A.13 — Phase A exit checklist

**What.** `docs/phase-a-exit.md` — completion checklist + rollback drill record.

**Done when.** Checklist filled in, rollback drill performed and documented.

## Per-task review gates

Each task is its own PR. Andrew reviews and merges. No task may begin until the previous task is merged to `main`.

## What Phase A does NOT do

- No database, ORM, or migrations. Phase B.
- No auth or sessions. Phase B.
- No queue, no Redis, no worker service. Phase C.
- No real signals; mock signals stay. Phase D.
- No Stripe webhook or entitlement enforcement. Phase E.
- No Twilio. Phase F.
- No imports v2. Phase G.
- No LLM calls. Phase H.

These are constraints Phase A's foundation must not violate. If A.X tempts you to add scope that touches one of the above, push back to a later phase.
