# Phase 0 — Governance Reconciliation

**Status:** Governance reconciliation pass — 2026-05-14. Preparation only; no implementation, no artifact edits, no commit.
**Scope:** Five findings designated **Phase 0 Critical Governance Locks** — F-H1, F-H3, F-H4, F-H5, F-M2.
**Authority inputs:** `Phase_0_Execution_Blueprint.md`, `ontology_releases/v1.1.0.yaml`, `engine_releases/v0.1.0.yaml`, `Phase_0_Freeze_Boundary.md` (current state: C1–C7 reconciled; C8/D2–D6 edits still pending).
**Purpose:** Lock the authoritative ruling for each finding, record rationale and consequences, and surface remaining unresolved items.

---

## Reading note

Three provisional rulings supplied for this pass (provisional F-H4, F-H5, F-M2) conflicted with already-authoritative artifacts and with canonical rulings issued during the Freeze Boundary reconciliation. Those conflicts were reported rather than silently applied, and superseding authoritative rulings were issued (2026-05-14). This document records the **authoritative** rulings, not the provisional ones.

---

## F-H1 — Ontology terminology authority

**Finding ID:** F-H1
**Conflict summary:** Terminology drift between artifacts for indicator computation modes and roles. The Freeze Boundary (pre-reconciliation) used `fully_auto` / `analyst_review`; the ontology YAML uses `config_lookup` / `automated` / `analyst_set` and `role: prior` / `likelihood_signal`. No artifact was explicitly named the semantic authority.
**Operational risk:** Implementation code, enums, loaders, and validators keyed to the wrong vocabulary would silently mismatch the release artifacts; divergent strings compound into untraceable drift.
**Replayability impact:** `computation_mode` / `role` strings are persisted into observation and event payloads. If the canonical vocabulary is not pinned, replay across artifact versions can mismatch. Pinning the ontology YAML as canonical — changeable only via explicit version bump — keeps persisted values stable and replay-safe.
**Authoritative ruling:** The ontology YAML (`ontology_releases/v1.1.0.yaml`) is the canonical source of indicator terminology — `computation_mode` values (`config_lookup`, `automated`, `analyst_set`) and `role` values (`prior`, `likelihood_signal`). This vocabulary is canonical unless explicitly changed via an ontology version bump.
**Rationale:** The ontology YAML already declares `governance.source_of_truth: "This YAML is the authoritative Phase 0 ontology release."` A single, version-gated semantic source of truth is the only drift-proof arrangement.
**Affected artifacts:**
- `ontology_releases/v1.1.0.yaml` — authority. No change.
- `Phase_0_Freeze_Boundary.md` — already aligned to ontology terms by the C3 reconciliation. Consistent.
- `Phase_0_Execution_Blueprint.md` §14 — uses prose ("automated", "analyst-set", "lookup/config-driven") that is semantically consistent but not identical strings. No change required; noted for awareness.
**Implementation consequence:** All code, enum definitions, loaders, and validators key off the ontology YAML vocabulary. The strings `fully_auto` and `analyst_review` do not appear in implementation.
**Version bump required:** No, to adopt this ruling. Going forward: yes — any change to the canonical terminology requires an ontology version bump.

---

## F-H3 — Override / invalidation ordering and referential integrity

**Finding ID:** F-H3
**Conflict summary:** The override flow's intra-transaction ordering and referential integrity were not explicitly specified. Risk: an indicator observation could be marked invalidated without — or before — the override row that justifies it exists.
**Operational risk:** Dangling reference in `indicator_observations.invalidated_by_override_id`; partially-applied overrides; ambiguous intra-transaction state.
**Replayability impact:** Event order must be deterministic. The `override.applied` event must be sequenced before the `observation.invalidated` state change within the same transaction so replay reconstructs an identical provenance DAG every time. A mandatory FK guarantees invalidation state can never exist without its provenance root.
**Authoritative ruling:** Within a single transaction: (1) the `override.applied` event and `analyst_overrides` row are created first; (2) the `indicator_observations.invalidated_by_override_id` mutation (NULL → uuid, one-way) happens second; (3) a mandatory foreign key `indicator_observations.invalidated_by_override_id` → `analyst_overrides(id)` enforces referential integrity.
**Rationale:** Provenance DAG integrity (Blueprint §11): derived/invalidation state must always reference an existing override. The one-way `NULL → uuid once` mutation already declared for this column is consistent with the FK + ordering rule.
**Affected artifacts:**
- `Phase_0_Freeze_Boundary.md` — §A `analyst_overrides`, `indicator_observations.invalidated_by_override_id`, CLI `override apply`, API `POST /overrides`, "Override flow" extension test. Consistent; no change.
- `Phase_0_Execution_Blueprint.md` — §9 (tables), §11 (provenance DAG). Consistent.
- Note: the `override.applied` event type is not in Blueprint §8's *minimum Day-1/Week-1* list. §8 is explicitly non-exhaustive and overrides are Day-6 scope (§21), so this is an expected addition, not a conflict.
**Implementation consequence:** The override handler wraps both writes in one transaction with explicit ordering. The schema adds the FK constraint. The `override.applied` event type is added to the event taxonomy when override work begins (Day 6).
**Version bump required:** No. This is an elaboration consistent with existing artifacts, not a semantic change.

