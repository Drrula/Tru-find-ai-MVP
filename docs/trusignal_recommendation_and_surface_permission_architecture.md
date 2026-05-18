# TruSignal — Recommendation Candidate and Surface Permission Architecture

**Status: CANONICAL DOCTRINE. NOT AN IMPLEMENTATION SPECIFICATION.**

This document is the binding architectural agreement for the split between
**RecommendationCandidate** (the substrate-side truth / defensibility object)
and **SurfacePermission** (the surface-side speech authorization object).

It supersedes the prior RecommendationCandidate architecture draft and its
final compression pass. Future implementation steps must conform to this
doctrine.

**This document does not authorize any of the following:**
- Code changes, modules, packages, or implementations of any kind.
- Database DDL, migrations, indexes, constraints, or schema scaffolding.
- API endpoints, route handlers, request/response models.
- Projection table builds (no `recommendation_candidates`, no
  `surface_permissions` table is authorized by this document).
- Sara code, automation hooks, outreach surfaces, or any downstream
  consumer wiring.
- Step 12, Step 13, or any subsequent substrate work.

This document encodes the irreducible doctrine. Implementation is a
separate, separately-authorized work surface.

The 7 constitutional INV rules in §5 are irreducible. They are not
subject to negotiation, optimization, A/B testing, performance pressure,
schedule pressure, or override by any consumer requirement.

---

## §1 — Executive Philosophy

Two systems exist within TruSignal that look superficially related but
must be kept architecturally inviolate:

> **Truth** — what we believe about an entity, defensibly, with provenance.
>
> **Permission** — what we are authorized to say to the world about that entity.

These are **not** phases of one workflow. They are **not** two states
of one object. They are two different objects with two different
audiences, two different state machines, two different failure modes,
and two different update rules.

The **truth side** (`RecommendationCandidate`) is built from events upward:
evidence accrues; compliance state is asserted; candidates are proposed,
defended, disqualified, reproposed. It is an audit trail. It persists.
It is the system of record. Its primary obligation is defensibility:
"why did the system believe this?"

The **permission side** (`SurfacePermission`) is the system of speech.
It is what Sara — and any other downstream actor — reads to decide
whether to contact an entity *at this moment*. It is suppressive by
default; it is narrow in scope; it is granted explicitly and consumed
once. It does not reason about truth. It does not explain itself. It
does not retry or adapt. It exists, or it doesn't. Its primary
obligation is safety: "should this surface speak right now?"

Truth persists. Permission fluctuates.

The doctrine that follows enforces the boundary between these two
worlds. Every drift vector identified in §6 is some form of attempt
to merge them. Every collapse of that boundary makes the system more
plausible-sounding and more dangerous.

**The single most important sentence in this document:**

> Sara never reads `RecommendationCandidate`. Sara only reads
> `SurfacePermission`.

If a future engineer, agent, contractor, vendor, or AI proposes a
shortcut that violates this sentence, the proposal is rejected on
sight and the underlying motivation is investigated for drift. There
is no path of justification — performance, latency, simplicity,
convenience, "just this one feature" — that overrides this rule.

---

## §2 — Object Boundary

| Axis | RecommendationCandidate | SurfacePermission |
|---|---|---|
| Domain | Truth | Speech |
| Owner | Substrate | Surface |
| Audience | Auditor / analyst / compliance review | Actor / Sara / outreach channel |
| Timescale | Durable / accretive | Ephemeral / single-use |
| Default state | Nonexistent until proposed by evidence-driven logic | **Suppressed** |
| Update rule | New event per state transition (proposed → defended → disqualified → …) | New event per grant / consumption / revocation; rows themselves are never mutated |
| Failure mode | Wrong belief (recoverable: emit a new candidate event) | Unauthorized speech (unrecoverable: external party received a message they should not have) |
| Replay obligation | Must rebuild byte-identical from events | Must rebuild byte-identical from events |
| What it answers | "What does TruSignal believe, and why, and based on what evidence?" | "Is Sara allowed to send a specific message to a specific entity right now?" |
| What it does NOT do | Authorize speech. Decide outreach. Express opinion to the world. | Reason about truth. Explain itself. Adapt to feedback. Retry. Aggregate. |

