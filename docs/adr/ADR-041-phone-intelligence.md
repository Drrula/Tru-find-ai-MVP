# ADR-041 — Phone intelligence: line-type classification + ownership/reassignment

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Communication systems · Security/compliance · Canonical entities |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
Phone intelligence is a system-data layer, not a tenant-data concern. Three new tables:

- `phone_record` (global) — normalized E.164 + line-type classification + ownership/reassignment fields. Single row per unique number; shared across accounts.
- `phone_observation` (account-scoped) — per-account first-seen / lead-link record.
- `phone_reassignment_check` (append-only) — audit log of reassignment lookups for TCPA safe-harbor.

Normalization is at ingest (libphonenumber). Classification is **lazy by default** (classify-on-send); eager admin batch available with budget cap. Lookups are cached and metered (`lookup_cost_cents`); per-account daily spend cap of $5/day soft (queue overflow for next day).

Default lookup provider: **Twilio Lookup v2**. Reassignment screening: Twilio Lookup reassignment field + FCC RND aggregator as the authoritative TCPA safe-harbor record.

## Why
Scraped/imported numbers are unsafe assumptions. Sending SMS to a landline violates TCPA and burns sender reputation. Sending to a reassigned number — even with valid prior consent — also violates TCPA. Phone intelligence is the architectural primitive that gates compliance; "unknown ≠ allowed."

Treating classification as system data (not tenant data) lets multiple accounts share the cost benefit while keeping observation/attribution tenant-scoped.

## Tradeoffs
- Per-number lookup cost (~$0.005); offset by global cache.
- First-send latency for previously-unclassified numbers.
- Vendor relationship with Twilio.

## Future limitations
- Carrier-specific SMS capabilities (e.g., short-code support) not modeled in v1.
- International numbers handled per E.164 but specific country regulatory rules deferred.
- Per-account custom eligibility rules not supported (would conflict with system-data framing).

## Migration cost if revisited
Low to swap providers (`clients/phone_lookup.py` adapter). High if removing the intelligence layer entirely (compliance regression).

## Scaling implications
Cache hit rate dominates cost; high cache hit rate at scale because numbers are shared across accounts. Per-account daily cap bounds worst case.

## Operational complexity
Medium. Per-environment Twilio + RND aggregator credentials. `phone_record` continuity covered by ADR-029 backups.

## Constraints this ADR imposes

### Normalization
- E.164 canonicalization at ingest via libphonenumber.
- `e164_hash` (sha256) is the lookup key; `e164_encrypted` per ADR-013.

### Line-type classification
- `phone_line_type` ∈ {`mobile`, `landline`, `voip`, `toll_free`, `unknown`}.
- `sms_eligible`: mobile=true, voip=carrier-conditional, landline=false (unless explicit), toll_free=false, unknown=false.
- `voice_eligible`: all classified types true, unknown=false.
- SMS confidence threshold: `lookup_confidence >= 0.7` globally; per-vertical override allowed.
- Re-classification TTL: 90 days confident, 24 hours unknown, 365 days toll_free.

### Ownership / reassignment
- Fields: `owner_confidence`, `owner_last_verified_at`, `reassignment_risk` ∈ {`low`,`medium`,`high`,`confirmed_reassigned`,`unknown`}, `first_seen_at`, `last_seen_at`.
- Owner verification triggers: inbound SMS reply, voice answered, manual confirmation. **Not** outbound link clicks.
- Reassignment-risk send refusal:
  - `high` or `confirmed_reassigned` → refuse.
  - `unknown` → refuse if consent age > 90 days; allow if ≤ 90 days.
  - `low` / `medium` → allow.
- `phone_reassignment_check` records every check (provider, result, raw_response, cost) for safe-harbor evidence.

### Send gate integration
- Phone classification is check #5 (line-type) and check #6 (ownership/reassignment) in the 8-check send gate.
- Voice send gate uses the same eight-check structure with `voice_eligible` swap.
- Default deny on missing classification, low confidence, or high reassignment risk.

### Cost containment
- `phone_record.lookup_cost_cents` cumulative per number.
- Per-account daily lookup spend cap: $5 soft; queue overflow for next day rather than refuse.
- CSV imports do **not** auto-classify by default (lazy); eager pre-classify is admin action with budget cap.

## See also
- ARCHITECTURE-LOCK §3.7 (eight-check send gate)
- ADR-013 (PII)
- ADR-014 (opt_out is check #1)
- ADR-024 (Twilio adapter — only place that talks to Twilio)
- ADR-025 (10DLC is check #7)
- ADR-042 (compliance policy may further constrain by jurisdiction at check #8)
- §5.11 outstanding decision (provider concrete contract, gate Phase F)
