# Phase B.4 — Implementation Plan (lead persistence primitives)

| Field | Value |
|---|---|
| Status | **Planning DRAFT — pending operator review before B.4.0 commit** |
| Date | 2026-05-11 |
| Scope of B.4 | `lead` table · `lead_event_definition` + `lead_event` tables · `lead_signal_definition` + `lead_signal` + `vertical_lead_signal_weight` tables · ORM models + repositories for all six · Lead lifecycle state machine (domain layer) · Lead recording helpers (record_event / record_signal) · `VerticalPack.lead_signal_weights()` Protocol extension · seed-utility extension for lead-signal weights. **Deterministic synthetic test data only.** |
| Out of scope for B.4 | 33k-lead dataset ingest · Charlie's database integration · bulk import / enrichment / dedupe pipelines · production-scale ingestion · Google Places integration · LLM integration · queues / async / event-bus expansion · `business_id` and `contact_phone_record_id` FK columns (deferred until target tables land) · `lead_dimension` table (rollup explainability) · `lead_enrichment` / `lead_source_attribution` (enrichment subsystem) · `blocklist` (suppression subsystem) · `phone_record` / `phone_observation` / `phone_reassignment_check` (phone intelligence subsystem) · `compliance_policy` / `compliance_policy_evaluation` (compliance subsystem) · `LeadEventProjectionPublisher` / `DatabaseEventPublisher` / `MultiPublisher` (ADR-044 defers to Phase C+) · frontend expansion (unless required for route/schema visibility — likely not) |
| Supersedes | none. Extends docs/phase-b-plan.md + docs/phase-b2-plan.md + docs/phase-b3-plan.md; inherits every prior phase Lock + ADR. |

---

## 1. Inheritance

Carries forward unchanged:

- **B.1** persistence foundations: async SQLAlchemy, alembic, repository pattern, env-var contract.
- **B.2** auth + tenancy: magic-link auth, signed cookies, `account` / `user` / `session` tables.
- **B.3** core/vertical separation: `app/vertical/` Protocol + registry + `local_business_ai_visibility` pack, `vertical_*` tables, scoring engine reads from DB via cache, `account.region` tag, `/v1/account/export` 501 stub.
- All Locked + Blocking ADRs through ADR-048.

Specifically load-bearing for B.4:

- **ADR-008** tenancy via `account_id` on every owned/derived row.
- **ADR-010** immutable + reproducible runs (analog applies to `lead_signal` observations — each row records the observation at a point in time and is never updated).
- **ADR-013** PII policy: `email_hash` / `email_encrypted` + `phone_hash` / `phone_encrypted` on `lead`.
- **ADR-016** soft-delete via `deleted_at` on customer-owned tables (`lead` is customer-owned).
- **ADR-027** additive-only migrations between deploys.
- **ADR-031** repository pattern.
- **ADR-035** lead intelligence as a first-class subsystem.
- **ADR-036** lead signals, dimensions, and explainability.
- **ADR-037** lead lifecycle states and event-driven evolution.
- **ADR-040** definition-driven event taxonomy.
- **ADR-044** canonical event envelope and publisher abstraction.
- **ADR-046** multi-region posture — `lead.region` not added in B.4 (regional routing deferred), but `account.region` already supplies the tenancy-scope region.
- **ADR-047** customer data ownership: `lead`, `lead_event`, `lead_signal` are **customer-owned + exportable**; `lead_event_definition`, `lead_signal_definition`, `vertical_lead_signal_weight` are **platform-owned**.
- **ADR-048** vertical pack lifecycle — extended in B.4.6 by adding `lead_signal_weights()` to the `VerticalPack` Protocol.

New constraints introduced by the **B.4 scope directive** (Andrew, 2026-05-11) saved to memory as `project_b4_scope_lead_primitives.md`:

- Architecture-first. No real data, no Charlie DB, no bulk pipelines.
- Deterministic synthetic test data only.
- Same discipline as B.3 (single FastAPI + single Postgres, no infrastructure).
- "Primitives stable before workflows" doctrine.

---

## 2. Decisions locked for B.4

