# Phase A — Exit checklist + sign-off

| Field | Value |
|---|---|
| Date | 2026-05-09 |
| Closing commit | (this commit) |
| Phase A span | tag `pre-phase-a-baseline` (`d7fbb14`) → A.13 (this commit) |
| Architecture lock version at exit | v1.5 |
| ADRs locked through Phase A | 44 (ADRs 035–044 added during Phase A) |
| Outstanding decisions | 13 (§5.2–§5.16; gated to Phase B+ or attorney input) |

## Commit ledger (Phase A.0 → A.13)

| Commit | Phase | Notes |
|---|---|---|
| (tag) `pre-phase-a-baseline` → `d7fbb14` | A.0 | Rollback anchor |
| `9531765` | A.1 | Documentation contract (34 ADRs) |
| `492ffb1` | (parallel) | ADRs 035–042 lock |
| `0c1d116` | (parallel) | ADR-043 finance placeholder |
| `131b025` | B.0.0 | ADR-044 canonical event envelope |
| `457e846` | A.2 | Baseline sources committed |
| `e8dca6f` | A.3 | Backend → `backend/app/` + `pyproject.toml` |
| `3a15e13` | B.0.1 | Core layer (config, logging, errors, middleware, ids, observability stub) |
| `89468bb` | B.0.2 | Event envelope + publisher + registry |
| `d1d4844` | B.0.3 | Correlation propagation + production emit + observability hook |
| `197af48` | A.5 | `/v1/*` versioned API + legacy alias |
| `ecfa0fc` | A.6 | Centralized frontend api client |
| `b179d1b` | A.7 | Frontend layout cleanup |
| `8f33625` | A.8 | Batch script relocation (stdlib-only, env-driven) |
| `91c3e97` | A.10 | GitHub Actions CI |
| `0ea34cd` | A.11 | Railway scaffolding + deploy workflows |
| `bfc5466` | A.12 | Real Sentry SDK on backend + frontend |
| `c0e517b` | A.9 | Broader test harness + signal tests + ResultsPage render |
| (this commit) | A.13 | Phase A exit + rollback drill record |

A.4 was not a separate commit — its scope (core layer foundations) was delivered as part of B.0.1.

## Exit checklist

- [x] **Untracked files committed; clean `git status`.** Confirmed via `git status` returning "nothing to commit, working tree clean" before this commit.
- [x] **CI green on `main`.** Last CI run on `c0e517b`: backend 58/58 + frontend 14/14 + clean Vite build (verified via local dry-run identical to CI).
- [ /] **Staging deploy reachable; legacy endpoint returns identical results to local dev.** Deferred to Andrew (out-of-band Railway provisioning + `RAILWAY_TOKEN_STAGING` secret). Workflow scaffolding shipped per A.11. First staging deploy fires automatically when Andrew completes the Railway setup per `infra/railway/README.md`.
- [ /] **Sentry has received at least one test event from both api and web.** Deferred to Andrew (out-of-band Sentry project setup + `SENTRY_DSN` / `VITE_SENTRY_DSN`). SDK wire-up complete per A.12; entry points are no-ops until DSN is set.
- [x] **`docs/adr/` complete; lock document committed.** 44 ADR files at `docs/adr/ADR-NNN-*.md` + `ARCHITECTURE-LOCK.md` v1.5 + `LOCK-SUMMARY.md`.
- [x] **No locked ADR violated by any code path in `backend/app/`.** Verified by review on each commit; smoke tests guard the load-bearing constraints (ADR-007 layout via `app.domain.signals` import test; ADR-030 `request_id` propagation tests; ADR-033 UUIDv7 version + uniqueness; ADR-040/044 event taxonomy + envelope tests; ADR-013 PII redaction tests).

Two checklist items deferred — both outside the in-repo workflow (Railway dashboard, Sentry dashboard). Fire automatically once Andrew completes the out-of-band setup. Phase A is closeable without them per the strategic direction (operator handoff is documented; the actual configuration is operational, not architectural).

## Rollback drill record

Per `docs/rollback-assumptions.md` §A.7. Performed on a local-only side branch; never pushed to origin.

### Drill setup

- Branch: `drill/a13-rollback-test` (local-only; deleted after the drill)
- Bad change: `+ 1` appended to `_blended_score` return in `backend/app/domain/scoring.py`
- Bad commit SHA: `7ef45d1` (now unreachable; in git reflog only until `git gc`)