The boundary is enforced **architecturally** — not by convention,
not by code review, not by lint rules. The two object families
live in different projections, are populated by different event
types, have different state machines, and are consumed by different
downstream readers.

**Crossing rule:** A SurfacePermission row may carry a soft pointer
to the candidate that motivated it (for audit). A RecommendationCandidate
row **never** carries a pointer to its permissions. The arrow points
only inward toward truth — never outward toward speech.

---

## §3 — Minimum Field Sets (Doctrine Level)

These are the **logical** minimum field sets at the doctrine layer.
Exact types, constraints, column ordering, indexes, and FK shape are
implementation concerns and are NOT authorized by this document.

### 3.1 RecommendationCandidate

The substrate-side truth object. One row per candidate-state-assertion;
multiple assertions over time accumulate as multiple rows. The latest
row per `candidate_id` is the current truth view; earlier rows are
historical truth (replayable).

Required logical fields:

- **`candidate_id`** — aggregate identity. Stable across state
  transitions. A "proposed" candidate that later becomes "defended"
  shares the same `candidate_id`; the lifecycle is recorded as multiple
  events, each producing its own row in the projection, all sharing
  the same `candidate_id` and differing in the candidate-state field.

  *(Alternative interpretation reserved for implementation review:
  multiple state-transition events may share `candidate_id` and live
  in the same projection with timestamp-based ordering, OR each event
  may produce a distinct row keyed by event_id and a separate
  derived-current-state projection may compute the latest. This
  document does not pick between these; it requires only that BOTH
  forms preserve the replay invariant.)*
- **`subject_entity_id`** — soft pointer to the entity this candidate
  is about. Required (a candidate without a subject entity is
  meaningless at this layer).
- **`parent_compliance_state_ids`** — soft pointers (array) to the
  upstream compliance assertions that informed this candidate.
  Order-preserved. Non-empty: a candidate must rest on at least one
  compliance assertion. (A candidate that wishes to bypass compliance
  has already broken the substrate; this field forces the chain to
  exist.)
- **`parent_derived_evidence_ids`** — soft pointers (array) to the
  upstream derived evidence that informed this candidate. Order-preserved.
  May be empty *only* if the candidate is purely a compliance-driven
  recommendation with no evidence beyond compliance state. Most
  candidates will have both.
- **`candidate_type`** — discriminator string identifying the *kind* of
  recommendation (e.g. `"primary_contact"`, `"fallback_contact"`,
  `"do_not_contact_recommendation"`, `"escalate_to_human_review"`).
  Free-form at this layer.
- **`candidate_state`** — the truth-side lifecycle state. See §4.1.
- **`candidate_version`** — opaque version string of the
  recommendation-producing logic. Required for audit and
  reproducibility. Mirrors `derivation_version` and `policy_version`.
- **`recommendation_payload`** — JSONB of the substantive
  recommendation (what is being recommended, with what parameters,
  with what defensibility annotations). PROJECTION SUBSTANCE, not
  metadata.
- **`proposed_at_for_projection`** — logical proposal time (or
  state-transition time for non-proposed events). Emitter-supplied,
  recorded verbatim.
- **`created_event_id`** — FK to `events(event_id)` of the originating
  event. Provenance link.
- **`projected_at`** — sourced from `event.occurred_at`. Never
  wall-clock.

Explicitly forbidden in the RecommendationCandidate object:
- Any pointer toward, or reference to, any SurfacePermission.
- Any "consumed by" / "authorized for" / "outreach status" field.
- Any field describing Sara's behavior or surface state.
- Any field whose meaning is "is this allowed to be spoken about?".
- Any field describing scoring, ranking, opportunity value, or
  monetary estimate.

