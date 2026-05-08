# ADR-024 — Twilio behind a single adapter

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Communication · Security/compliance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
All outbound SMS go through `clients/twilio.send`, invoked only by `domain/notifications`. The inbound webhook handler (`/v1/webhooks/twilio`) verifies HMAC and enqueues `notify.sms.inbound` — no business logic in the request handler. Templates live in DB (versioned, like prompts). Phone numbers are PII (ADR-013).

## Why
SMS is the highest-compliance-risk surface. Centralizing outbound and inbound paths means there is exactly one place to enforce opt-out checks (ADR-014), one place to log messages, one place to handle delivery callbacks. Spread that logic across the codebase and compliance becomes structurally impossible to maintain.

## Tradeoffs
- Notifications can't trivially be sent "ad-hoc" from random code paths — by design.
- The constraint is the value.

## Future limitations
- Voice and MMS slot under the same adapter pattern.
- WhatsApp via Twilio adds a channel, not a new architecture.

## Migration cost if revisited
Centralizing scattered SMS calls is a security-critical refactor with compliance consequences. Doing it now is free.

## Scaling implications
Worker queue absorbs bursts. Twilio throughput limits well above our needs.

## Operational complexity
Medium. Per-environment credentials, sandbox numbers in staging (ADR-026), STOP/HELP handling tested.

## Constraints this ADR imposes
- One module: `backend/app/clients/twilio.py`.
- One inbound router: `backend/app/api/v1/webhooks/twilio.py`.
- Outbound messages go through `domain/notifications/send_sms` (opt_out checked).
- Templates in `notification_template` table, versioned like prompts.
- Auto-reply on inbound: outstanding §5.8, gate Phase F. Default: STOP/HELP only.

## See also
- ARCHITECTURE-LOCK §3.7
- ADR-014 (opt_out)
- ADR-025 (10DLC)
- ADR-013 (PII)
