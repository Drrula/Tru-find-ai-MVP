# ADR-011 — Verticals are data, not code

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
A `vertical` table; per-vertical signal weights, prompts, gap copy, and competitor filters live in vertical-keyed tables (`vertical_signal_weight`, `vertical_prompt_version`, `vertical_copy`, `vertical_template`). Adding a trade is a data change, not a deploy.

## Why
"Roofers vs HVAC vs landscapers" is the product's core extension axis. If `if vertical == "roofers"` shows up in a domain module once, it shows up everywhere. Driving from data lets non-engineers (or future ops tooling) onboard a vertical without releasing code.

## Tradeoffs
- Slightly more indirection in code (a weights lookup, a copy lookup) per signal evaluation.
- Tests cover the resolution order.
- Risk of over-parameterizing — putting things in DB that should be code.

## Future limitations
- Truly novel verticals may need a different signal *set*, not just different weights. `vertical_template` anticipates this.

## Migration cost if revisited
Hard later, easy now. Once two verticals are hard-coded, removing the branching is a refactor across the codebase.

## Scaling implications
None — tables are small (<100 rows) and cached in process.

## Operational complexity
Higher: changing a weight is a DB write, requires audit trail and rollback. Solved by treating these tables like code: PRs that produce SQL migrations, not direct DB edits.

## Constraints this ADR imposes
- No `if vertical == "X"` branches in domain code.
- Weight resolution: `vertical_signal_weight` → `signal_definition.default_weight` fallback (semantics in outstanding decision §5.5).
- Prompt/copy resolution by `(vertical_id, key, status='active')`.
- Vertical taxonomy management surface (DB-editable vs migration-only): outstanding §5.4, gate Phase D.

## See also
- ARCHITECTURE-LOCK §2.3
- ADR-020 (versioned prompts)
- ARCHITECTURE-LOCK §5 outstanding decisions