| # | Question | Locked answer |
|---|---|---|
| 1 | Lead table shape | Combined v1.2 + v1.3 in a single `CREATE TABLE` (no `ALTER TABLE` migration to a non-existent prior shape). Includes `lifecycle_state` CHECK constraint, PII columns (`email_hash` + `email_encrypted` + `phone_hash` + `phone_encrypted`), consent fields, `vertical_id` FK to `vertical(id)`, `first_seen_at` + `last_engaged_at`, standard `created_at` / `updated_at` / `deleted_at`. |
| 2 | Deferred columns | `business_id` (target table `business` doesn't exist) + `contact_phone_record_id` (target table `phone_record` doesn't exist). Both added by future additive migrations per ADR-027 when their target tables ship. |
| 3 | Lifecycle states | Per ADR-037 + LOCK §2.5.1: `{'cold','warm','engaged','qualified','opportunity','customer','dormant','unsubscribed'}`. Default `'cold'`. CHECK constraint at DB; Python-side enum constants in `app/domain/leads/lifecycle.py`. |
| 4 | Lifecycle transitions | **Open in B.4** — `transition()` validates that the target state is in the allowed enum (CHECK passes) but does NOT yet enforce a from→to allowed-transitions matrix. Transition rules land when business workflows that depend on them activate; the seam exists. |
| 5 | Lead event taxonomy | Per ADR-040 + LOCK §2.5.3: `lead_event_definition` is a DB catalog; `lead_event` rows reference it via `event_definition_id`. Catalog seeded with placeholder rows (`engagement.opened`, `engagement.replied`, `intent.qualified`, `lifecycle.transition`) so the FK is satisfied for synthetic tests. Real taxonomy expansion is a later phase. |
| 6 | Lead event projection mechanism | **Direct repository writes** — domain code calls `LeadEventRepository.create(...)` from async contexts. The canonical-envelope-to-projection-table publisher (ADR-044 `DatabaseEventPublisher` + `MultiPublisher`) is explicitly deferred to Phase C+ when async worker support lands; bridging sync `publish_event()` to async DB writes in B.4 would require queues, which the directive forbids. |
| 7 | Signal observation immutability | Per ADR-010 analog: `lead_signal` rows are APPEND-ONLY. Each call to `LeadSignalRepository.record(...)` writes a new row with `observed_at` + `recorded_at`. The "current value" of a signal for a lead is the row with the latest `observed_at` per `(lead_id, signal_name)` — resolved in Python by the repo's `find_current` helper. No `lead_signal_snapshot` table; `lead_signal` IS the snapshot table. |
| 8 | Per-vertical lead-signal weights | `vertical_lead_signal_weight` table lands in B.4.3. Weight history via `effective_from` / `effective_to` columns (mirrors `vertical_signal_weight` from B.3.3). `VerticalPack.lead_signal_weights() -> dict[str, float]` Protocol extension lands in B.4.6. |
| 9 | Lead signal evaluation execution | **Out of scope for B.4** — B.4 builds the persistence (table + repo + seed) but does NOT yet run signal probes against leads. Signal evaluation lands when ingest activates (B.5+). |
| 10 | Ownership classification per ADR-047 | Customer-owned (exportable): `lead`, `lead_event`, `lead_signal`. Platform-owned (NOT exportable): `lead_event_definition`, `lead_signal_definition`, `vertical_lead_signal_weight`. The `/v1/account/export` stub's `contents_when_implemented` extends in B.4 to list `leads` + `lead_events` + `lead_signals`. |
| 11 | Tests | All tests use deterministic synthetic data. Each repo gets behavior tests with mock `AsyncSession`. Mock-only — no real DB integration tests in B.4 (consistent with B.1–B.3). Real-DB integration is a deferred testing concern. |
| 12 | Locale + region | `lead` has no `region` column in B.4 — region comes from `account.region` (B.3.5) via join. Future regional-routing work can add a denormalized `lead.region` if access patterns demand it. |
| 13 | Audit-log integration | `lead_event` is a separate timeline from `audit_log`. Privileged operations on a lead (admin force-transition, manual blocklist add) write to BOTH `audit_log` (per ADR-015 — coming in a future platform-action phase) AND `lead_event`. B.4 does not yet wire `audit_log` writes — that's tracked separately. |
| 14 | Frontend | **No expansion.** B.4 is backend-only. The frontend continues to consume `/v1/analyses-legacy`. |

