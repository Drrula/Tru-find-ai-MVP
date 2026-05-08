# ADR-028 — Feature flags wrap user-visible new behavior

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Operations |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
New user-visible behavior is gated by a flag (env-var initially, DB-backed `feature_flag` table once we need per-account targeting). Flags default off in production; rollout is "ship dark, flip on, watch."

## Why
Decouples deploy risk from rollout risk. A bug in a new path becomes "flip the flag" instead of "redeploy the whole API." Second-cheapest piece of operational insurance after backups.

## Tradeoffs
- Code carries `if flag_enabled(...)` branches that must be cleaned up after rollout.
- Flags accumulate if not pruned. Mitigated by treating each flag as a ticket with an explicit "remove by" date.

## Future limitations
- Sophisticated targeting (percentages, account cohorts, A/B) wants a real flag service eventually (PostHog, Flagsmith). Env-var flags are the 80% solution.

## Migration cost if revisited
Adding flags to a stable behavior-set is fine. The cost is *not* having them when an incident makes you wish you did.

## Scaling implications
None until per-account targeting, which is a small DB lookup.

## Operational complexity
Low. Discipline: delete the flag with the cleanup PR.

## Constraints this ADR imposes
- `core/flags.py` exposes `feature_enabled(key, account_id=None)`.
- Phase A: env-var flags only.
- Phase D+: `feature_flag` table.
- Each new flag has a corresponding ticket with a removal date.

## See also
- ADR-026 (tag promotion)
- ADR-027 (additive migrations)