### 3.2 SurfacePermission

The surface-side speech authorization object. One row per
permission-grant-or-state-change event; multiple events over time
accumulate as multiple rows. A consumed permission is **immutable** —
its row cannot be deleted, updated, or repointed. Revocation is a
**new event**, producing a new row.

Required logical fields:

- **`permission_id`** — aggregate identity. Each grant is its own
  aggregate. A revocation references the original `permission_id` via
  provenance, not via mutation.
- **`subject_entity_id`** — required. A permission without a subject
  entity is incoherent.
- **`candidate_id`** — soft pointer (NOT FK) to the candidate that
  motivated this permission. This is the **only** crossing from
  permission back toward truth, and it is for audit, not for runtime
  logic. Sara never follows this pointer.
- **`permission_type`** — discriminator string identifying the kind
  of speech being authorized (e.g. `"outbound_sms"`,
  `"outbound_phone_call"`, `"outbound_email"`, `"warm_introduction"`).
  Free-form at this layer; future projections may constrain.
- **`permission_state`** — the speech-side lifecycle state. See §4.2.
- **`permission_scope_payload`** — JSONB describing the narrow scope
  of the authorization (e.g. specific channel parameters, specific
  message-template binding, specific time window). PROJECTION
  SUBSTANCE. Required.
- **`granted_at_for_projection`** — logical grant time. Required for
  GRANTED-state rows.
- **`expires_at_for_projection`** — optional logical expiration time.
  Permissions without explicit expiration default to **non-renewable
  single-consumption** (see §4.2).
- **`consumed_at_for_projection`** — optional. Set ONLY in
  CONSUMED-state rows. Once set, immutable.
- **`consumption_event_id`** — optional FK to the event that consumed
  this permission. Provenance: every consumption is an event.
- **`grant_version`** — opaque version string of the permission-granting
  logic. Required for audit.
- **`created_event_id`** — FK to the originating event.
- **`projected_at`** — sourced from `event.occurred_at`.

Explicitly forbidden in the SurfacePermission object:
- Any "candidate full snapshot" or denormalized truth payload.
- Any reasoning about *why* the permission was granted beyond the
  audit-only `candidate_id` pointer and the grant_version.
- Any field describing the *content* of the message to be sent.
  (The permission authorizes a channel and scope; message content
  generation is a separate surface concern.)
- Any "retry count", "adaptive parameter", "calibration score".
- Any pointer to other permissions for cross-permission constraint
  solving.
- Any field that allows a downstream reader to *infer* truth state
  without traversing back to the candidate.

---

## §4 — Split State Machines

The two objects have distinct state machines. They share no transitions.
A candidate-state transition does NOT emit a permission event.
A permission-state transition does NOT emit a candidate event.

### 4.1 Truth-Side Lifecycle: RecommendationCandidate

```
                  ┌─────────────────────────────────┐
                  │                                 │
                  ▼                                 │
              PROPOSED ──────► DEFENDED ──────► DEFENDED  (new evidence reinforces)
                  │                │                ▲
                  │                │                │
                  │                ▼                │
                  │           DISQUALIFIED ─────────┘
                  │                                 (re-evidence → re-defended)
                  │
                  ▼
            WITHDRAWN
            (proposer explicitly retracts before defense)
```

States (logical, not exhaustive — implementation may add states that
match this discipline):

- **PROPOSED** — the recommender logic has proposed this candidate
  based on current evidence and compliance state. It has not yet
  been defended (i.e. no second-pass corroboration). It is real
  enough to record, not real enough to motivate a permission grant.
- **DEFENDED** — the candidate has been corroborated by a second
  evidence pass, an analyst, or a structural-defense step (depending
  on policy). It is now eligible to motivate a permission grant.
  **A permission grant is NOT automatic at this point.** A separate
  permission-granting event must occur.
