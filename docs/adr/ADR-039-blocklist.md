# ADR-039 — Blocklist as account-scoped suppression

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Communication systems · Security/compliance |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
A `blocklist` table for account-scoped, channel-aware, target-aware suppression — distinct from `opt_out` (recipient-initiated, ADR-014). Both are checked on every send; both fail-closed.

```sql
blocklist (
  id                uuid PK,
  account_id        uuid NOT NULL REFERENCES account(id),
  channel           text NOT NULL CHECK (channel IN ('sms','email','any')),
  target_kind       text NOT NULL CHECK (target_kind IN
                      ('contact_identifier','business','lead')),
  identifier_hash   bytea NOT NULL,                -- sha256 canonicalized
  reason            text NOT NULL,
  source            text NOT NULL,                 -- 'admin' | 'import' | 'rule' | ...
  expires_at        timestamptz NULL,
  recorded_at       timestamptz NOT NULL,
  created_at, updated_at, deleted_at
)
UNIQUE (account_id, channel, target_kind, identifier_hash)
   WHERE deleted_at IS NULL
INDEX (account_id, channel) WHERE deleted_at IS NULL
```

## Why
- `opt_out` records recipient-initiated suppression (e.g., STOP).
- `blocklist` records account-initiated suppression (known-bad leads, regulatory exclusions, business preferences, internal filters).

Conflating them loses the source distinction and makes audit and compliance harder.

## Tradeoffs
- Two tables to query before each send.
- Slight schema verbosity.

## Future limitations
- System-wide blocklists (across all accounts) not supported in v1; would add a NULL `account_id` row.
- Time-bounded blocks supported via `expires_at` but no automatic re-evaluation cycle.

## Migration cost if revisited
Low. Renaming or merging tables is doable. The check is a single function.

## Scaling implications
One indexed lookup per send; same pattern as `opt_out`. Negligible.

## Operational complexity
Low. The discipline: every send path checks both `opt_out` and `blocklist`. Inserts/deletes audit-logged.

## Constraints this ADR imposes
- Send gate runs check #1 (`opt_out`) AND check #2 (`blocklist`); both must pass.
- `identifier_hash` follows the same hashing pattern as `opt_out` (sha256 of canonicalized phone or email).
- Per-channel rows allow blocking SMS while permitting email (and vice versa).
- `target_kind='business'` allows blocking competitor inclusion in scoring without affecting communications.
- Blocklist mutations write `audit_log` entries.

## See also
- ARCHITECTURE-LOCK §3.7
- ADR-014 (opt_out is the recipient-initiated counterpart)
- ADR-013 (PII hashing pattern)
- ADR-015 (audit_log for mutation history)