---

## F-H4 — VERTICAL_BASE_PRIOR observation and confidence coverage

**Finding ID:** F-H4
**Conflict summary:** The provisional F-H4 ruling stated `VERTICAL_BASE_PRIOR` "is excluded from LR coverage denominator due to role=prior." This conflicted with the C8 outcome and with Blueprint §15 + `engine_releases/v0.1.0.yaml`, all of which count all three required indicators in the confidence denominator.
**Operational risk:** Implemented with a denominator of 2, every confidence score would be systematically inflated, and confidence-gated tier routing would misroute entities. The artifacts were split: Blueprint §15 and the engine YAML say 3; the Freeze Boundary (pre-reconciliation) implied 2 via "LR indicators."
**Replayability impact:** Confidence is part of scoring output and is persisted in `scoring_runs`. A denominator change alters every confidence value; the denominator must be pinned to one authority or persisted scoring runs are not reproducible.
**Authoritative ruling:** The confidence / coverage denominator = **3** = the count of **all required Phase 0 indicators** (`VERTICAL_BASE_PRIOR`, `ACQ_PAGE_PRESENT`, `MULTI_BRAND_DECLARED`). `VERTICAL_BASE_PRIOR` **does** produce an observation row (retained from provisional F-H4 — required for provenance and replayability), contributes **no** log-LR weight (`role: prior`), but **does** count toward confidence completeness. There is no separate "LR coverage denominator"; the provisional F-H4 phrasing is corrected. C8 (the finding) is resolved by deferring to Blueprint §15 + engine YAML authority.
**Rationale:** Confidence measures *completeness of required Phase 0 indicator observation*, not *log-LR-contributor coverage*. A prior observation that exists but carries no LR weight still represents a completed required-indicator observation. Authority: Blueprint §15 (`total_required_phase0_indicators = 3`, all three listed as required) + `engine_releases/v0.1.0.yaml` (`confidence.total_required_phase0_indicators: 3`, all three in `required_indicators`).
**Affected artifacts:**
- `Phase_0_Execution_Blueprint.md` §15 — authority. No change (already specifies 3).
- `engine_releases/v0.1.0.yaml` `confidence` block — authority. No change (already specifies 3).
- `Phase_0_Freeze_Boundary.md` §A Scoring — **currently still reads "observed LR indicators ÷ total LR indicators"** (the C8 reconciliation edit never landed). Must be reconciled to denominator-3 wording. See Remaining Unresolved Items.
**Implementation consequence:** `confidence = observed_required_indicators / 3`. `VERTICAL_BASE_PRIOR` emits an `indicator.observed` row with no LR weight; it still increments the observed-required count. Tier gating consumes this confidence value.
**Version bump required:** No. Blueprint §15 and the engine YAML already specify 3; adopting the ruling requires no change to them. Only the Freeze Boundary needs an alignment-only (non-semantic) reconciliation edit.

---

## F-H5 — Append-only enforcement scope for projection tables

**Finding ID:** F-H5
**Conflict summary:** The provisional F-H5 ruling stated `entities` and `analysts` "become append-only projection tables enforced via triggers." This conflicted with ruling D2 (append-only = `events` only), Blueprint §7, and Blueprint §19.5, and introduced a replayability hazard.
**Operational risk:** Trigger-enforced immutability on projection tables blocks normal projection maintenance and over-constrains the schema before the substrate is proven — scope creep against anti-cathedral discipline (Blueprint §25).
**Replayability impact:** Blueprint §6/§9 require projection state to be rebuildable from the event log, and replay rebuilds projections. DELETE-blocking triggers on the `entities` projection table would prevent a replay from clearing and rebuilding it — a direct replayability contradiction. Keeping `entities` / `analysts` mutable preserves replay.
**Authoritative ruling:** **D2 stands.** Phase 0 append-only enforcement applies **only to `events`**. `entities` and `analysts` are **mutable projection tables**. There are **no trigger-enforced append-only projection tables in Phase 0**. F-H5 is **deferred beyond Phase 0**.
**Rationale:** The append-only event log is the substrate guarantee (Blueprint §7, §19.5). Projection tables are derived and must remain rebuildable (§6, §9); trigger-enforced immutability fights replay. Anti-cathedral discipline: do not add enforcement the substrate proof does not require.
**Affected artifacts:**
- `Phase_0_Execution_Blueprint.md` §7, §19.5 — authority (`events` only). No change.
- `Phase_0_Freeze_Boundary.md` §A Append-only enforcement — **currently still lists 10 tables + 3 one-way-mutation columns** as enforcement (the D2 reconciliation edit never landed). Must be reconciled to "`events` only." See Remaining Unresolved Items.
**Implementation consequence:** Day-1 trigger work targets `events` only. `entities` and `analysts` receive no append-only triggers. F-H5 moves to the post-Phase-0 deferred catalog.
**Version bump required:** No.

---

## F-M2 — Coverage denominator definition