- **DISQUALIFIED** — new evidence, new compliance state, or analyst
  judgment has ruled this candidate out. The row is recorded;
  permissions previously granted in reliance on this candidate are
  NOT automatically revoked by candidate disqualification (see INV-7).
  Revocation, if appropriate, is a separate permission-side event.
- **WITHDRAWN** — the proposing logic explicitly retracts the
  candidate before defense. Distinct from DISQUALIFIED because the
  withdrawal is internal to the recommender, not driven by
  contradicting evidence.

Every state transition is an event. Events emit new rows. No row is
ever mutated. The projection at any point is the result of replaying
all candidate events for a given `candidate_id` in `sequence_no` order.

### 4.2 Speech-Side Lifecycle: SurfacePermission

```
            (default for every entity, always)
                  SUPPRESSED
                       │
                       │  (explicit grant event; never automatic)
                       ▼
                   GRANTED ──────► CONSUMED  (terminal; immutable)
                       │
                       │  (revocation or expiration event)
                       ▼
                   REVOKED / EXPIRED  (terminal; immutable)
```

States:

- **SUPPRESSED** — the default state for every (entity, permission_type)
  pair, always, in the absence of an explicit GRANTED row. SUPPRESSED
  is **not a stored state**: it is the *absence* of a non-terminal
  GRANTED row. Sara reads "is there a non-terminal GRANTED row for
  (entity, permission_type, time-of-read)?". If no, the answer is
  SUPPRESSED. Default-deny.
- **GRANTED** — an explicit grant event has been emitted. A row exists.
  The row is non-terminal until consumed, revoked, or expired.
- **CONSUMED** — Sara (or another authorized surface) has consumed
  the permission by emitting a consumption event. The consumption
  event references the permission's `permission_id` via provenance.
  A new row is written (or the existing row is paired with a
  consumption row — implementation detail). **The consumed
  permission is immutable from this point forward.** No future event
  may un-consume it, re-grant it, or alter its consumed-at timestamp.
- **REVOKED** — a revocation event has been emitted before consumption.
  The revocation is a new event producing a new row. The original
  GRANTED row is left in place (immutable history). Sara's read,
  which is point-in-time, will see the latest state and find
  REVOKED.
- **EXPIRED** — equivalent to REVOKED but driven by `expires_at`
  rather than an explicit revocation event. Implementation may
  emit an explicit expiration event or treat expiry as a function
  over time-of-read; this document does not pick between those, but
  requires whichever path is chosen to be replay-deterministic.

**There is no transition from CONSUMED, REVOKED, or EXPIRED back to
GRANTED.** A new GRANTED row, if appropriate, is a new event for a
new `permission_id`. Permission rows are never re-used.

**There is no transition from SUPPRESSED to anything except via an
explicit grant event.** Reading a candidate, observing evidence,
asserting compliance, defending a candidate — none of these create
permissions.

---

## §5 — The Seven Constitutional INV Rules

These seven rules are the **irreducible core** of the doctrine. They
take precedence over every other consideration. They are not subject
to optimization. They have no exception clause.

> **INV-1** — Truth and permission are separate objects with separate
> state machines, separate audiences, separate update rules, and
> separate failure modes. Any code, schema, API, or doctrine that
> blurs this boundary is, by definition, drift.

> **INV-2** — Sara reads **SurfacePermission**. Sara **never** reads
> **RecommendationCandidate**. No direct candidate-to-Sara path may
> exist. No code path, no API endpoint, no projection JOIN, no caching
> layer, no batch precompute may be constructed that permits a Sara-
> resident component to obtain candidate-derived information without
> going through a SurfacePermission row.

> **INV-3** — Suppression is default. Every entity, every
> permission_type, at every time-of-read, is suppressed unless and
> until an explicit, non-terminal GRANTED row exists. There is no
> "infer permission from candidate state." There is no "allow because
> there is no recent revocation." Absence of GRANTED is suppression.

