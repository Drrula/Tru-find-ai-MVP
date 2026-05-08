# Contributing

This file translates the architecture lock (`docs/adr/ARCHITECTURE-LOCK.md`) into day-to-day rules. If a rule here conflicts with an ADR, the ADR wins.

## Before you write code

- Read `docs/adr/ARCHITECTURE-LOCK.md` Part 1. If your change touches a **Blocking ADR** domain (tenancy, canonical entities, AI mutation, security/compliance, billing/entitlements, environment separation, communication systems, irreversible schema), open a superseding ADR first. Implementation in that area pauses until the new ADR is reviewed (ADR-034).
- Open changes only against tasks defined in `docs/phase-a-plan.md` (or the active phase plan). New scope requires its own task.

## Code rules

### Backend
- **No business logic in API routers.** Routers parse, call a domain service, serialize.
- **No raw DB queries in domain code.** All DB access via repositories (ADR-031). Repositories enforce `account_id` and soft-delete.
- **No external HTTP in domain code.** Use `clients/*` wrappers behind `Cached(...)` (ADR-012).
- **No business logic in webhooks.** Webhooks verify signatures and enqueue.
- **No PII in plaintext columns.** Use the `(hash, encrypted)` pattern (ADR-013).
- **No prompts as code constants.** Versioned in DB (ADR-020).
- **Idempotency keys are explicit.** Any mutating job/external call carries one (ADR-032).
- **UUIDv7 primary keys** generated via `core.ids` (ADR-033).

### Frontend
- **No `fetch()` in components.** Use `lib/api.js`.
- **No client-side paywall logic.** Server-side entitlement only (ADR-019).
- **No env values in source.** Read from `import.meta.env.VITE_*`.

### Migrations (Phase B+)
- **Additive between deploys** (ADR-027). Drops and renames split into expand → migrate → contract.
- **One ALTER per migration.** Easier to review, easier to revert.
- **No backfills in migrations.** Backfills are jobs.

### Testing
- New domain code requires at least one test that exercises the public surface.
- Migrations are tested by `alembic upgrade head` + smoke read.
- Frontend changes that touch `apiFetch` or auth flow require a smoke test.

## Commit and PR rules

- **One commit per PR** (squash-merge), titled with conventional-commits style.
- **Each commit is revertible** without breaking `main` (ADR-026/027).
- **No `--amend` to published commits.** Forward fixes only.
- **No `--no-verify` skip of hooks.** Fix the hook failure.

## Secrets

- Never commit a real secret. `.env.example` only.
- Secrets live in Railway environment variables (or the secrets manager when introduced).
- If a secret is committed accidentally: rotate first, then remove from history.

## Branching and deploys

- `main` auto-deploys to staging.
- Production deploys only on tag (`vN.M.P`) created from a green staging build.
- No direct push to `main`. PRs only.

## Working with Claude Code

- Read-only exploration and additive file creation may proceed without per-step confirmation.
- **Modifications to tracked files** (especially `.gitignore`, `README.md`, anything in `app/` or `frontend/`) require an explicit diff or risk assessment before applying.
- ADR changes require the protocol in `docs/adr/README.md`.

## ADR change protocol

See `docs/adr/README.md`. Summary:
1. Open a new ADR that supersedes the old one.
2. Update `ARCHITECTURE-LOCK.md` Part 1 index.
3. Blocking ADR? → review gate before any code lands.
