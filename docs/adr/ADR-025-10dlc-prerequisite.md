# ADR-025 — 10DLC registration as a launch prerequisite

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Communication · Security/compliance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
No production SMS sending until 10DLC brand and campaign registration are approved. Block this on the calendar; treat it as a precondition for the Twilio go-live milestone.

## Why
Unregistered A2P traffic in the US is heavily filtered, then blocked, then carries fines and the loss of sender registration. The registration process takes 1–4 weeks and cannot be rushed. Pretending it is optional is the most expensive shortcut available.

## Tradeoffs
- Launch dates are gated on third-party approval.
- Mitigated by starting the process the day SMS enters scope.

## Future limitations
- International expansion adds analogous regimes (UK STIR/SHAKEN, country-by-country sender ID rules).

## Migration cost if revisited
This decision *is* the timeline. Underestimating it is the migration cost.

## Scaling implications
Approved campaigns have throughput tiers. Higher trust scores unlock higher TPS.

## Operational complexity
Medium up front, low after. One person owns the registration paperwork; renewals annual.

## Constraints this ADR imposes
- 10DLC registration must be initiated no later than Phase B (so it overlaps with Phase F build time).
- Production Twilio credentials are not provisioned until registration approved.
- Staging uses sandbox/test numbers regardless.

## See also
- ARCHITECTURE-LOCK §3.7, §11
- ADR-024 (Twilio adapter)