> **INV-4** — A consumed permission is immutable. Once a permission
> reaches CONSUMED state, its row is frozen in time. No event may
> revise its `consumed_at_for_projection`, `consumption_event_id`,
> `permission_state`, or any other field. The CONSUMED row is the
> permanent record that a specific surface acted on a specific
> authorization at a specific time. Replay reconstructs CONSUMED rows
> byte-identical.

> **INV-5** — Retractions are new events, never mutations. Revocation,
> expiration, withdrawal, correction, retraction — all of these are
> recorded as **new events** producing **new rows**. Original rows are
> immutable. The append-only event log discipline (events table) is
> mirrored at the doctrinal level for these projections: the truth
> and permission histories are accretive, never overwritten.

> **INV-6** — Permission gates have no bypass paths. Every speech act
> initiated by Sara (or any surface) must traverse a non-terminal
> GRANTED SurfacePermission row, by `permission_id`. There is no
> "service account override." There is no "admin force-send." There
> is no "test mode bypass" in production code paths. There is no
> "this candidate has been DEFENDED N times, so we'll allow speech."
> The gate is single, narrow, and unbypassed.

> **INV-7** — Candidate state transitions emit candidate events.
> Permission state transitions emit permission events. **The two
> event families do not cross.** A candidate going from PROPOSED to
> DEFENDED emits a candidate event. It does **not** emit a permission
> grant. A candidate going from DEFENDED to DISQUALIFIED emits a
> candidate event. It does **not** emit a permission revocation. Any
> revocation of a previously-granted permission, if appropriate, is
> a separate, explicit permission event. The boundary holds at the
> event level, not just at the projection level.

---

## §6 — Anti-Patterns and Drift Vectors

Each of these is a known direction in which the architecture wants to
collapse under operational pressure. They are listed not as
hypotheticals — they are listed because some version of each has been
proposed, sketched, or considered. They are rejected here, by name,
so future proposals collide with this document.

### 6.1 Orchestration Explosion

**The drift:** A new "orchestrator" service is introduced to sit
above the substrate, coordinate candidates with permissions, watch
for state changes across both, and emit downstream notifications.
Soon, the orchestrator owns the policy. Sara reads from the
orchestrator. The substrate becomes a backing store for the
orchestrator. Truth and permission have re-merged inside the
orchestrator's working set.

**Why it's a drift:** It violates INV-1 by reuniting truth and
permission inside a single decision context. It violates INV-2 by
giving Sara a path to candidate-derived state. It violates INV-6
by becoming a bypass path: Sara now obeys the orchestrator's
authorization rather than the SurfacePermission row.

**What to do instead:** Reject orchestrators above the substrate.
If coordination between candidate state and permission state is
required, it is encoded as **explicit downstream consumer logic**
inside well-defined per-surface code, not a substrate-resident
service. Each surface consults SurfacePermission directly. The
substrate publishes events and projections; it does not coordinate.

### 6.2 Emotional-State Modeling

**The drift:** Adding fields like `engagement_warmth`,
`responsiveness_index`, `inferred_buyer_mood`, `social_signal_score`
to either object, justified by "Sara will pick the right tone."

**Why it's a drift:** Emotional-state modeling collapses the
permission gate into a continuous personalization knob. INV-3
(suppression default) becomes meaningless: rather than "speak / don't
speak," the gate becomes "speak warmly / speak cautiously / speak
not at all," which Sara is free to interpret. Permission becomes a
parameter rather than a binary. Liability surface explodes.

**What to do instead:** Speech permissions are binary at the gate.
Tone, content, channel selection are downstream concerns of the
surface that has already been authorized. They are not encoded in
SurfacePermission.

### 6.3 Adaptive Persuasion Logic

