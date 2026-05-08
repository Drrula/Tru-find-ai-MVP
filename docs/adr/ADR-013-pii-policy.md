# ADR-013 — PII policy: encrypt-at-rest, hash-for-lookup

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Security/compliance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Phone numbers and emails are stored as `(hashed_lookup, encrypted_value)`. Lookups happen on the hash; decryption only when displaying. Locations (street addresses, if collected) are encrypted. Business names and public attributes are not encrypted.

## Why
Compliance posture (CCPA/GDPR-equivalent) is much easier to sustain when PII is structurally separated from operational data. Hash-for-lookup means most queries don't decrypt anything. Encryption-at-rest beyond the volume layer protects against backup leaks and accidental log exposure.

## Tradeoffs
- Schema is more verbose (two columns per PII field).
- Search by partial value (e.g. "users with @gmail.com") is impossible without a separate index, by design.
- Application code handles encryption keys → key-management story (ADR-030 dependency).

## Future limitations
- Field-level encryption complicates analytics; cannot trivially query "average lead-to-purchase by email domain."
- Key rotation requires re-encrypting historical rows.

## Migration cost if revisited
Adding encryption to plaintext columns is high effort and high risk (coordinated writers and readers during transition). Doing it from the first migration is an order of magnitude cheaper.

## Scaling implications
Negligible at any realistic volume. Encryption/decryption is microseconds per row.

## Operational complexity
Higher: we own a key (env-injected, rotated quarterly) and incident-response procedures for key compromise.

## Constraints this ADR imposes
- `email_hash bytea`, `email_encrypted bytea` pattern on `user`, `lead`, `business.contact_email_*`.
- `phone_hash`, `phone_encrypted` on `lead`, `business.contact_phone_*`, `sms_thread.to_phone_*`.
- `email_hash = sha256(lower(trim(email)))`. Salt strategy documented in `core/crypto.py`.
- AES-256-GCM via `ENCRYPTION_KEY` env var.
- Logs never contain decrypted PII; structured logger redacts known PII fields.

## See also
- ARCHITECTURE-LOCK §2.3
- ADR-014 (opt_out hashes by identifier_hash)
- ADR-030 (logging redaction)