---

## 3. Architecture after B.4

```
backend/app/
├── core/                              # unchanged
├── api/                               # unchanged
├── db/
│   ├── models/
│   │   ├── lead.py                    # NEW (B.4.1)
│   │   ├── lead_event.py              # NEW (B.4.2)
│   │   ├── lead_event_definition.py   # NEW (B.4.2)
│   │   ├── lead_signal.py             # NEW (B.4.3)
│   │   ├── lead_signal_definition.py  # NEW (B.4.3)
│   │   ├── vertical_lead_signal_weight.py  # NEW (B.4.3)
│   │   └── __init__.py                # extended
│   └── repositories/
│       ├── lead_repo.py               # NEW (B.4.1)
│       ├── lead_event_repo.py         # NEW (B.4.2)
│       ├── lead_event_definition_repo.py    # NEW (B.4.2)
│       ├── lead_signal_repo.py        # NEW (B.4.3)
│       ├── lead_signal_definition_repo.py   # NEW (B.4.3)
│       └── vertical_lead_signal_weight_repo.py  # NEW (B.4.3)
├── domain/
│   ├── leads/                         # NEW package (B.4.4 + B.4.5)
│   │   ├── __init__.py
│   │   ├── lifecycle.py               # state enum + transition() helper
│   │   ├── recording.py               # record_lead_event() + record_lead_signal() helpers
│   │   └── events.py                  # canonical event-type registrations for lead.*
│   ├── auth/                          # unchanged
│   ├── notifications/                 # unchanged
│   └── scoring.py                     # unchanged (B.3.4 final shape)
└── vertical/
    ├── pack.py                        # extended (B.4.6) — adds lead_signal_weights()
    ├── packs/local_business_ai_visibility/
    │   ├── lead_signal_weights.py     # NEW (B.4.6) — empty stub
    │   ├── __init__.py                # extended to expose new method
    │   └── ... (other modules unchanged)
    └── seed.py                        # extended (B.4.6) — seeds vertical_lead_signal_weight from pack
```

Key invariants after B.4:

- Every `lead*` table has an explicit ownership classification (customer vs platform) in its docstring (per ADR-047).
- `lead_signal` rows are append-only; the "current value" is resolved at read time by the repo.
- `lead_event` rows are written directly by domain code (not via a publisher) — pending the Phase C+ publisher unification.
- `VerticalPack.lead_signal_weights()` exists and returns `{}` for the reference pack — populates when real lead scoring activates.
- No business / phone_record / blocklist / compliance dependencies — those columns + tables are deferred.

---

## 4. Schema design (subset of LOCK §2.5)

