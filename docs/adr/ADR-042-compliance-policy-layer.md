# ADR-042 — Compliance Policy Layer (placeholder)

| Field | Value |
|---|---|
| Status | **Locked (placeholder)** |
| Class | Communication systems · Security/compliance · Canonical entities |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none |
| Superseded by | none |

## Decision
A placeholder Compliance Policy Layer carves out architectural space for attorney-managed federal/state/channel-specific rules. The system enforces rules through configuration; no legal rule lives in code.

Two new tables:

```sql
compliance_policy (
  id              uuid PK,
  scope_kind      text NOT NULL CHECK (scope_kind IN
                    ('federal','state','channel','vertical',
                     'account','category','combination')),
  scope_value     jsonb NOT NULL,            -- e.g. {state:'TX', channel:'sms'}
  rule_kind       text NOT NULL,             -- e.g. 'send_window' | 'consent_freshness'
                                              --      | 'reassignment_max_age' | 'frequency_cap'
                                              --      | 'required_disclosure_language'
  rule_value      jsonb NOT NULL,            -- shape per rule_kind; grammar deferred to §5.12
  version         int NOT NULL,
  effective_from  timestamptz NOT NULL,
  effective_to    timestamptz NULL,
  status          text NOT NULL CHECK (status IN ('draft','active','retired')),
  source          text NOT NULL CHECK (source IN
                    ('attorney_provided','system_default','manual_override')),
  source_metadata jsonb,                      -- attorney name, citation, approval ref
  created_at, updated_at
)
UNIQUE (scope_kind, scope_value, rule_kind, version)
INDEX (rule_kind, status) WHERE status = 'active'

compliance_policy_evaluation (
  id                  uuid PK,
  account_id          uuid NOT NULL,
  lead_id             uuid NULL,
  channel             text NOT NULL,
  message_category    text NULL,
  send_request_id     uuid NOT NULL,
  policies_evaluated  jsonb NOT NULL,         -- [{policy_id, version, rule_kind}, ...]
  rules_passed        jsonb NOT NULL,
  rules_failed        jsonb NOT NULL,
  decision            text NOT NULL CHECK (decision IN ('allow','deny','soft_warn')),
  reason              text NULL,
  evaluated_at        timestamptz NOT NULL
)
INDEX (account_id, evaluated_at DESC)
INDEX (lead_id, evaluated_at DESC) WHERE lead_id IS NOT NULL
INDEX (decision) WHERE decision = 'deny'
```

The send gate has **eight** checks; compliance policy is check #8. Fail-closed on missing, expired, or ambiguous policy.

## Why
TCPA and state law evolve. Embedding rules in code creates a compliance maintenance burden incompatible with how legal advice is delivered (per-jurisdiction, time-bounded, attorney-cited). A data-driven layer lets attorneys provide rules that the system enforces uniformly.

This is a **placeholder**: rule grammar (the JSONB shape of `rule_value` per `rule_kind`) and concrete federal/state rulesets are deferred to attorney input (outstanding decision §5.12). The architecture space is locked now so future rules drop into a known shape; without the placeholder, rules will be ad-hoc and embed in code.

## Tradeoffs
- Placeholder shape may need tightening when attorney-supplied grammar is concrete.
- Rule grammar (`rule_value jsonb`) is open-ended in v1; tightening later may require migration.
- Evaluator complexity grows with `rule_kind` count.

## Future limitations
- Cross-jurisdiction rules (lead in TX, sender in CA) require explicit scope combinations.
- Rule ambiguity (two policies disagree) requires deterministic resolution; not modeled in v1 placeholder — to be defined with attorney input.
- Quiet hours, retry caps, frequency caps, disclosure language: all deferred to §5.12.

## Migration cost if revisited
Low to tighten the placeholder once attorney input arrives. **High-risk** if removing the layer entirely (compliance regression).

## Scaling implications
Indexed lookups per send; bounded by active policy count. `compliance_policy_evaluation` grows linearly with sends; partition-friendly by `evaluated_at`.

## Operational complexity
High once active. Attorney-supplied rules must be auditable end-to-end. Discipline: no legal rule lives in Python; no `if state == "X"` permitted.

## Constraints this ADR imposes
- All federal/state/channel/vertical/account compliance rules live in `compliance_policy` rows.
- Send gate check #8 (after 10DLC) evaluates the active policy set; refusal codes recorded in `compliance_policy_evaluation`.
- Policy authoring is attorney-mediated via migration in v1; admin UI is a Phase G+ surface.
- Each send writes one `compliance_policy_evaluation` row regardless of decision.
- Fail-closed when policy missing for a required scope.
- Specific rule grammar (`rule_value` shape per `rule_kind`) deferred to §5.12 with attorney input.
- No `if state == "X"` or `if jurisdiction == "Y"` permitted in Python; all enforcement through the evaluator.
- Phase F SMS go-live cannot proceed without §5.12 finalized + an active ruleset.

## What this ADR explicitly forbids
- Hard-coding any state-specific or federal rule into Python.
- Computing rule outcomes outside the policy evaluator.
- Bypassing the evaluator in any "internal" or "test" send path.
- Releasing Phase F SMS without ADR-042 grammar finalized.

## What this ADR makes possible
- Attorney provides updated state law → migration inserts new `compliance_policy` rows with `effective_from` set to the law's effective date → no code change.
- A specific dispute → `compliance_policy_evaluation` row reproduces "on this date, these policy versions were active, these rules passed, these rules failed."
- A new vertical adds bespoke compliance rules (industry-specific disclosure language) → vertical-scoped policy rows; system-wide rules untouched.
- A jurisdiction expansion → new state-scoped policies; existing policies for other states untouched.

## See also
- ARCHITECTURE-LOCK §3.7 (eight-check send gate)
- ADR-014 (opt_out is check #1)
- ADR-024 (Twilio adapter)
- ADR-025 (10DLC is check #7)
- ADR-038 (warm-outbound is check #4)
- ADR-039 (blocklist is check #2)
- ADR-041 (phone intelligence is checks #5 + #6)
- §5.12 outstanding decision (rule grammar + initial ruleset)
