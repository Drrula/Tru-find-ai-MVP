# Architecture Decision Records

This directory holds the architectural contract for Tru-find-ai. The lock document (`ARCHITECTURE-LOCK.md`) is the master reference; each ADR file expands one decision with full rationale.

## Reading order

1. `ARCHITECTURE-LOCK.md` — start here. The ADR index, schema, lifecycles, service boundaries, and Phase A plan in one place.
2. Individual `ADR-NNN-*.md` files — full rationale per decision, linked from the lock document index.

## ADR statuses

- **Locked.** Full-strength. Changing requires a superseding ADR.
- **Locked-default.** Accepted by default. Same change rule, lower historical blast radius.
- **Open.** Decision deferred; gated on a specific phase or feature.

## Blocking ADRs (per ADR-034)

Any ADR materially affecting **tenancy, canonical entities, AI mutation behavior, security/compliance, billing/entitlements, environment separation, communication systems, or irreversible schema decisions** is a Blocking ADR.

Modifying or superseding a Blocking ADR requires explicit review before implementation proceeds. New ADRs in those domains are likewise blocking.

The Blocking ADR set is enumerated in `ARCHITECTURE-LOCK.md` Part 1.

## Change protocol

To modify a Locked ADR:

1. Open a new ADR with the next available number.
2. In the new ADR, set `Supersedes:` to the prior ADR ID.
3. In the prior ADR, set `Superseded by:` to the new ADR ID. Do not edit any other fields of the prior ADR.
4. Update `ARCHITECTURE-LOCK.md` Part 1 to reflect the new ID and status.
5. If the change is to a Blocking ADR: pause implementation in any affected area, get explicit review approval, then proceed.
6. Add a migration plan (DB, code, contracts, rollout) to the new ADR if the change affects deployed state.

## File naming

`ADR-NNN-short-slug.md` where `NNN` is zero-padded to three digits. The slug describes the decision, not the implementation.

## What is *not* an ADR

- Implementation details (which library, which file structure inside a module).
- Reversible style preferences.
- Day-to-day refactors.

These belong in `CONTRIBUTING.md` or in code review.