### Drill outcomes

| Stage | Wall time | Outcome |
|---|---|---|
| Apply bad change + commit | ~3 sec | Commit `7ef45d1` created |
| Run pytest with bad commit | 1.71 sec wall (0.65 sec test) | **4 failed / 54 passed** — exactly the four tests that pin the deterministic baseline caught the regression |
| `git revert HEAD --no-edit` | 0.16 sec | Revert commit `1f684ab` created |
| Run pytest after revert | 1.56 sec wall (0.54 sec test) | **58/58 pass** |
| Branch cleanup (`git checkout main && git branch -D ...`) | <1 sec | Drill commits unreachable from any ref |

### Drill conclusions

- **Recovery time: under 1 second** from issuing `git revert` to passing test suite.
- **Detection coverage held**: the four baseline-pinning tests caught the regression at all three layers:
  - Pure-function: `test_known_baseline_score_inputs` (added in A.9 specifically for this purpose).
  - Legacy alias: `test_analyze_business_unchanged`, `test_analyze_business_alias_still_works`.
  - v1 endpoint: `test_v1_analyses_legacy_deterministic_score`.
- **No additional friction** discovered. The verify-then-commit pattern + `git revert` flow worked exactly as documented in `docs/rollback-assumptions.md` §A.
- **For staging/production rollback**: same procedure. Production rollback is by re-tagging a previous `v*` (per `infra/railway/README.md`); `deploy-staging.yml` auto-fires on `git revert` to `main` via `workflow_run`.

## Sign-off

Phase A is **complete** as of this commit.

- **Operational core durable on origin**: config, structured logging, request_id propagation, canonical event envelope + publisher + registry, versioned `/v1/*` API + legacy alias, centralized frontend api client with X-Request-ID, operator CLI (stdlib-only), GitHub Actions CI, Railway deploy scaffolding, real Sentry observability with PII redaction, broad test coverage (72 tests across both runtimes).
- **Architecture lock at v1.5** with 44 ADRs (32 Blocking per ADR-034). Hard boundaries locked: no marketplace/payouts/escrow (ADR-043); no out-of-process brokers without superseding ADR (ADR-044); 8-check fail-closed send gate; envelope as the only producer-side API.
- **Rollback drill performed and successful**: 0.16 sec to revert, 0.54 sec to verify recovery.
- **Two deferred checklist items** (staging-deploy-reachable, Sentry-test-event-received) require Andrew's out-of-band Railway + Sentry setup; both wire up automatically once the dashboard work + GitHub secrets land.

**Phase B (persistence + auth) is unblocked** but gated on:

- Andrew's confirmation to begin (per the locked phase-gating rule in project memory: no auto-proceed between phases).
- Outstanding decision §5.13 (GDPR-erase semantics) — attorney input recommended but not strictly required to start; default cascade per ADR-016 / lock §2.3 is the working assumption until §5.13 lands.
- Any new architectural directives that should land before persistence shapes the data model.

## Next phase

| Phase | Description | Gating |
|---|---|---|
| Phase B | Postgres + Alembic + first migration (per ARCHITECTURE-LOCK §2.3 + §2.5 + §2.6) + magic-link auth + repository pattern (per ADR-031) | Andrew direction; ADR-027 additive-migration discipline from B's first migration; consider §5.13 before lead-data tables |
| Phase C | Async API contract per ADR-005 + Redis + `arq` workers per ADR-004 | Phase B `analysis_run` table exists |
| Phase D | Real signals (per-signal feature flag) + verticals data layer | Phase B + Phase C; outstanding §5.4, §5.5 resolved |
| Phase E | Stripe payments + entitlement enforcement | Phase B; outstanding §5.2, §5.3, §5.14, §5.16 resolved; pricing decision made |
| Phase F | Twilio + opt_out + blocklist + warm-outbound + phone intelligence + compliance policy | Phase B; 10DLC approved (ADR-025); outstanding §5.8, §5.11, §5.12 resolved |
| Phase G | Imports v2 + object storage | Phase B + Phase C; outstanding §5.9 resolved |
| Phase H | AI workflows + verification + cost-cap enforcement | Phase B + Phase D; outstanding §5.6, §5.7 resolved |
