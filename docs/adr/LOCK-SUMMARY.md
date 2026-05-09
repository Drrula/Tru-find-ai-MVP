# ADR Lock Summary — In-flight ADRs 035–042

| Field | Value |
|---|---|
| Date | 2026-05-08 |
| Source | Architecture-lock questionnaire (30 questions) |
| Outcome | 28 approved · 1 override · 1 deferred · ADR-042 placeholder added |
| Companion docs | `ARCHITECTURE-LOCK.md` · `ADR-035`–`ADR-042` (to be created on `commit`) |

This file is the durable record of decisions reached in the questionnaire. It is the source of truth for what the eventual ADR-035 through ADR-042 files will contain.

---

## Approved (28 of 30 questions)

| Q | Topic | Locked decision |
|---|---|---|
| Q1 | Lead intelligence dimensions | 7 dimensions, never collapsed: `lead_quality | engagement | ai_confidence | qualification | conversion_probability | communication_readiness | buying_window_intensity` |
| Q2 | Per-dimension confidence column | `lead_dimension.confidence numeric(4,3) NULL` per row, distinct from the standalone `ai_confidence` dimension |
| Q3 | Recomputation triggers | Hybrid: real-time on `engagement`/`intent`/`communication`/`lifecycle` events; scheduled (10-min cadence) for `ai`-derived dimensions; on-demand admin recompute |
| Q4 | `ai_probe` table | Shared. `target_type text NOT NULL CHECK (target_type IN ('analysis_run','lead'))`; one of `analysis_run_id` / `lead_id` populated |
| Q5 | Multi-touch attribution retention | All touches retained, append-only; no cap; indexed `(lead_id, touched_at DESC)` |
| Q6 | Lifecycle states (8) | `cold | warm | engaged | qualified | opportunity | customer | dormant | unsubscribed` |
| Q7 | Cross-account lead ownership | One `lead` row per account; signal histories isolated; `phone_record` is the only globally-shared artifact |
| Q9 | Definition versioning model | New row per version (matches ADR-020 prompt versioning); old `lead_event` rows pin to `event_definition_id` |
| Q10 | Event category seed (7) | `engagement | intent | enrichment | ai | attribution | communication | lifecycle` |
| Q11 | Event source seed (9) | `web | sms | email | crm | enrichment_provider | ai_probe | manual | system | import` |
| Q12 | Payload schema enforcement | Insert-time strict; per-definition `lenient` flag for known-noisy sources |
| Q13 | Retired definitions | Emit refused for retired `event_type`; reads (historical events) still resolve via pinned `event_definition_id` |
| Q14 | Cross-account event definitions | Global. Tenancy lives on observations and signals, not on the taxonomy |
| Q15 | Orchestration namespace reservation | Reserve `lead_event_category='orchestration'` and `lead_event_source='sara_orchestration'` as `status='draft'` |
| Q17 | Warm-outbound qualifying categories | `engagement | intent | communication` only. System-derived categories (`ai`, `enrichment`, `attribution`, `lifecycle`) do not qualify |
| Q18 | Blocklist scope | Per-channel × per-target. `channel IN ('sms','email','any')`, `target_kind IN ('contact_identifier','business','lead')`. Account-scoped |
| Q19 | Blocklist + opt-out precedence | Both checked. Send refused if either matches. Both fail-closed |
| Q20 | Phone lookup provider default | Twilio Lookup v2 (line-type + carrier in one call) |
| Q21 | Eligibility derivation rules | `sms_eligible`: mobile=true, voip=carrier-conditional, landline=false (unless explicit), toll_free=false, unknown=false. `voice_eligible`: all classified types true, unknown=false |
| Q22 | SMS confidence threshold | `lookup_confidence >= 0.7` globally; per-vertical override allowed |
| Q23 | Re-classification TTL | 90 days for confident; 24 hours for `unknown`; 365 days for `toll_free` |
| Q24 | Pre-classify on import | Lazy by default. Eager only via explicit "pre-classify batch" admin action with budget cap |
| Q25 | Voice send-gate structure | Same eight-check structure as SMS; `voice_eligible` replaces `sms_eligible` in check #5 |
| Q26 | Per-account daily lookup spend cap | $5/day soft cap. On exhaustion, queue lookups for next day rather than refuse |
| Q27 | Reassignment check provider | Twilio Lookup v2 reassignment field for screening; FCC RND (Reassigned Numbers Database) via aggregator as authoritative TCPA safe-harbor record. Both checked in critical paths |
| Q28 | Reassignment-risk refusal threshold | Refuse: `high` or `confirmed_reassigned`. Conditional refuse: `unknown` if consent age > 90 days. Allow: `low`/`medium` |
| Q29 | Owner verification triggers | Inbound SMS reply, voice answered, manual confirmation. **Not** outbound link clicks |
| Q30 | Usage-based billing annotation | §5.2 annotated to explicitly enumerate `usage_based` as a candidate option family alongside `one_time` and `subscription`. Decision deferred to Phase E |

---

## Overrides (1 of 30)

| Q | Topic | Override locked |
|---|---|---|
| Q16 | Warm-outbound trigger freshness windows | **engagement: 14d** (was default 30d) · **intent: 3d** (was default 7d) · **communication: 24h** (unchanged). Per-vertical override allowed via `vertical_lead_event_weight` sibling configuration |

