# ADR-026 — Tag-driven prod, branch-driven staging

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Environment separation · Operations |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
`main` auto-deploys to staging on every merge. Production deploys only on a git tag (`v0.NN.M`), created from a green staging build. Rollback is tag-redeploy of the previous tag.

## Why
Branch-to-prod ("merge and pray") couples code review to deploys, which couples velocity to risk. Tags introduce a deliberate "is staging actually green?" pause and produce an immutable artifact list for any production state. Cheapest possible release engineering that survives a real incident.

## Tradeoffs
- One extra step to ship to prod (cut a tag). This is the point — friction proportional to risk.

## Future limitations
- Per-service deploy cadences (api hourly, worker daily) want per-service tags. Easy extension when needed.

## Migration cost if revisited
Going from branch-deploy to tag-deploy after the first prod incident is one of the universal moves teams make. Better to start there.

## Scaling implications
None.

## Operational complexity
Low. One CI workflow per environment; tag creation is `git tag && git push --tags`.

## Constraints this ADR imposes
- `.github/workflows/deploy-staging.yml` triggers on push to `main`.
- `.github/workflows/deploy-production.yml` triggers on `v*` tag push.
- Production rollback = re-tag previous good version (Railway retains images).
- Staging may break; production must be promoted from a known-green staging build.

## See also
- ARCHITECTURE-LOCK §11
- ADR-027 (additive migrations make rollback safe)
- ADR-029 (backups for irreversible state)
