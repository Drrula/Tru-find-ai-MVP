# Rollback Assumptions

Explicit list of what must be true for rollback to work at each layer. If any assumption breaks, rollback becomes more expensive than expected — that's the warning sign.

## A. Per-commit rollback (within Phase A)

**Mechanism.** `git revert <sha>` produces an inverse commit. Each Phase A commit is independently revertible.

**Assumptions:**
1. Each commit produces a green CI on its own (enforced by per-PR CI runs).
2. No commit depends on a not-yet-committed sibling (enforced by sequential merge order in `docs/phase-a-plan.md`).
3. Reverting a commit does not require running a database migration backwards (Phase A introduces no migrations — assumption automatically true).
4. The pre-Phase-A tag (`pre-phase-a-baseline`) exists and points to a known-working state. **Already established.**
5. Working tree files that are *untracked* (e.g. `.venv/`, `.claude/settings.local.json` after gitignore landed) are not affected by `git reset` and remain available.

**Failure modes:**
- A commit silently depends on a previous one being present → revert fails or leaves broken state. Mitigation: run CI on the revert PR; never merge a revert without it.
- A revert reintroduces a removed file with stale content. Mitigation: prefer forward-fix when the original commit removed something; only revert if the removal itself was the bug.

## B. Phase-level rollback (Phase A as a unit)

**Mechanism.** Revert commits in reverse order via PRs, or `git reset --hard pre-phase-a-baseline` as the absolute fallback.

**Assumptions:**
1. The `pre-phase-a-baseline` tag is preserved on the remote (`git push --tags origin pre-phase-a-baseline`). **Pending push.**
2. No Phase A commit modifies git history of pre-existing commits (no rebase, no force-push, no amend).
3. Untracked files added by external tooling (e.g. `.venv/` recreated by Python, `node_modules/` recreated by `npm install`) are recoverable by re-running tooling, not by git.
4. Railway deploys do not auto-revert if you `git revert` on `main` — they auto-deploy the revert as a new build (per ADR-026). The revert is the rollback.

**Failure modes:**
- Force-push happened. Mitigation: branch protection rule on `main` from Phase A.10.
- Tag was deleted. Mitigation: tags are append-only conventionally; if deleted accidentally, recreate from reflog.

## C. Staging rollback

**Mechanism.** Staging auto-deploys from `main`. Revert at git level → staging redeploys the prior state automatically.

**Assumptions:**
1. Railway staging deploy webhook is connected to GitHub `main`.
2. The previous Railway staging build artifact is retained for at least 7 days (Railway default).
3. Staging environment variables match the reverted code's expectations (i.e. we don't introduce env vars without backward-compatible defaults).

**Failure modes:**
- Env-var schema changed without a default. Mitigation: pydantic-settings `Field(default=...)` for any new var until known to be required everywhere.
- Build artifact pruned before rollback need. Mitigation: tag any production-bound build to extend retention.

## D. Production rollback

**Mechanism.** Production is tag-driven (ADR-026). To roll back: re-tag the previous known-good `vN.M.P` and push the tag. Railway redeploys the prior image.

**Assumptions:**
1. Each prior production tag corresponds to a build artifact still retained on Railway.
2. The previous image's environment variables are still valid (e.g. third-party credentials haven't been rotated to a value the old image doesn't know about).
3. The previous image's database schema is still valid — i.e. no destructive migrations have been deployed in between (ADR-027).
4. Production tag history is preserved (tags are append-only).

**Failure modes:**
- A migration was destructive (a column the old code reads no longer exists). **This is the primary risk after Phase B.** Mitigation: ADR-027 (additive only between deploys; drops only one deploy after code stops referencing).
- A third-party credential rotation between deploys. Mitigation: dual-credential rolling rotation (old and new valid simultaneously during the rotation window).
- Image pruned. Mitigation: Railway retention; for critical builds, push to a long-retention registry as backup.

## E. Data rollback

**Phase A.** No DB exists. Data rollback is not applicable. **Important to verify this is still true at Phase A exit** — if any task accidentally introduces persistence, this assumption breaks.

**Phase B+.** Backed by ADR-029 (PITR + tested restore).

**Assumptions (Phase B+):**
1. Postgres provisioned with PITR enabled from creation (Phase B task gate).
2. Backups verified by quarterly restore drill.
3. RTO target: <4 hours. RPO target: <5 minutes (PITR granularity).

**Failure modes:**
- PITR not enabled. Mitigation: Phase B's first task is to verify PITR before any write traffic.
- Backup never tested. Mitigation: drill is a calendar event with a documented owner.
- Schema migration rolled forward but data shape doesn't match restored backup. Mitigation: keep the prior schema deploy available alongside the prior image; restore + previous-image is a coordinated pair.

## F. Railway provisioning rollback

**Mechanism.** Tear down a Railway service and re-create from `infra/railway/*.template`.

**Assumptions:**
1. All env vars are documented in `*.env.template`.
2. No state lives only in Railway (no Railway volumes used in Phase A; if introduced later, separate backup story needed).
3. Service IDs / DNS hostnames may change on tear-down. Mitigation: custom domain attached, not Railway-generated URL.

**Failure modes:**
- Custom domain DNS TTL too long during failover. Mitigation: 5-minute TTL on staging hostnames.

## G. Documentation rollback (this commit)

**Mechanism.** `git revert` of the A.1 commit removes all docs and the `.gitignore` append.

**Assumptions:**
1. No code yet depends on the docs (true).
2. The `.gitignore` append is purely additive (verified via diff during apply).
3. No local Claude state in `.claude/settings.local.json` is critical to retain (it would become tracked again after revert — but is gitignored as of A.1, so not a concern post-A.1).

## Required rollback drill (Phase A exit)

Before declaring Phase A complete:

1. On a feature branch, deliberately introduce a bad commit (e.g. break A.12 Sentry config).
2. Revert via the §A procedure.
3. Verify staging recovers.
4. Document elapsed time and any friction in `docs/phase-a-exit.md`.

The first real production rollback should never be the first time you've done one.