**The drift:** Adding feedback loops where Sara's outreach outcomes
update permission-granting logic, candidate-defense logic, or
compliance-state policy — "let the system learn what works."

**Why it's a drift:** Replay-determinism dies. The system can no
longer answer "why did we believe X at time T?" because the rules
that produced X are themselves a function of outcomes between time
0 and T. Audit defensibility collapses. Worse: outreach outcomes
become inputs to truth, which means an entity that responds well
to outreach becomes more "true" than one that does not. This is a
sales-engagement system pretending to be a substrate.

**What to do instead:** Outreach outcomes are observations
(evidence_raw at most). They do NOT update the rules that produced
candidates or permissions. Rule changes are explicit version bumps
in `candidate_version` / `grant_version` / `policy_version`, emitted
as new events, replayable.

### 6.4 Permission Intelligence

**The drift:** Adding logic *inside* the permission layer to
"intelligently" decide whether a permission should still be valid:
"if the entity hasn't responded in N days, downgrade permission";
"if a related entity revokes consent, propagate"; "if the candidate
moves to DISQUALIFIED, auto-revoke any open permissions."

**Why it's a drift:** It violates INV-7 by emitting permission-side
state changes as side-effects of non-permission events. It violates
INV-3 by making permission state a function of inferred recency rather
than explicit grant. It re-couples permission to truth via the back
door.

**What to do instead:** Permissions are dumb. They are granted by
explicit events, consumed by explicit events, revoked by explicit
events. If a downstream policy requires "revoke open permissions
when candidate is disqualified," that policy emits an explicit
revocation event for each affected permission_id. The cause-effect
chain is recorded; the substrate does not silently propagate.

### 6.5 Auto-Tuning Calibration

**The drift:** A background job periodically scans candidates and
permissions, recomputes confidence thresholds, adjusts policy
versions, recalibrates "what counts as defended" — all to keep the
system "in tune" with observed reality.

**Why it's a drift:** Same as 6.3 but more insidious because it
appears purely operational. The substrate's invariants are
themselves now time-varying. Replay over historical events using
current calibration gives different results than replay using
original calibration. The substrate becomes non-deterministic with
respect to its own past.

**What to do instead:** Calibration changes are explicit policy
version bumps, recorded as events, replayable. There is no
background job that touches the substrate. If recalibration is
needed, an analyst emits the recalibration event with full
attribution.

### 6.6 Channel Arbitration Systems

**The drift:** A "channel arbiter" sits between SurfacePermission
and Sara, deciding which channel (SMS vs email vs call) is most
appropriate for a given moment, based on a model of channel
preferences, recent activity, and cost. Sara reads the arbiter's
output rather than the raw permissions.

**Why it's a drift:** The arbiter becomes a second permission gate
that is opaque, learned, and not part of the substrate. INV-6 is
violated: the gate Sara obeys is no longer the SurfacePermission
row, it's the arbiter's output. Whether speech happens is now
determined by a non-substrate component.

**What to do instead:** Each permission_type is its own
authorization. If multiple permission_types are granted for the
same entity, the surface (Sara or a Sara-adjacent component)
chooses which to consume. The choice is recorded by which
consumption event is emitted. There is no separate "arbiter"
projection or service. The choice is encoded in the surface's
consumption behavior, not in a model.

### 6.7 Cross-Permission Constraint Solvers

**The drift:** A system that examines all open permissions for a
given entity (or entity cluster) and solves a constraint problem:
"this entity has permissions for SMS and email, but not both within
24h"; "if we grant permission X, we must auto-revoke Y." Implemented
as a service that maintains a global view.

**Why it's a drift:** The solver becomes a new oracle whose state
must be replayable, deterministic, and audit-defensible — but it
isn't, because it's a constraint solver over a moving set. It
violates INV-4 by potentially auto-revoking CONSUMED permissions
in pursuit of consistency. It violates INV-5 by treating revocation
as a side-effect rather than an explicit event.