**Finding ID:** F-M2
**Conflict summary:** The provisional F-M2 ruling set "coverage denominator equals count of likelihood_ratio indicators only" (= 2). This conflicted with the C8 outcome and Blueprint §15 + engine YAML (= 3). F-M2 and F-H4 are two expressions of the same coverage-denominator question.
**Operational risk:** Identical to F-H4 — a denominator of 2 produces systematically inflated confidence and misrouted tiers.
**Replayability impact:** Identical to F-H4 — the denominator must be pinned to one authority or persisted `scoring_runs` confidence values are not reproducible.
**Authoritative ruling:** **OVERTURNED.** The coverage denominator equals the count of **all required Phase 0 indicators** (3), **not** likelihood_ratio indicators only. F-M2 is superseded by Blueprint §15 + `engine_releases/v0.1.0.yaml`. Same authority and outcome as F-H4.
**Rationale:** Identical to F-H4 — confidence measures required-indicator observation completeness, not LR-contributor coverage. The two LR indicators contribute log-LR *weight*; all three required indicators contribute to *coverage completeness*.
**Affected artifacts:** Same as F-H4 — Blueprint §15 (authority), `engine_releases/v0.1.0.yaml` `confidence` block (authority), `Phase_0_Freeze_Boundary.md` §A Scoring (pending C8 reconciliation edit).
**Implementation consequence:** `confidence = observed_required_indicators / 3`. The implementation must not define an "LR-only" coverage denominator.
**Version bump required:** No.

---

## Version-bump analysis

| Finding | Semantic change to a release artifact? | Version bump |
|---|---|---|
| F-H1 | No — ontology YAML already authoritative | None now |
| F-H3 | No — elaboration consistent with Blueprint §9/§11 | None |
| F-H4 | No — Blueprint §15 + engine YAML already specify denominator 3 | None |
| F-H5 | No — Blueprint §7/§19.5 already specify `events`-only | None |
| F-M2 | No — same as F-H4 | None |

No engine or ontology version bump is required to adopt any of the five Critical Governance Locks. All five resolve **toward** the existing Blueprint + release-YAML authority; none change a release artifact's semantics. The only edits implied are **alignment-only reconciliation edits to `Phase_0_Freeze_Boundary.md`** (the still-pending C8 + D2 edits), which are non-semantic.

Conditional triggers for a future bump:
- Any change to the canonical indicator vocabulary (F-H1) → ontology version bump.
- Any change to the confidence denominator definition (F-H4 / F-M2) → engine version bump (per the engine YAML's own `governance.modification_rule`) + Blueprint §15 edit.
- Any future authorization of append-only enforcement on projection tables (F-H5) → a dedicated governance release.

---

## Remaining unresolved items

1. **`Phase_0_Freeze_Boundary.md` is not fully reconciled.** The C8, D2, D3, D5, and D6 edits were issued but never landed (rejected / interrupted). With F-H4/F-M2 and F-H5/D2 now authoritatively settled, two of those pending edits are required for cross-artifact consistency:
   - §A Scoring still reads "observed LR indicators ÷ total LR indicators" — contradicts the F-H4/F-M2 ruling (denominator = 3).
   - §A Append-only enforcement still lists 10 tables + 3 one-way columns — contradicts the F-H5/D2 ruling (`events` only).
   - D3 (canonical release paths), D5 (remove nonexistent references), D6 (§1 → §5 citation) are also still pending.
2. **D4 — entity naming unresolved.** The D4 ruling specifies "AI Garage" as canonical, but every materialized artifact uses "A1 Garage" / `A1_GARAGE` (Blueprint §3/§17; `engine_releases/v0.1.0.yaml` `A1_GARAGE` + validation notes), and the ontology YAML contains no entity reference at all. The ruling's stated rationale ("already used consistently in Blueprint, ontology YAML, engine YAML") does not match the materialized state. Needs an explicit decision: confirm "A1 Garage" is canonical, or authorize corrections to the Blueprint + engine YAML to adopt "AI Garage."
3. **C2 standing item.** Blueprint §§4/5 do not list FastAPI or an API module; the Freeze Boundary's FastAPI + read-mostly API surface was ruled canonical, with Blueprint §§4/5 flagged for a later "minimal reconciliation." Not yet done.
4. **Bare "TSA-FRAG" reference.** `Phase_0_Freeze_Boundary.md` §C "Deferred to Phase 2+" still contains "the full TSA-FRAG scoring engine." The D5 ruling removed "TSA-FRAG v1.1" specifically; this bare reference was not covered. Needs a ruling (remove, or keep as a conceptual reference).
5. **Blueprint §26 artifact set still incomplete.** Not yet materialized: `03_PREQUAL_ENGINE/Phase_0_Governance_and_Replayability.md` (a distinct artifact from *this* `Phase_0_Governance_Reconciliation.md`), `CURRENT_STATE_BRIEF.md` (repo root), `MASTER_INDEX.md` (repo root).
6. **Drift-risk catalog DR-01 … DR-15** was referenced as an output of the continuity-archivist pass, but its contents have not been provided to this checkout. If it is to be materialized, the content is needed.