Six tables. Schemas closely follow the locked design — the only B.4-specific change is the **deferred-columns** decision (§2 #2).

### `lead` (B.4.1, customer-owned per ADR-047)

```sql
lead (
  id                    uuid PK,
  account_id            uuid NOT NULL REFERENCES account(id),
  vertical_id           uuid NULL REFERENCES vertical(id),
  source                text NOT NULL,
  lifecycle_state       text NOT NULL DEFAULT 'cold'
                        CHECK (lifecycle_state IN
                          ('cold','warm','engaged','qualified',
                           'opportunity','customer','dormant','unsubscribed')),
  email_hash            bytea NULL,
  email_encrypted       bytea NULL,
  phone_hash            bytea NULL,
  phone_encrypted       bytea NULL,
  consent_sms           boolean NOT NULL DEFAULT false,
  consent_email         boolean NOT NULL DEFAULT false,
  consent_source        text NULL,
  consent_at            timestamptz NULL,
  consent_ip_hash       bytea NULL,
  first_seen_at         timestamptz NOT NULL DEFAULT now(),
  last_engaged_at       timestamptz NULL,
  created_at, updated_at, deleted_at
)
INDEX (account_id) WHERE deleted_at IS NULL
INDEX (account_id, vertical_id) WHERE deleted_at IS NULL
INDEX (account_id, lifecycle_state) WHERE deleted_at IS NULL
INDEX (email_hash) WHERE deleted_at IS NULL AND email_hash IS NOT NULL
INDEX (phone_hash) WHERE deleted_at IS NULL AND phone_hash IS NOT NULL
```

**Deferred:** `business_id uuid NULL REFERENCES business(id)` + `contact_phone_record_id uuid NULL REFERENCES phone_record(id)`. Added by additive migrations when target tables land.

### `lead_event_definition` (B.4.2, platform-owned)

```sql
lead_event_definition (
  id                    uuid PK,
  event_type            text NOT NULL,
  version               int NOT NULL,
  status                text NOT NULL CHECK (status IN ('draft','active','retired')),
  category              text NOT NULL,
  source                text NOT NULL,
  default_weight        numeric(4,3) NOT NULL CHECK (default_weight BETWEEN 0 AND 1),
  freshness_ttl_seconds int NOT NULL,
  description           text,
  payload_schema        jsonb NOT NULL,
  lenient               boolean NOT NULL DEFAULT false,
  created_at, updated_at
)
UNIQUE (event_type, version)
INDEX (event_type) WHERE status = 'active'
```

B.4 simplification vs LOCK §2.5.3: omits `lead_event_category` and `lead_event_source` lookup tables (they were enum-style FK targets; we'll use plain text fields with documented value sets and add the lookup tables when admin tooling needs them). `category` + `source` are free-text in B.4.

### `lead_event` (B.4.2, customer-owned)

```sql
lead_event (
  id                  uuid PK,
  account_id          uuid NOT NULL,
  lead_id             uuid NOT NULL REFERENCES lead(id),
  event_type          text NOT NULL,
  event_definition_id uuid NOT NULL REFERENCES lead_event_definition(id),
  payload             jsonb NOT NULL,
  actor_kind          text NOT NULL
                      CHECK (actor_kind IN ('user','system','webhook','job','ai')),
  actor_user_id       uuid NULL,
  occurred_at         timestamptz NOT NULL,
  recorded_at         timestamptz NOT NULL,
  created_at
)
INDEX (lead_id, occurred_at DESC)
INDEX (account_id, event_type, occurred_at DESC)
```

Append-only. No `deleted_at`. No UPDATE — the timeline is immutable.

### `lead_signal_definition` (B.4.3, platform-owned)

```sql
lead_signal_definition (
  name                    text PK,
  description             text NOT NULL,
  contributes_to          text[] NOT NULL,
  freshness_ttl_seconds   int NOT NULL,
  source_kind             text NOT NULL,
  default_weight          numeric(4,3) NOT NULL CHECK (default_weight BETWEEN 0 AND 1),
  default_enabled         boolean NOT NULL DEFAULT true,
  created_at, updated_at
)
```

### `lead_signal` (B.4.3, customer-owned)

```sql
lead_signal (
  id                uuid PK,
  account_id        uuid NOT NULL,
  lead_id           uuid NOT NULL REFERENCES lead(id),
  signal_name       text NOT NULL REFERENCES lead_signal_definition(name),
  value             jsonb NOT NULL,
  source            text NOT NULL,
  source_ref_id     uuid NULL,
  observed_at       timestamptz NOT NULL,
  recorded_at       timestamptz NOT NULL,
  created_at
)
INDEX (lead_id, signal_name, observed_at DESC)
INDEX (account_id, observed_at DESC)
```

Append-only. The repo's `find_current(lead_id, signal_name)` returns the row with the latest `observed_at` per `(lead_id, signal_name)`.

### `vertical_lead_signal_weight` (B.4.3, platform-owned)

```sql
vertical_lead_signal_weight (
  id                uuid PK,
  vertical_id       uuid NOT NULL REFERENCES vertical(id),
  signal_name       text NOT NULL REFERENCES lead_signal_definition(name),
  dimension         text NOT NULL,
  weight            numeric(4,3) NOT NULL CHECK (weight BETWEEN 0 AND 1),
  enabled           boolean NOT NULL DEFAULT true,
  effective_from    timestamptz NOT NULL,
  effective_to      timestamptz NULL,
  created_at
)
UNIQUE (vertical_id, signal_name, dimension, effective_from)
INDEX (vertical_id, signal_name)
```

History via `effective_from` + `effective_to` (matches `vertical_signal_weight` from B.3.3 except this one explicitly carries an effective_to for closing a historical version).

---

## 5. Domain layer

### `app/domain/leads/lifecycle.py` (B.4.4)

```python
LIFECYCLE_STATES = frozenset({
    "cold", "warm", "engaged", "qualified",
    "opportunity", "customer", "dormant", "unsubscribed",
})


async def transition(
    lead: Lead,
    *,
    new_state: str,
    actor_kind: str,
    actor_user_id: UUID | None,
    lead_repo: LeadRepository,
    lead_event_repo: LeadEventRepository,
    event_definition_repo: LeadEventDefinitionRepository,
    now_fn: Callable[[], datetime] = ...,
) -> Lead:
    """Validate + apply a lifecycle transition. Always records a
    `lifecycle.transition` event in lead_event. Open transitions in
    B.4 — any target state in LIFECYCLE_STATES is allowed; from->to
    matrix enforcement lands when business workflows demand it."""
```

Returns the updated lead. Raises `ValueError` if `new_state` not in `LIFECYCLE_STATES`.

### `app/domain/leads/recording.py` (B.4.5)

```python
async def record_lead_event(
    *,
    lead: Lead,
    event_type: str,
    payload: dict,
    actor_kind: str,
    actor_user_id: UUID | None,
    lead_event_repo: LeadEventRepository,
    event_definition_repo: LeadEventDefinitionRepository,
    now_fn: Callable[[], datetime] = ...,
) -> LeadEvent:
    """Resolve event_definition_id from the catalog (raise on missing),
    write a lead_event row. Append-only."""


async def record_lead_signal(
    *,
    lead: Lead,
    signal_name: str,
    value: dict,
    source: str,
    source_ref_id: UUID | None,
    observed_at: datetime,
    lead_signal_repo: LeadSignalRepository,
    signal_definition_repo: LeadSignalDefinitionRepository,
    now_fn: Callable[[], datetime] = ...,
) -> LeadSignal:
    """Validate signal_name is in the catalog (raise on missing),
    write a lead_signal row. Append-only."""
```

Both helpers are *thin* — they exist to centralize the catalog-validation step and the `recorded_at = now_fn()` stamping, so call sites can't accidentally write rows that violate the FK or skip the timestamp.

### `app/domain/leads/events.py` (B.4.5)

Registers canonical event types with `app.core.event_registry` for the lead taxonomy. Mirrors `app.domain.auth.events` from B.2.3. B.4 registers a minimal set:

- `lead.lifecycle.transition` — every lifecycle transition emits this
- `lead.signal.observed` — every signal observation emits this
- `lead.event.recorded` — every domain event recorded emits this (meta)

These flow through the existing `LoggingEventPublisher` to structured logs. The DB projection happens via the direct repo writes in `recording.py` / `lifecycle.py` — NOT via the publisher (see §2 #6).

---

## 6. Event projection — direct writes, not publisher

ADR-044 anticipates a `DatabaseEventPublisher` that projects canonical envelope events to `lead_event` / `audit_log` / `billing_event` / `compliance_policy_evaluation` rows. B.4 does NOT build this publisher because:

- `EventPublisher.publish()` is sync per ADR-044 v1.
- DB writes are async (asyncpg).
- Bridging sync→async in a sync method requires either a queue (forbidden by B.4 directive) or a worker (forbidden).
- ADR-044 explicitly defers `DatabaseEventPublisher` + `MultiPublisher` to Phase C+ when async workers land.

B.4 pattern: domain code calls the repository directly from async contexts:

```python
# in app/domain/leads/recording.py
await lead_event_repo.create(...)             # writes the row
publish_event("lead.event.recorded", ...)      # canonical envelope -> log
```

Two parallel mechanisms in B.4. The unification (single `publish_event` call that fans out to both log AND DB row) lands in a future phase when MultiPublisher arrives. Marked as a known limitation in `recording.py` docstrings.

---

## 7. Vertical pack extension (B.4.6)

`VerticalPack` Protocol gains one method (additive per ADR-048):

```python
def lead_signal_weights(self) -> dict[str, float]:
    """signal_name -> weight in [0.0, 1.0]. Used by the (future)
    lead scoring engine to weight signal contributions. B.4 ships
    with an empty dict on the reference pack — real lead scoring
    activates in a later phase."""
```

`local_business_ai_visibility` pack adds `lead_signal_weights.py` with an empty `LEAD_SIGNAL_WEIGHTS: dict[str, float] = {}` constant; pack `__init__.py` exposes the new method returning a copy of it.

`seed_pack(...)` in `app/vertical/seed.py` extends to seed `vertical_lead_signal_weight` rows from the pack's `lead_signal_weights()` — empty dict produces zero rows, but the seeding pathway exists.

`DatabaseBackedVerticalPack` extends to load `vertical_lead_signal_weight` rows at startup (same lifespan pattern as B.3.4).

---

## 8. Hard rules for every B.4+ commit

Carries forward from B.3 §8 unchanged, plus:

10. **No real data ingest.** Tests use deterministic synthetic leads / events / signals.
11. **Append-only on event + signal tables.** `lead_event` and `lead_signal` rows are written ONCE — no UPDATE paths in B.4.
12. **Customer-owned vs platform-owned classification.** Every new lead* table docstring states its ADR-047 classification.

---

## 9. Sub-task breakdown

Each sub-task is one commit, verify-then-commit per the locked rule.

| Sub | Title | Files | Verifies |
|---|---|---|---|
| **B.4.0** | Phase B.4 planning doc | `docs/phase-b4-plan.md` (this file) | Docs-only. Plan exists; future commits trace to it. No code change. Backend + frontend tests still pass at the prior baselines. |
| **B.4.1** | `lead` table + Lead model + LeadRepository | Migration `0013_lead.py` · `backend/app/db/models/lead.py` · `backend/app/db/repositories/lead_repo.py` · `backend/tests/test_lead_model.py` · `backend/tests/test_lead_repo.py` · `__init__.py` re-export | Migration chains from 0012. ORM matches §4. Lifecycle CHECK enforces enum at DB. Tenancy filter active (`account_id` present). Soft-delete filter active (`deleted_at` present). Partial indexes match spec. |
| **B.4.2** | `lead_event_definition` + `lead_event` tables + models + repos + canonical event types | Migrations `0014_lead_event_definition.py` + `0015_lead_event.py` · models · repos · `backend/app/domain/leads/__init__.py` + `events.py` (registry seed) · tests | Migrations chain. lead_event_definition is platform-owned (no account_id, no deleted_at). lead_event is customer-owned (account_id NOT NULL, append-only — no UPDATE). FK from lead_event to lead_event_definition. Event-type registry seeded with the lead.* placeholder set. |
| **B.4.3** | `lead_signal_definition` + `lead_signal` + `vertical_lead_signal_weight` tables + models + repos | Migrations `0016_lead_signal_definition.py` + `0017_lead_signal.py` + `0018_vertical_lead_signal_weight.py` · models · repos · tests | Three migrations chain. Signal definitions platform-owned; signals customer-owned + append-only; weights platform-owned with history (`effective_from` / `effective_to`). LeadSignalRepository has `find_current(lead_id, signal_name)` returning latest-observed. |
| **B.4.4** | Lead lifecycle state machine (domain layer) | `backend/app/domain/leads/lifecycle.py` · `backend/tests/test_lead_lifecycle.py` | `LIFECYCLE_STATES` frozenset. `transition()` validates target state in enum, updates `lead.lifecycle_state`, records `lead.lifecycle.transition` event via the recording helper (B.4.5 will land both together — combined commit). |
| **B.4.5** | Lead recording helpers + canonical event registration | `backend/app/domain/leads/recording.py` · `backend/app/domain/leads/events.py` (extended) · tests | `record_lead_event` + `record_lead_signal` helpers wrap repo writes with catalog validation. Idempotent event-type registration (matches B.2.3 auth events pattern). |
| **B.4.6** | `VerticalPack.lead_signal_weights()` Protocol extension + pack stub + seed + cache | `backend/app/vertical/pack.py` (extend Protocol) · `backend/app/vertical/packs/local_business_ai_visibility/lead_signal_weights.py` (new, empty) · `__init__.py` (expose method) · `backend/app/vertical/seed.py` (extend to write `vertical_lead_signal_weight`) · `backend/app/vertical/db_pack.py` (extend `DatabaseBackedVerticalPack` to load `vertical_lead_signal_weight` rows at startup) · tests | Protocol extension additive (per ADR-048). Reference pack returns `{}`. Seed utility writes zero rows for the empty dict — pathway exists. Lifespan pre-load + cache surface unchanged in shape. |

**7 commits total. Each independently revertible.**

---

## 10. What B.4 explicitly does NOT do

- No `business_id` or `contact_phone_record_id` columns on `lead` (deferred).
- No `lead_dimension` table (rollup explainability — lands when scoring rollups compute real data).
- No `lead_enrichment` table (enrichment subsystem — lands with real data sources).
- No `lead_source_attribution` table (attribution subsystem — same).
- No `blocklist` table (suppression subsystem — separate phase).
- No `phone_record` / `phone_observation` / `phone_reassignment_check` (phone intelligence — separate phase).
- No `compliance_policy` / `compliance_policy_evaluation` (compliance subsystem — separate phase, attorney input gate per ADR-042).
- No `DatabaseEventPublisher` / `MultiPublisher` (ADR-044 defers to Phase C+).
- No actual lead signal evaluation against real data (the tables + repos exist; the probes are deferred).
- No bulk import / ingest / dedupe pipelines.
- No Charlie's database integration.
- No Google Places / LLM integration.
- No frontend changes.
- No new env vars beyond what already exists.
- No new infrastructure (single FastAPI + single Postgres throughout).

---

## 11. Cross-phase implications activated by B.4

When B.4 lands:

- **The platform CAN persist leads** — operator-loaded synthetic leads have a durable home. Real-data ingest in a later phase plugs into the existing tables.
- **The lead-event timeline exists** — every domain operation that touches a lead can record a timeline entry. Future CRM / Sara / monitoring features read from `lead_event`.
- **Per-vertical lead signal weights exist as data** — when a future commit activates real lead scoring, the weights are already DB-driven via the same pattern as B.3 business scoring.
- **Customer export gains real content** — `/v1/account/export` `contents_when_implemented` (B.3.7) lists `leads`, `lead_events`, `lead_signals` once those tables exist; the export implementation (future phase) reads from them.
- **The publisher unification problem becomes load-bearing** — `recording.py`'s parallel-write pattern (repo write + log publish) is the prototype for what MultiPublisher will replace. The shape of that future refactor is constrained by what B.4 commits to here.

---

## 12. Pre-flight items for Andrew (between now and `proceed B.4.1`)

- [ ] Confirm the 14 decisions in §2 (or override any).
- [ ] Confirm sub-task ordering in §9 (or rebundle).
- [ ] Confirm OUT-OF-SCOPE list in §10 — especially:
      - Deferred `business_id` / `contact_phone_record_id` columns
      - Deferred `lead_dimension` table
      - Direct-write event projection (no publisher in B.4)
      - Combined B.4.4 + B.4.5 commit (lifecycle + recording helpers together)
- [ ] Confirm event-type registry placeholders (`lead.lifecycle.transition`, `lead.signal.observed`, `lead.event.recorded`) or override the initial set.
- [ ] Operator-side: nothing required for B.4.0 itself. B.4.1+ requires `alembic upgrade head` against docker-compose Postgres locally before staging deploy.

---

## 13. Sign-off / next gate

| Action | Requires |
|---|---|
| Commit this plan | `commit B.4.0` |
| Push | `push B.4.0` |
| Begin B.4.1 (lead table + model + repo) | `proceed B.4.1` |
| Override any decision in §2 or §9 | reply with override + revised `proceed B.4.0-amend` |

No auto-proceed beyond this planning commit.