**What to do instead:** Cross-permission constraints, if real, are
encoded **upstream** at the candidate level: the candidate-state
logic should not have produced a candidate that motivates a
conflicting permission grant. If the constraint must be enforced
at permission-grant time, the grant emitter performs the check
**before emitting** and either emits or does not emit; no global
solver exists. The substrate stays simple.

---

## §7 — Intentionally Primitive

Several substrate components must remain primitive — explicit,
boring, narrow — for a long time. This section names them so future
optimization pressure collides with this document.

**Intentionally primitive, indefinitely:**

- **The permission gate.** A row exists in non-terminal GRANTED
  state, keyed by (`permission_id`, `subject_entity_id`,
  `permission_type`), or it does not. There is no scoring of the
  gate. There is no probabilistic gate. There is no "soft gate."
  The gate is one row lookup.

- **The candidate → permission relationship.** Soft pointer
  (`candidate_id` on permission) for audit only. There is no JOIN
  done at speech-time. There is no denormalization that puts
  candidate fields into the permission row. There is no caching
  layer that pre-resolves the relationship.

- **Replay dispatch.** Inline `if/elif/elif/elif` branching in test
  modules per event type. No registry. No dispatcher. No
  framework. The replay-discipline manual contract documented in
  the substrate's Step-8 hardening doctrine carries forward
  through every new event type.

- **State machine progression.** New state events are emitted by
  explicit emit functions called by explicit upstream logic. There
  is no state-machine library, no transition table, no formal FSM
  framework. The states named in §4 are achieved by emitting events
  with the appropriate `candidate_state` or `permission_state`
  field value.

- **Policy versioning.** Free-form opaque version strings
  (`candidate_version`, `grant_version`, `policy_version`,
  `derivation_version`). No semver enforcement. No version
  registry. No version compatibility matrix. The string is
  recorded; consumers interpret.

- **Consumption.** Sara emits a consumption event. The substrate
  records it. There is no "begin consume / confirm consume / commit
  consume" protocol. Single event. Once recorded, immutable.

- **Suppression.** Suppression is the absence of a GRANTED row.
  Suppression is not a state that takes resources to maintain.
  The default cost of suppressing the entire universe of (entity,
  permission_type) pairs is zero rows.

**How to spot drift pressure toward optimizing the primitives:**

If a proposal includes phrases like *"to make permissions more
intelligent…"*, *"to optimize the gate…"*, *"to reduce coupling
between…"*, *"to enable richer policy expression…"*, or *"as
volume grows we'll need…"* — the proposal is, by default, drift
toward §6's anti-patterns. The burden is on the proposer to
demonstrate, with concrete evidence and against the INV rules,
that the primitive is genuinely insufficient. Volume alone is
never the justification; the substrate is designed for replay
determinism, not for throughput optimization, and any volume
problem has a non-architectural solution first.

---

## §8 — Replay Integrity Across the Full Chain

The canonical chain, at full Step-12-or-beyond build-out:

```
                          events  (append-only, source of truth)
                            │
       ┌─────────┬──────────┼──────────┬──────────────┬──────────────────────┐
       ▼         ▼          ▼          ▼              ▼                      ▼
   entities  evidence_raw   evidence_derived  compliance_state  recommendation_candidates  surface_permissions
       │              \         /              │              /  \                          │
       │               \       /               │             /    └────────────── (soft pointer, audit only) ────────────┘
       │                \     /                │            /
       │            (parent_evidence_ids)  (parent_derived_evidence_ids)
       │                                                     │
       │                                              (parent_compliance_state_ids,
       │                                               parent_derived_evidence_ids)
       └─────── (subject_entity_id soft pointers throughout)
```

### 8.1 Replay invariants that must hold across the full chain