---

## Deferred (1 of 30)

| Q | Topic | Reason | Gate |
|---|---|---|---|
| Q8 | GDPR-erase / anonymization semantics | Attorney review required before locking. Phase B's first migration accommodates either path (cascade vs anonymize-in-place); concrete behavior locked before Phase G | Recorded as outstanding decision **§5.13**. Phase G — or earlier if a customer-facing erasure request arrives |

---

## New architectural locks

### Pre-locked principles (Section 0 of questionnaire — locked verbatim into ADR text)

1. Seven independent lead dimensions, never collapsed into one score.
2. Definition-driven event taxonomy; no hardcoded event enums in business logic.
3. Warm outbound requires a positive trigger event, not absence of opt-out.
4. Unknown phone type fails closed for SMS — "unknown ≠ allowed."
5. Phone lookups cached and cost-controlled (`phone_record` is the cache; `lookup_cost_cents` metered).
6. CSV imports do not auto-classify phones by default.
7. Blocklist distinct from `opt_out`; both checked, both fail-closed.
8. Same contact across accounts → separate `lead` rows; `phone_record` global, `lead` account-scoped.
9. Public-data signals are global; downstream lead state is account-scoped.
10. AI classifications explainable, versioned, reversible.
11. All important state transitions auditable.

### ADR-042 — Compliance Policy Layer (placeholder, Blocking)

- **Send gate becomes eight checks** (compliance policy is #8).
- `compliance_policy` table: data-driven, versioned, scoped by `(scope_kind, scope_value, rule_kind)` with `effective_from` / `effective_to`.
- `compliance_policy_evaluation` table: append-only audit log; pins policy versions per send decision; records `policies_evaluated`, `rules_passed`, `rules_failed`, `decision`, `reason`.
- **Fail-closed** on missing, expired, or ambiguous policy.
- Attorney-mediated authoring via migration; no rules embedded in code; rule grammar (`rule_value jsonb` shape) deferred to §5.12.
- No legal rule may live in any Python module; all rules live as `compliance_policy` rows.

### Updated send gate (8 fail-closed checks)

1. opt-out (ADR-014)
2. blocklist (ADR-039)
3. communication readiness (ADR-036; derived live)
4. positive trigger / warm event (ADR-038)
5. phone classification — line-type (ADR-041)
6. ownership / reassignment risk (ADR-041)
7. 10DLC / campaign readiness (ADR-025)
8. compliance policy rules (ADR-042)

Each denial records a reason code into `audit_log`; check #8 also writes `compliance_policy_evaluation`.

### In-flight ADR queue (8 new entries; ARCHITECTURE-LOCK Part 1 expands 34 → 42)

| Order | ID | Title | Class |
|---|---|---|---|
| 1 | 035 | Lead intelligence framing | Blocking |
| 2 | 036 | Signals / dimensions / explainability | Blocking |
| 3 | 040 | Event taxonomy (definition-driven) | Blocking |
| 4 | 037 | Lifecycle states + event-driven evolution | Blocking |
| 5 | 038 | Warm-outbound positive-trigger | Blocking |
| 6 | 039 | Blocklist (account-scoped suppression) | Blocking |
| 7 | 041 | Phone intelligence: line-type + ownership / reassignment | Blocking |
| 8 | 042 | Compliance Policy Layer (placeholder) | Blocking |

### New outstanding decisions (Part 5 additions)

| ID | Topic | Gate | Notes |
|---|---|---|---|
| §5.11 | Phone lookup + reassignment provider concrete contract | Phase F | Twilio Lookup v2 + FCC RND aggregator confirmed at default; specific aggregator selection is the open piece |
| §5.12 | Compliance policy authoring path + initial ruleset (attorney input required) | Phase F | Rule grammar shape, federal baseline, state-specific seed rules |
| §5.13 | GDPR-erase / anonymization semantics (attorney input required) | Phase G or earlier on demand | Cascade vs anonymize-in-place |

---

## Schema additions implied by these locks (table list only — full DDL in eventual ADRs)

New tables (Phase B's first migration):

`lead_signal_definition` · `vertical_lead_signal_weight` · `lead_signal` · `lead_dimension` · `lead_event_category` · `lead_event_source` · `lead_event_definition` · `vertical_lead_event_weight` · `lead_event` · `lead_enrichment` · `lead_source_attribution` · `blocklist` · `phone_record` · `phone_observation` · `phone_reassignment_check` · `compliance_policy` · `compliance_policy_evaluation`

New columns on existing tables:
- `lead`: `lifecycle_state`, `vertical_id`, `first_seen_at`, `last_engaged_at`, `contact_phone_record_id`
- `ai_probe` (per ADR-020): `target_type`, `lead_id` (nullable, alongside `analysis_run_id`)

---

## What this summary does and does not do

- **Does** record durable decisions from the architecture-lock questionnaire.
- **Does** define what ADR-035 through ADR-042 files will contain when written.
- **Does not** create the ADR files themselves (pending `commit` direction).
- **Does not** change schema, code, or migrations.
- **Does not** override existing ADR-001 through ADR-034 (all v1.2 locks remain in force).

When the next commit is authorized, the full eight ADR files plus `ARCHITECTURE-LOCK.md` index/schema/outstanding-decisions updates will land in a single docs-only PR, with diff verification before the actual git commit.
