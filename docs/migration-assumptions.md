# Migration Assumptions

Explicit list of what each future phase assumes about the foundation laid by Phase A and earlier phases. If a Phase A choice violates any assumption, raise it before merging.

## What "migration" means here

This document covers two distinct senses:

- **Phase migrations** — how Phase B inherits from Phase A, Phase C from B, etc.
- **Schema migrations within a phase** — Alembic discipline (covered by ADR-027 + ADR-029).

## Phase A's contract with future phases

Phase A is a foundation. It must establish certain things that future phases rely on; equivalently, it must not establish things that conflict.

### Things Phase A must provide
- Domain-grouped backend layout under `backend/app/domain/*` (ADR-007).
- `core/config.py` settings layer reading every env var, with safe defaults for unset values.
- `core/logging.py` JSON structured logging with `request_id` propagation.
- `core/errors.py` global exception handler returning a stable JSON envelope.
- `core/middleware.py` CORS, request-ID minting, in-process rate limit (Redis-free until Phase C).
- `core/ids.py` UUIDv7 generator (used from Phase B's first migration).
- `core/observability.py` Sentry initializer (callable from main).
- API surface under `/v1/*` with legacy `/analyze-business` alias (ADR-017).
- Frontend `lib/api.js` as the only HTTP entry point.
- CI on every PR (lint + types + tests).
- Two Railway environments (staging, production), services `api` + `web`.

### Things Phase A must NOT introduce
- No database, no ORM imports, no `db/` directory beyond stub.
- No auth, no sessions, no `account` or `user` tables.
- No queue, no Redis, no worker service.
- No real LLM calls, no Stripe code, no Twilio code.
- No `domain/payments/`, `domain/notifications/`, `domain/ai/` modules with substantive code.
- No persistence of analysis results.

If the temptation to "just add a tiny X" arises during Phase A, push it to its proper phase.

## Phase B (persistence + auth) — assumptions

**Inherits from Phase A:**
- `core/config.py` already exposes the field types needed to add `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`, `ENCRYPTION_KEY`, `MAGIC_LINK_TOKEN_TTL_MIN`. Adding them is a new field, not a new module.
- Domain modules importable at `app.domain.*`; persistence layer can introduce `app.db.*` without touching imports elsewhere.
- API routers do no business logic; adding `Depends(get_current_user)` is mechanical.
- `request_id` is in logging context; once `account_id` exists, it slots into the same context binder.
- UUIDv7 generator in `core.ids` from the first migration onward.

**Must establish in B:**
- Postgres provisioned with PITR enabled (ADR-029) before any write traffic.
- All tables in ARCHITECTURE-LOCK §2.3 created in the first migration.
- `account_id` on every owned/derived table (ADR-008) — non-nullable from the start.
- Repository base class enforcing tenancy + soft-delete (ADR-031).
- PII columns follow `(hash, encrypted)` pattern (ADR-013) — even if first user has no real PII.
- Idempotency-key columns on every command-style table (ADR-032).
- `DatabaseEventPublisher` (ADR-044): resolves `event_type` via registry to the correct projection table (`lead_event` / `audit_log` / `billing_event` / `compliance_policy_evaluation`) and routes through the relevant repository. Promotes the in-process registry to DB-driven (`lead_event_definition` per ADR-040).

**Risk if assumptions break:**
- Missing config slot → adding it later means a separate config refactor commit.
- Domain module imports `app/api/...` (forbidden) → repository can't slot in cleanly.
- `request_id` not in log context → distributed debugging gets retroactively painful.

## Phase C (async API + workers) — assumptions

**Inherits from B:**
- `analysis_run` table exists with the lifecycle in ARCHITECTURE-LOCK §3.1.
- `idempotency_key` columns present.
- Logging is JSON-structured; worker logs follow same format.
- Railway env structure documented; adding `worker` and `redis` services is config only.

**Must establish in C:**
- Redis service in Railway (per environment).
- `arq` worker service with one queue per blast radius (signals, ai, imports, notify, default).
- Switch `/v1/analyses` to async-poll model (ADR-005); legacy alias still works.
- `job_run` table for worker observability.

**Risk if assumptions break:**
- `analysis_run` schema not finalized → worker writes to a moving target.
- No request-ID propagation → enqueued jobs lack correlation back to API call.
- Legacy alias removed prematurely → batch script breaks.

## Phase D (real signals + verticals) — assumptions

**Inherits from B & C:**
- `business`, `analysis_run`, `signal_result`, `vertical_*` tables exist.
- Worker queues `signals` and `default` exist.
- `external_cache` table exists; `Cached(client)` wrapper exists.
- `signal_definition` table exists; per-signal toggles via `vertical_signal_weight.enabled`.

**Outstanding decisions that must resolve before D:**
- §5.4 vertical taxonomy management surface.
- §5.5 weight resolution semantics (default vs fail-loud).

**Must establish in D:**
- One real signal at a time, behind `SIGNAL_<NAME>_REAL=1` flag.
- Real Google Places client; cache TTLs documented.
- Vertical config seeded for first vertical (e.g. roofers).

## Phase E (payments) — assumptions

**Inherits from B:**
- `account`, `business`, `entitlement`, `purchase`, `stripe_event` tables exist.
- `audit_log` exists.
- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` env vars set per environment.

**Outstanding decisions that must resolve before E:**
- §5.2 pricing model.
- §5.3 refund/expiration policy.
- §5.14 tax provider selection (if multi-state or international customers).
- §5.16 subscription pricing tiers, trial, dunning, proration (if launching subscriptions).

**Must establish in E:**
- Webhook handler idempotent on `stripe_event_id`.
- Frontend unlocks via server-side entitlement only (ADR-019).
- Daily reconciliation job against Stripe API.

**Risk if assumptions break:**
- `entitlement` schema doesn't match pricing model → schema rework with active customers.
- Webhook handler not idempotent → double-grants on Stripe replay.

## Phase F (Twilio) — assumptions

**Inherits from B:**
- `lead`, `opt_out`, `sms_thread`, `sms_message` tables exist.
- 10DLC registration approved (ADR-025) — must be initiated by Phase B.

**Outstanding decisions that must resolve before F:**
- §5.8 auto-reply policy.
- §5.11 phone lookup + reassignment provider concrete contract.
- §5.12 compliance policy authoring path + initial ruleset (attorney input required).

**Must establish in F:**
- Single Twilio adapter (ADR-024).
- Inbound webhook signature verification.
- Notification template registry (mirrors prompt versioning).
- Sandbox numbers in staging; production credentials only after 10DLC approved.

## Phase G (imports v2) — assumptions

**Inherits from B & C:**
- `import_batch`, `import_row` tables exist.
- `imports` queue with rate limit lower than `signals` (so 10k-row CSV doesn't starve interactive scans).

**Outstanding decisions that must resolve before G:**
- §5.9 object storage choice.
- §5.13 GDPR-erase / anonymization semantics (attorney input required; can elevate to earlier phase if customer-facing erasure request arrives).

**Must establish in G:**
- Authenticated `POST /v1/imports`.
- Per-account batch state machine.
- File hash dedupe (re-upload is idempotent).
- Retire `infra/scripts/batch_score.py` once API replaces it.

## Phase H (AI workflows + verification) — assumptions

**Inherits from B, C, D:**
- `vertical_prompt_version`, `ai_probe`, `verification_result`, `external_cache` tables.
- Real signals from D (LLM probes augment, not substitute, real data).
- `analysis_run.cost_usd_cents`, `cost_cap_usd_cents` operative from B's first migration.

**Outstanding decisions that must resolve before H:**
- §5.6 LLM provider/model defaults.
- §5.7 cost cap dollar amount.

**Must establish in H:**
- Prompt registry resolves `(vertical_id, probe_name) → vertical_prompt_version` with `status='active'`.
- All probes write `ai_probe` rows.
- Verification pipeline runs for paid analyses.

## Always-on assumptions (every phase)

- ADR-027 (additive-only migrations between deploys).
- ADR-026 (tag-driven prod, branch-driven staging).
- ADR-028 (feature flags wrap user-visible new behavior).
- ADR-029 (backups, PITR, tested restore — quarterly drill).
- ADR-031 (no raw queries; repositories only).
- ADR-032 (no command-style operation lacks an idempotency key).
- ADR-034 (Blocking ADRs gate implementation).

If you find yourself violating any of these "always" assumptions, stop and open an ADR — don't ship around them.
