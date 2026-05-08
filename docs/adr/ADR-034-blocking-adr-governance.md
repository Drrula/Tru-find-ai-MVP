# ADR-034 — Blocking-ADR governance category

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Governance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No (defines the rule) |
| Supersedes | none |
| Superseded by | none |

## Decision
ADRs that materially affect any of the following domains are designated **Blocking ADRs**:

- Tenancy
- Canonical entities
- AI mutation behavior
- Security / compliance
- Billing / entitlements
- Environment separation
- Communication systems
- Irreversible schema decisions

Modifying or superseding any Blocking ADR — or introducing a new ADR that materially affects any of these domains — requires explicit review before implementation proceeds. Implementation in the affected area pauses until the review is complete.

## Why
These domains carry the largest blast radius if changed mid-flight. Forcing explicit review prevents drift from architectural intent and catches second-order consequences (data migrations, customer-visible breakage, compliance regressions) before code lands.

## Tradeoffs
- Slows down change in those areas.
- May discourage useful refactors. Mitigated by a clear superseding-ADR procedure (`docs/adr/README.md`).

## Future limitations
- New domains may need to be added to the blocking list later (e.g. data residency, cross-region replication, multi-currency billing).

## Migration cost if revisited
Low — this is a process rule, not code. Adding/removing categories or changing the review threshold is an ADR amendment.

## Scaling implications
None direct; protects scaling decisions from ad-hoc reversal.

## Operational complexity
Low — one extra review step on certain ADRs. Reviewer (Andrew) decides explicitly.

## Constraints this ADR imposes
- Each ADR in the lock document carries a "Blocking ADR (per ADR-034)" field set explicitly Yes/No.
- ADRs in this set as of v1.2: 002, 005, 008, 009, 010, 011, 013, 014, 015, 018, 019, 020, 021, 022, 023, 024, 025, 026, 027, 031, 032, 033 — 22 ADRs total.
- Any new ADR in the eight domains above auto-inherits Blocking status.
- Modifications to a Blocking ADR cannot proceed to implementation until reviewed.

## See also
- ARCHITECTURE-LOCK Part 1 (full status table)
- `docs/adr/README.md` (change protocol)