**Replay-invariant A (per projection).** Every projection in the
chain must be rebuildable byte-identical from the event log via its
own per-event-type replay, with the same SHA-256 snapshot before
and after a wipe-and-replay cycle. This invariant is already proven
for `entities`, `evidence_raw`, and `evidence_derived`. It must
extend, unchanged, to `compliance_state`, `recommendation_candidates`,
and `surface_permissions`.

**Replay-invariant B (cross-projection independence).** A wipe of
projection X followed by a replay of X's event type does not require
any other projection to be present. Each projection is its own self-
contained replay surface. Soft pointers across projections may
reference rows that do not currently exist; the substrate accepts
this and records faithfully.

**Replay-invariant C (combined replay).** Wiping all projections and
replaying the full event log in a single sequence_no-ordered pass
with inline-dispatch rebuilds every projection byte-identical to its
pre-wipe snapshot. This is proven combined-style at every step. The
Step-12 combined test, when authorized, becomes a five-way inline
`if/elif/elif/elif/elif` dispatch over the existing five event
types (entity.created, evidence.raw_ingested, evidence.derived_created,
compliance.state_asserted, recommendation.*). The Step-13 combined
test becomes a six-way (adding permission.* events).

**Replay-invariant D (no logic re-execution).** Replay never re-runs
the AI / extraction / policy / candidate-recommender / permission-
grant logic that originally produced the events. All such logic
lives **outside the substrate** at original emit time. Replay
recovers the recorded output verbatim. The substrate is concerned
only with byte-faithful projection reconstruction.

**Replay-invariant E (permission consumption is replayable).** A
consumption event in the event log produces a CONSUMED-state row in
`surface_permissions` at replay time, byte-identical to the original.
This is critical: the audit "did Sara consume this permission at
time T?" must be answerable after a full substrate rebuild from
events. Consumption is not a side-effect of an external system —
it is a first-class event in the substrate log.

**Replay-invariant F (cross-layer order preservation).** All
parent_* UUID[] arrays preserve element order through emission,
JSONB storage, replay reconstruction, and projection round-trip.
This is the foundation of provenance-DAG traversal: when an
auditor walks `surface_permissions.candidate_id` →
`recommendation_candidates.parent_compliance_state_ids` →
`compliance_state.parent_derived_evidence_ids` →
`evidence_derived.parent_evidence_ids` →
`evidence_raw.evidence_id`, the order of citations at each level
matters. The substrate preserves it.

### 8.2 What replay-determinism is NOT

- It is not a guarantee that the AI/policy logic *that produced*
  the events would yield the same output if re-run today. (It is a
  guarantee that the **recorded output** can be recovered byte-
  identical.)
- It is not a guarantee of permission validity at replay time.
  Replay rebuilds historical permission state; a SUPPRESSED entity
  at original event time remains SUPPRESSED at replay time. Whether
  *current* speech is authorized is a live read against the
  projection, not a replay concern.
- It is not a substitute for the cost-guard discipline on paid
  external calls. Replay never causes a paid external call; if a
  future event-emitter were ever to make a paid call in its emit
  path, that emit path itself would violate substrate doctrine.

---

## §9 — Status Reminder

This document is canonical doctrine, dated **2026-05-18**.

It supersedes any prior RecommendationCandidate architecture draft
and its compression pass. It is the binding architectural agreement
between the substrate, the surfaces that read from it, and any
future agent or human introducing new event types, projections, or
consumers.

It authorizes **no** implementation work. Step 11 (compliance_state)
is the most recent authorized implementation step. Step 12
(recommendation_candidates) and Step 13 (surface_permissions) are
not authorized by this document; they will be planned and
authorized separately, and any implementation must conform to the
doctrine above.

Any conflict between this document and a future implementation
proposal is resolved by deferring the implementation, not by
softening the doctrine. The INV rules in §5 are non-negotiable.
The anti-patterns in §6 are non-revisable. The boundary in §2 is
the substrate's structural commitment to its own defensibility.
