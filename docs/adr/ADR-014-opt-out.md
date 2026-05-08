# ADR-014 — `opt_out` global, channel-keyed

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Security/compliance · Communication |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
A single `opt_out(channel, identifier_hash, source, recorded_at, account_id NULL)` table. *Every* outbound notification path (SMS, email) checks this table before sending. STOP/UNSUBSCRIBE webhooks write to this table.

## Why
Twilio compliance (and email deliverability) is binary: a single send to a non-opted-in or opted-out recipient can revoke sender registration or burn IP reputation. Centralizing the check means there is one function to audit and one place to fix bugs.

## Tradeoffs
- Slight latency on every send (one indexed lookup).
- Discipline: no code path bypasses the check, even "internal" or "test" sends.

## Future limitations
- Per-account opt-outs (recipient opted out of account X but not Y) require the nullable `account_id` to be populated. Designed in from the start.

## Migration cost if revisited
Adding opt-out enforcement to an existing send pipeline is high-stakes work with compliance consequences during transition. Doing it now is one helper function.

## Scaling implications
Negligible.

## Operational complexity
Low to medium. The operational task is reconciliation — a daily job that ensures opt-outs in our DB match carrier-side state. Required for Twilio anyway.

## Constraints this ADR imposes
- `domain/notifications/send_sms` and send_email functions check `opt_out` before render.
- `(channel, identifier_hash, account_id)` unique; NULL account_id = global.
- `identifier_hash = sha256(canonicalized phone or email)` — same canonicalization as ADR-013.
- Bypass is impossible from any public function; explicit admin override goes through audited `force_send` with `audit_log` entry.

## See also
- ARCHITECTURE-LOCK §3.7
- ADR-013 (PII hashing)
- ADR-024 (Twilio adapter)
- ADR-025 (10DLC)
