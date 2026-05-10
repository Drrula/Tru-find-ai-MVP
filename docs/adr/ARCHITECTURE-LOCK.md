# ARCHITECTURE LOCK

| Field | Value |
|---|---|
| Version | v1.6 |
| Status | **Phase B.2 complete; B.3 planning locked** (B.2 closed 2026-05-10 at commit `792a2f1`; B.3.0 lands this revision + ADRs 045–048 per Platform Directive v1) |
| Locked | 2026-05-10 |
| Region | US East (Railway) — single-region operational; multi-region commitment + `account.region` tag introduced by ADR-046 (informational only in B.3) |
| Supersedes | v1.5 (extends with ADRs 045–048: platform identity placeholder, multi-region posture, customer data ownership vs platform IP, vertical pack lifecycle — operationalizing ADR-011). v1.4 (ADR-044: canonical event envelope and publisher abstraction). v1.3 (ADR-043: finance & commercial compliance placeholder). v1.2 (ADRs 035–042: lead intelligence, communication compliance, phone intelligence, compliance policy). See `LOCK-SUMMARY.md` for the questionnaire decisions that produced ADRs 035–042. |
| Change rule | See `docs/adr/README.md`. Modifying a Locked ADR or finalized schema requires a superseding ADR. Modifying a **Blocking ADR** (ADR-034) requires explicit review before implementation proceeds. |

This document is the contract. Implementation conforms to it. Phase A may not begin until this is committed and acknowledged. Subsequent phases inherit every assumption stated here.

---

## Part 1 — ADR index (48 entries)

The full text of each ADR is in `docs/adr/ADR-NNN-*.md`. Status legend:

- **Locked** — full-strength; changing requires a superseding ADR.
- **Locked-default** — accepted by default; same change rule, lower historical blast radius.
- **Blocking ADR (per ADR-034)** — affects tenancy, canonical entities, AI mutation behavior, security/compliance, billing/entitlements, environment separation, communication systems, or irreversible schema decisions. Modifications gate implementation until reviewed.

| ID | Title | Status | Blocking |
|---|---|---|---|
| 001 | FastAPI as the API framework | Locked-default | No |
| 002 | Postgres as primary datastore | Locked-default | Yes |
| 003 | Redis for queues + ephemeral state | Locked-default | No |
| 004 | `arq` worker runtime | Locked-default | No |
| 005 | Async-with-poll API contract | **Locked** | Yes |
| 006 | Stateless API; durable state in Postgres only | Locked-default | No |
| 007 | Monorepo, domain-oriented layout | Locked-default | No |
| 008 | Tenancy via `account_id` on every owned row | **Locked** | Yes |
| 009 | Business canonical identity | Locked-default | Yes |
| 010 | `analysis_run` is immutable and reproducible | **Locked** | Yes |
| 011 | Verticals are data, not code | **Locked** | Yes |
| 012 | `external_cache` as a layer outside clients | Locked-default | No |
| 013 | PII policy: encrypt-at-rest, hash-for-lookup | **Locked** | Yes |
| 014 | `opt_out` global, channel-keyed | Locked-default | Yes |
| 015 | `audit_log` from day one | Locked-default | Yes |
| 016 | Soft-delete via `deleted_at` on user-owned data | Locked-default | No |
| 017 | Path-based API versioning (`/v1/...`) | Locked-default | No |
| 018 | DIY magic-link auth, hosted-provider escape hatch | Locked-default | Yes |
| 019 | Server-side entitlement is the only paywall | **Locked** | Yes |
| 020 | Versioned prompts as DB rows | **Locked** | Yes |
| 021 | LLM output validated against JSON schema | Locked-default | Yes |
| 022 | Per-run AI cost cap | Locked-default | Yes |
| 023 | Stripe webhook is source of truth | Locked-default | Yes |
| 024 | Twilio behind a single adapter | Locked-default | Yes |
| 025 | 10DLC registration as launch prerequisite | **Locked** | Yes |
| 026 | Tag-driven prod, branch-driven staging | Locked-default | Yes |
| 027 | Additive-only migrations between deploys | Locked-default | Yes |
| 028 | Feature flags wrap user-visible new behavior | Locked-default | No |
| 029 | Backups, PITR, tested restore | Locked-default | No |
| 030 | Sentry + structured JSON logs + Railway metrics | Locked-default | No |
| 031 | Repository pattern for all DB access | Locked-default | Yes |
| 032 | Idempotency keys are explicit and stored | Locked-default | Yes |
| 033 | UUIDv7 for all primary keys | Locked-default | Yes |
| 034 | Blocking-ADR governance category | **Locked** | No (defines the rule) |
| 035 | Lead intelligence as a first-class subsystem | **Locked** | Yes |
| 036 | Lead signals, dimensions, and explainability | **Locked** | Yes |
| 037 | Lead lifecycle states and event-driven evolution | **Locked** | Yes |
| 038 | Warm-outbound positive-trigger requirement | **Locked** | Yes |
| 039 | Blocklist as account-scoped suppression | **Locked** | Yes |
| 040 | Definition-driven event taxonomy | **Locked** | Yes |
| 041 | Phone intelligence: line-type + ownership/reassignment | **Locked** | Yes |
| 042 | Compliance Policy Layer (placeholder) | **Locked (placeholder)** | Yes |
| 043 | Finance & commercial compliance (placeholder) | **Locked (placeholder)** | Yes |
| 044 | Canonical event envelope and publisher abstraction | **Locked (placeholder)** | Yes |
| 045 | Platform identity placeholder (`platform_core`) | **Locked (placeholder)** | No |
| 046 | Multi-region / data-residency posture | **Locked** | Yes |
| 047 | Customer data ownership vs. platform IP | **Locked** | Yes |
| 048 | Vertical pack lifecycle (operationalizes ADR-011) | **Locked** | Yes |

35 of 48 ADRs are Blocking ADRs. Any change to those, or any new ADR materially affecting the eight domains in ADR-034, requires explicit review before implementation proceeds.

---

## Part 2 — Final schema design

Postgres 15+. All tables in the `app` schema. `id` columns are `uuid` (UUIDv7, ADR-033). Timestamps are `timestamptz`. Soft-delete via `deleted_at`. `created_at`/`updated_at` present everywhere.

### 2.1 Tenancy classes

Every table belongs to exactly one class. The repository layer (ADR-031) enforces tenancy filters per class.

| Class | account_id | Examples |
|---|---|---|
| Tenant-owned | NOT NULL | `business`, `analysis_run`, `purchase`, `entitlement`, `import_batch`, `lead`, `sms_thread` |
| Tenant-derived | NOT NULL (denormalized) | `signal_result`, `gap`, `competitor_snapshot`, `ai_probe`, `verification_result`, `import_row`, `sms_message` |
| Identity | implicit via FK to user | `account`, `user`, `session`, `magic_link_token` |
| Global config | NULL/absent | `vertical`, `vertical_signal_weight`, `vertical_prompt_version`, `vertical_copy`, `vertical_template`, `signal_definition` |
| System | absent | `external_cache`, `audit_log`, `stripe_event`, `feature_flag`, `opt_out`, `job_run` |

`account_id` denormalization onto child tables is intentional: removes a join from every read path; enables future row-level security and per-tenant partitioning without schema work.

### 2.2 ERD

```
                 ┌─────────┐
                 │ account │
                 └────┬────┘
        ┌─────────────┼──────────────────────────────────────┐
        ▼             ▼                                      ▼
   ┌────────┐    ┌──────────┐                       ┌───────────────┐
   │  user  │    │ business │◄──────────────────────│ vertical (FK) │
   └────┬───┘    └────┬─────┘                       └───────┬───────┘
        │             │                                     │
   ┌────▼────┐        │                                     ├── vertical_signal_weight
   │ session │        │                                     ├── vertical_prompt_version
   └─────────┘        │                                     ├── vertical_copy
                      │                                     └── vertical_template
                      │
        ┌─────────────┼──────────────────────────────────┐
        ▼             ▼                                  ▼
   ┌──────────┐  ┌──────────────┐                   ┌──────┐
   │   lead   │  │ analysis_run │                   │ sms_ │
   └──────────┘  └──┬───────────┘                   │thread│
                    │                               └──┬───┘
        ┌───────────┼─────────┬────────────┐          │
        ▼           ▼         ▼            ▼          ▼
   ┌─────────┐ ┌────────┐ ┌─────┐ ┌─────────────┐ ┌────────┐
   │ signal_ │ │  gap   │ │ ai_ │ │ verification│ │  sms_  │
   │ result  │ │        │ │probe│ │   _result   │ │message │
   └─────────┘ └────────┘ └─────┘ └─────────────┘ └────────┘
                                       │
                                       └─► competitor_snapshot

   ┌──────────────┐    ┌────────────┐    ┌─────────────┐
   │ import_batch │───►│ import_row │───►│analysis_run │
   └──────────────┘    └────────────┘    └─────────────┘

   ┌──────────┐  ┌─────────────┐  ┌──────────────┐
   │ purchase │─►│ entitlement │─►│  business    │ (target)
   └──────────┘  └─────────────┘  └──────────────┘
        ▲
   ┌──────────────┐
   │ stripe_event │ (idempotency)
   └──────────────┘

   System tables (no account_id):
   external_cache · audit_log · feature_flag · opt_out · job_run · signal_definition
```

### 2.3 Table specs

#### Identity

```sql
account (
  id                    uuid PK,
  display_name          text NOT NULL,
  parent_account_id     uuid NULL REFERENCES account(id),
  status                text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','suspended','closed')),
  created_at, updated_at, deleted_at
)
INDEX (parent_account_id) WHERE parent_account_id IS NOT NULL

user (
  id                    uuid PK,
  account_id            uuid NOT NULL REFERENCES account(id),
  email_hash            bytea NOT NULL,
  email_encrypted       bytea NOT NULL,
  display_name          text,
  external_auth_id      text NULL,
  role                  text NOT NULL DEFAULT 'owner'
                        CHECK (role IN ('owner','admin','member')),
  last_login_at         timestamptz,
  created_at, updated_at, deleted_at
)
UNIQUE (email_hash) WHERE deleted_at IS NULL
INDEX (account_id)

session (
  id                    uuid PK,
  user_id               uuid NOT NULL REFERENCES user(id),
  account_id            uuid NOT NULL,
  issued_at             timestamptz NOT NULL,
  expires_at            timestamptz NOT NULL,
  revoked_at            timestamptz NULL,
  ip_hash               bytea,
  user_agent            text
)
INDEX (user_id, expires_at)

magic_link_token (
  id                    uuid PK,
  email_hash            bytea NOT NULL,
  email_encrypted       bytea NOT NULL,            -- B.2.2-amend: ciphertext per ADR-013; consume decrypts for self-signup
  token_hash            bytea NOT NULL UNIQUE,
  issued_at, expires_at, consumed_at timestamptz NULL,
  ip_hash               bytea
)
INDEX (token_hash) WHERE consumed_at IS NULL
```

#### Verticals (extension surface)

```sql
vertical (
  id                    uuid PK,
  slug                  text NOT NULL UNIQUE,
  display_name          text NOT NULL,
  status                text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','beta','retired')),
  template_id           uuid NULL REFERENCES vertical_template(id),
  default_competitor_filter jsonb,
  created_at, updated_at
)

vertical_template (
  id                    uuid PK,
  slug                  text NOT NULL UNIQUE,
  signal_set            text[] NOT NULL,
  notes                 text
)

signal_definition (
  name                  text PK,
  description           text NOT NULL,
  category              text NOT NULL
                        CHECK (category IN ('ai_presence','seo_strength','authority','performance')),
  default_weight        numeric(4,3) NOT NULL CHECK (default_weight BETWEEN 0 AND 1),
  default_enabled       boolean NOT NULL DEFAULT true,
  created_at, updated_at
)

vertical_signal_weight (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  signal_name           text NOT NULL REFERENCES signal_definition(name),
  weight                numeric(4,3) NOT NULL CHECK (weight BETWEEN 0 AND 1),
  enabled               boolean NOT NULL DEFAULT true,
  effective_from        timestamptz NOT NULL,
  effective_to          timestamptz NULL,
  created_at
)
UNIQUE (vertical_id, signal_name, effective_from)

vertical_prompt_version (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  probe_name            text NOT NULL,
  version               int NOT NULL,
  status                text NOT NULL CHECK (status IN ('draft','active','retired')),
  system_text           text NOT NULL,
  user_template         text NOT NULL,
  output_schema         jsonb NOT NULL,
  model                 text NOT NULL,
  max_tokens            int NOT NULL,
  created_at
)
UNIQUE (vertical_id, probe_name, version)
INDEX (vertical_id, probe_name) WHERE status = 'active'

vertical_copy (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  key                   text NOT NULL,
  locale                text NOT NULL DEFAULT 'en-US',
  text                  text NOT NULL,
  version               int NOT NULL,
  status                text NOT NULL CHECK (status IN ('draft','active','retired')),
  created_at
)
UNIQUE (vertical_id, key, locale, version)
```

#### Business and analysis

```sql
business (
  id                    uuid PK,
  account_id            uuid NOT NULL REFERENCES account(id),
  vertical_id           uuid NULL REFERENCES vertical(id),
  display_name          text NOT NULL,
  name_norm             text NOT NULL,
  location_raw          text NOT NULL,
  location_norm         text NOT NULL,
  dedupe_hash           bytea NOT NULL,
  website_url           text,
  place_id              text NULL,
  contact_email_hash    bytea, contact_email_encrypted bytea,
  contact_phone_hash    bytea, contact_phone_encrypted bytea,
  metadata              jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at, updated_at, deleted_at
)
UNIQUE (dedupe_hash) WHERE deleted_at IS NULL
INDEX (account_id, deleted_at)
INDEX (place_id) WHERE place_id IS NOT NULL

analysis_run (
  id                    uuid PK,
  account_id            uuid NOT NULL,
  business_id           uuid NOT NULL REFERENCES business(id),
  vertical_id           uuid NULL,
  status                text NOT NULL
                        CHECK (status IN ('pending','running','complete','partial','failed')),
  trigger               text NOT NULL
                        CHECK (trigger IN ('web_form','import','api','scheduled','verification')),
  idempotency_key       text NOT NULL,
  weight_snapshot       jsonb NOT NULL DEFAULT '{}'::jsonb,
  prompt_version_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  code_sha              text,
  total_score           int NULL CHECK (total_score BETWEEN 0 AND 100),
  cost_usd_cents        int NOT NULL DEFAULT 0,
  cost_cap_usd_cents    int NOT NULL,
  failure_reason        text NULL,
  started_at, completed_at,
  created_at, updated_at, deleted_at
)
UNIQUE (account_id, idempotency_key)
INDEX (account_id, business_id, created_at DESC)
INDEX (status) WHERE status IN ('pending','running')

signal_result (
  id                    uuid PK,
  analysis_run_id       uuid NOT NULL REFERENCES analysis_run(id),
  account_id            uuid NOT NULL,
  signal_name           text NOT NULL,
  status                text NOT NULL
                        CHECK (status IN ('pending','running','success','failed','skipped')),
  score                 numeric(4,3) NULL CHECK (score BETWEEN 0 AND 1),
  weight_used           numeric(4,3) NOT NULL,
  category              text NOT NULL,
  raw_payload_ref       uuid NULL REFERENCES external_cache(id),
  computed_at           timestamptz NULL,
  failure_reason        text NULL,
  created_at, updated_at
)
UNIQUE (analysis_run_id, signal_name)

gap (
  id                    uuid PK,
  analysis_run_id       uuid NOT NULL REFERENCES analysis_run(id),
  account_id            uuid NOT NULL,
  signal_name           text NOT NULL,
  severity              text NOT NULL CHECK (severity IN ('low','medium','high')),
  copy_key              text NOT NULL,
  copy_version          int NOT NULL,
  rendered_text         text NOT NULL,
  created_at
)

competitor_snapshot (
  id                    uuid PK,
  analysis_run_id       uuid NOT NULL REFERENCES analysis_run(id),
  account_id            uuid NOT NULL,
  rank                  int NOT NULL,
  name                  text NOT NULL,
  source                text NOT NULL CHECK (source IN ('places','synthetic')),
  score                 int NULL,
  external_id           text NULL,
  metadata              jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at
)

ai_probe (
  id                    uuid PK,
  analysis_run_id       uuid NOT NULL,
  account_id            uuid NOT NULL,
  probe_name            text NOT NULL,
  prompt_version_id     uuid NOT NULL REFERENCES vertical_prompt_version(id),
  model                 text NOT NULL,
  input_hash            bytea NOT NULL,
  output                jsonb NOT NULL,
  validated             boolean NOT NULL,
  tokens_in             int NOT NULL,
  tokens_out            int NOT NULL,
  cost_usd_cents        int NOT NULL,
  latency_ms            int NOT NULL,
  retry_count           smallint NOT NULL DEFAULT 0,
  created_at
)
INDEX (analysis_run_id, probe_name)

verification_result (
  id                    uuid PK,
  analysis_run_id       uuid NOT NULL REFERENCES analysis_run(id),
  account_id            uuid NOT NULL,
  signal_name           text NOT NULL,
  status                text NOT NULL
                        CHECK (status IN ('verified','unverified','conflicting','failed')),
  signal_result_id      uuid NOT NULL REFERENCES signal_result(id),
  rechecked_payload_ref uuid NULL REFERENCES external_cache(id),
  notes                 text,
  created_at
)
UNIQUE (analysis_run_id, signal_name)
```

#### Imports

```sql
import_batch (
  id                    uuid PK,
  account_id            uuid NOT NULL,
  source                text NOT NULL CHECK (source IN ('csv_upload','api')),
  file_hash             bytea,
  row_count             int NOT NULL DEFAULT 0,
  status                text NOT NULL
                        CHECK (status IN ('received','processing','complete','partial','failed')),
  error_summary         jsonb,
  created_at, updated_at, completed_at, deleted_at
)
UNIQUE (account_id, file_hash) WHERE file_hash IS NOT NULL AND deleted_at IS NULL

import_row (
  id                    uuid PK,
  import_batch_id       uuid NOT NULL REFERENCES import_batch(id),
  account_id            uuid NOT NULL,
  row_index             int NOT NULL,
  raw                   jsonb NOT NULL,
  business_id           uuid NULL REFERENCES business(id),
  analysis_run_id       uuid NULL REFERENCES analysis_run(id),
  status                text NOT NULL
                        CHECK (status IN ('queued','dispatched','complete','failed','skipped')),
  failure_reason        text,
  created_at, updated_at
)
UNIQUE (import_batch_id, row_index)
INDEX (status) WHERE status IN ('queued','dispatched')
```

#### Payments

```sql
stripe_event (
  id                    uuid PK,
  stripe_event_id       text NOT NULL UNIQUE,
  type                  text NOT NULL,
  payload               jsonb NOT NULL,
  received_at           timestamptz NOT NULL,
  processed_at          timestamptz NULL,
  process_error         text NULL
)

purchase (
  id                    uuid PK,
  account_id            uuid NOT NULL,
  stripe_session_id     text NOT NULL UNIQUE,
  stripe_customer_id    text,
  amount_cents          int NOT NULL,
  currency              text NOT NULL,
  product_code          text NOT NULL,
  status                text NOT NULL CHECK (status IN ('paid','refunded','disputed')),
  source_event_id       uuid REFERENCES stripe_event(id),
  created_at, updated_at
)

entitlement (
  id                    uuid PK,
  account_id            uuid NOT NULL,
  target_type           text NOT NULL CHECK (target_type IN ('business')),
  target_id             uuid NOT NULL,
  product_code          text NOT NULL,
  granted_at            timestamptz NOT NULL,
  expires_at            timestamptz NULL,
  revoked_at            timestamptz NULL,
  source_purchase_id    uuid REFERENCES purchase(id),
  created_at, updated_at
)
UNIQUE (account_id, target_type, target_id, product_code) WHERE revoked_at IS NULL
INDEX (account_id, target_id)
```

#### Notifications and leads

```sql
lead (
  id                    uuid PK,
  account_id            uuid NOT NULL,
  business_id           uuid NULL REFERENCES business(id),
  email_hash            bytea, email_encrypted bytea,
  phone_hash            bytea, phone_encrypted bytea,
  source                text NOT NULL,
  consent_sms           boolean NOT NULL DEFAULT false,
  consent_email         boolean NOT NULL DEFAULT false,
  consent_source        text,
  consent_at            timestamptz,
  consent_ip_hash       bytea,
  created_at, updated_at, deleted_at
)
INDEX (account_id, business_id) WHERE deleted_at IS NULL

opt_out (
  id                    uuid PK,
  channel               text NOT NULL CHECK (channel IN ('sms','email')),
  identifier_hash       bytea NOT NULL,
  source                text NOT NULL CHECK (source IN ('inbound_stop','admin','webhook')),
  recorded_at           timestamptz NOT NULL,
  account_id            uuid NULL
)
UNIQUE (channel, identifier_hash, account_id)

sms_thread (
  id                    uuid PK,
  account_id            uuid NOT NULL,
  business_id           uuid NULL,
  lead_id               uuid NULL,
  to_phone_hash         bytea NOT NULL,
  to_phone_encrypted    bytea NOT NULL,
  last_message_at       timestamptz,
  created_at, updated_at, closed_at, deleted_at
)
INDEX (account_id, last_message_at DESC)

sms_message (
  id                    uuid PK,
  thread_id             uuid NOT NULL REFERENCES sms_thread(id),
  account_id            uuid NOT NULL,
  direction             text NOT NULL CHECK (direction IN ('outbound','inbound')),
  status                text NOT NULL
                        CHECK (status IN ('queued','sent','delivered','failed','received')),
  template_key          text NULL,
  template_version      int NULL,
  rendered_text         text NOT NULL,
  twilio_sid            text,
  idempotency_key       text,
  error_code            text,
  error_message         text,
  sent_at, delivered_at, received_at,
  created_at, updated_at
)
UNIQUE (idempotency_key) WHERE idempotency_key IS NOT NULL
INDEX (thread_id, created_at)
```

#### System

```sql
external_cache (
  id                    uuid PK,
  provider              text NOT NULL,
  key_hash              bytea NOT NULL,
  payload               jsonb NOT NULL,
  payload_size          int NOT NULL,
  fetched_at            timestamptz NOT NULL,
  ttl_at                timestamptz NOT NULL,
  hit_count             int NOT NULL DEFAULT 0
)
UNIQUE (provider, key_hash)
INDEX (ttl_at)

audit_log (
  id                    uuid PK,
  account_id            uuid NULL,
  actor_user_id         uuid NULL,
  actor_kind            text NOT NULL CHECK (actor_kind IN ('user','system','admin','webhook')),
  action                text NOT NULL,
  target_type           text,
  target_id             uuid,
  payload_hash          bytea,
  request_id            text,
  recorded_at           timestamptz NOT NULL
)
INDEX (account_id, recorded_at DESC)
INDEX (target_type, target_id)

feature_flag (
  key                   text PK,
  scope                 text NOT NULL CHECK (scope IN ('global','account')),
  default_value         boolean NOT NULL,
  rules                 jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at
)

job_run (
  id                    uuid PK,
  queue                 text NOT NULL,
  job_name              text NOT NULL,
  payload_hash          bytea,
  account_id            uuid NULL,
  status                text NOT NULL
                        CHECK (status IN ('queued','running','success','failed','dead')),
  attempts              smallint NOT NULL DEFAULT 0,
  enqueued_at, started_at, finished_at,
  error                 text
)
INDEX (queue, status)
INDEX (job_name, finished_at DESC)
```

### 2.4 Constraint hygiene

- All FKs `ON DELETE RESTRICT` except where soft-delete is explicit.
- All `status`/`role`/`category` columns have `CHECK` constraints.
- All `*_at` defaults `now()` for `created_at`/`updated_at`; trigger updates `updated_at`.
- Numeric scores constrained `BETWEEN 0 AND 1` or `BETWEEN 0 AND 100` per scale.

### 2.5 Lead intelligence + communication compliance + phone intelligence (v1.3)

These tables land in Phase B's first migration alongside the v1.2 schema. Decisions and rationale: see ADRs 035–042 and `LOCK-SUMMARY.md`.

#### 2.5.1 `lead` (v1.2 row, with v1.3 column additions)

```sql
ALTER TABLE lead
  ADD COLUMN lifecycle_state    text NOT NULL DEFAULT 'cold'
             CHECK (lifecycle_state IN
               ('cold','warm','engaged','qualified','opportunity',
                'customer','dormant','unsubscribed')),
  ADD COLUMN vertical_id        uuid NULL REFERENCES vertical(id),
  ADD COLUMN first_seen_at      timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN last_engaged_at    timestamptz NULL,
  ADD COLUMN contact_phone_record_id uuid NULL REFERENCES phone_record(id);
```

#### 2.5.2 Lead signals & dimensions (ADR-036)

```sql
lead_signal_definition (
  name              text PK,
  description       text NOT NULL,
  contributes_to    text[] NOT NULL,
  freshness_ttl_seconds int NOT NULL,
  source_kind       text NOT NULL,
  default_weight    numeric(4,3) NOT NULL CHECK (default_weight BETWEEN 0 AND 1),
  default_enabled   boolean NOT NULL DEFAULT true,
  created_at, updated_at
)

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

lead_dimension (
  id                uuid PK,
  account_id        uuid NOT NULL,
  lead_id           uuid NOT NULL REFERENCES lead(id),
  dimension         text NOT NULL CHECK (dimension IN
                      ('lead_quality','engagement','ai_confidence',
                       'qualification','conversion_probability',
                       'communication_readiness','buying_window_intensity')),
  value_numeric     numeric(5,2) NULL,
  value_text        text NULL,
  computed_at       timestamptz NOT NULL,
  vertical_id       uuid NULL,
  weight_version_at timestamptz NOT NULL,
  inputs            jsonb NOT NULL,
  confidence        numeric(4,3) NULL CHECK (confidence BETWEEN 0 AND 1
                                              OR confidence IS NULL),
  created_at,
  CHECK ((value_numeric IS NULL) <> (value_text IS NULL))
)
INDEX (lead_id, dimension, computed_at DESC)
INDEX (account_id, computed_at DESC)
```

#### 2.5.3 Event taxonomy (ADR-040)

```sql
lead_event_category (
  name              text PK,
  description       text NOT NULL,
  contributes_to    text[] NOT NULL,
  status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired'))
)

lead_event_source (
  name              text PK,
  description       text NOT NULL,
  is_first_party    boolean NOT NULL,
  status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired'))
)

lead_event_definition (
  id                uuid PK,
  event_type        text NOT NULL,
  version           int NOT NULL,
  status            text NOT NULL CHECK (status IN ('draft','active','retired')),
  category          text NOT NULL REFERENCES lead_event_category(name),
  source            text NOT NULL REFERENCES lead_event_source(name),
  default_weight    numeric(4,3) NOT NULL CHECK (default_weight BETWEEN 0 AND 1),
  freshness_ttl_seconds int NOT NULL,
  description       text,
  payload_schema    jsonb NOT NULL,
  lenient           boolean NOT NULL DEFAULT false,
  created_at, updated_at
)
UNIQUE (event_type, version)
INDEX (event_type) WHERE status = 'active'

vertical_lead_event_weight (
  id                uuid PK,
  vertical_id       uuid NOT NULL REFERENCES vertical(id),
  event_type        text NOT NULL,
  weight            numeric(4,3) NOT NULL,
  enabled           boolean NOT NULL DEFAULT true,
  effective_from    timestamptz NOT NULL,
  effective_to      timestamptz NULL,
  created_at
)
UNIQUE (vertical_id, event_type, effective_from)

lead_event (
  id                  uuid PK,
  account_id          uuid NOT NULL,
  lead_id             uuid NOT NULL REFERENCES lead(id),
  event_type          text NOT NULL,
  event_definition_id uuid NOT NULL REFERENCES lead_event_definition(id),
  payload             jsonb NOT NULL,
  actor_kind          text NOT NULL CHECK (actor_kind IN ('user','system','webhook','job','ai')),
  actor_user_id       uuid NULL,
  occurred_at         timestamptz NOT NULL,
  recorded_at         timestamptz NOT NULL,
  created_at
)
INDEX (lead_id, occurred_at DESC)
INDEX (account_id, event_type, occurred_at DESC)
```

#### 2.5.4 Lead enrichment + attribution (ADR-035, ADR-036)

```sql
lead_enrichment (
  id                uuid PK,
  account_id        uuid NOT NULL,
  lead_id           uuid NOT NULL REFERENCES lead(id),
  provider          text NOT NULL,
  payload           jsonb NOT NULL,
  fetched_at        timestamptz NOT NULL,
  ttl_at            timestamptz NULL,
  created_at
)
INDEX (lead_id, provider, fetched_at DESC)

lead_source_attribution (
  id                uuid PK,
  account_id        uuid NOT NULL,
  lead_id           uuid NOT NULL REFERENCES lead(id),
  source            text NOT NULL,
  campaign          text NULL,
  medium            text NULL,
  ref_url           text NULL,
  utm_source        text NULL,
  utm_medium        text NULL,
  utm_campaign      text NULL,
  utm_term          text NULL,
  utm_content       text NULL,
  touched_at        timestamptz NOT NULL,
  is_first_touch    boolean NOT NULL,
  is_last_touch     boolean NOT NULL,
  created_at
)
INDEX (lead_id, touched_at)
```

#### 2.5.5 Blocklist (ADR-039)

```sql
blocklist (
  id                uuid PK,
  account_id        uuid NOT NULL REFERENCES account(id),
  channel           text NOT NULL CHECK (channel IN ('sms','email','any')),
  target_kind       text NOT NULL CHECK (target_kind IN ('contact_identifier','business','lead')),
  identifier_hash   bytea NOT NULL,
  reason            text NOT NULL,
  source            text NOT NULL,
  expires_at        timestamptz NULL,
  recorded_at       timestamptz NOT NULL,
  created_at, updated_at, deleted_at
)
UNIQUE (account_id, channel, target_kind, identifier_hash) WHERE deleted_at IS NULL
INDEX (account_id, channel) WHERE deleted_at IS NULL
```

#### 2.5.6 Phone intelligence (ADR-041)

```sql
phone_record (
  id                       uuid PK,
  e164_hash                bytea NOT NULL UNIQUE,
  e164_encrypted           bytea NOT NULL,
  country_code             text NOT NULL,
  -- Line-type
  phone_line_type          text NULL CHECK (phone_line_type IN
                             ('mobile','landline','voip','toll_free','unknown')
                             OR phone_line_type IS NULL),
  carrier_name             text NULL,
  lookup_provider          text NULL,
  lookup_confidence        numeric(4,3) NULL CHECK (lookup_confidence BETWEEN 0 AND 1
                                                     OR lookup_confidence IS NULL),
  lookup_checked_at        timestamptz NULL,
  lookup_attempt_count     int NOT NULL DEFAULT 0,
  sms_eligible             boolean NULL,
  voice_eligible           boolean NULL,
  last_lookup_result       jsonb NULL,
  lookup_cost_cents        int NOT NULL DEFAULT 0,
  -- Ownership / reassignment
  owner_confidence         numeric(4,3) NULL CHECK (owner_confidence BETWEEN 0 AND 1
                                                    OR owner_confidence IS NULL),
  owner_last_verified_at   timestamptz NULL,
  reassignment_risk        text NOT NULL DEFAULT 'unknown'
                           CHECK (reassignment_risk IN
                             ('low','medium','high','confirmed_reassigned','unknown')),
  first_seen_at            timestamptz NOT NULL,
  last_seen_at             timestamptz NOT NULL,
  created_at, updated_at
)
INDEX (lookup_checked_at) WHERE lookup_checked_at IS NULL
INDEX (reassignment_risk) WHERE reassignment_risk IN ('high','confirmed_reassigned')
INDEX (last_seen_at)

phone_observation (
  id                uuid PK,
  account_id        uuid NOT NULL,
  phone_record_id   uuid NOT NULL REFERENCES phone_record(id),
  lead_id           uuid NULL REFERENCES lead(id),
  business_id       uuid NULL REFERENCES business(id),
  source            text NOT NULL,
  raw_input_redacted text,
  first_seen_at     timestamptz NOT NULL,
  created_at
)
INDEX (account_id, phone_record_id)
INDEX (lead_id) WHERE lead_id IS NOT NULL
INDEX (business_id) WHERE business_id IS NOT NULL

phone_reassignment_check (
  id                    uuid PK,
  phone_record_id       uuid NOT NULL REFERENCES phone_record(id),
  provider              text NOT NULL,
  checked_at            timestamptz NOT NULL,
  result                text NOT NULL CHECK (result IN
                          ('current','reassigned','disconnected','unknown','error')),
  reassigned_on         date NULL,
  raw_response          jsonb NOT NULL,
  cost_cents            int NOT NULL DEFAULT 0,
  created_at
)
INDEX (phone_record_id, checked_at DESC)
```

#### 2.5.7 Compliance policy (ADR-042 placeholder)

```sql
compliance_policy (
  id              uuid PK,
  scope_kind      text NOT NULL CHECK (scope_kind IN
                    ('federal','state','channel','vertical','account','category','combination')),
  scope_value     jsonb NOT NULL,
  rule_kind       text NOT NULL,
  rule_value      jsonb NOT NULL,
  version         int NOT NULL,
  effective_from  timestamptz NOT NULL,
  effective_to    timestamptz NULL,
  status          text NOT NULL CHECK (status IN ('draft','active','retired')),
  source          text NOT NULL CHECK (source IN
                    ('attorney_provided','system_default','manual_override')),
  source_metadata jsonb,
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
  policies_evaluated  jsonb NOT NULL,
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

#### 2.5.8 `ai_probe` (v1.2 table, with v1.3 column additions)

```sql
ALTER TABLE ai_probe
  ADD COLUMN target_type text NOT NULL DEFAULT 'analysis_run'
             CHECK (target_type IN ('analysis_run','lead')),
  ADD COLUMN lead_id     uuid NULL REFERENCES lead(id);
-- analysis_run_id remains NOT NULL in v1.2; in v1.3 it becomes NULLABLE with a
-- CHECK constraint that exactly one of (analysis_run_id, lead_id) is non-null.
-- Concrete migration ordering follows ADR-027 (additive between deploys).
```

### 2.6 Finance & commercial compliance (v1.4 placeholder)

These tables land in Phase B's first migration as empty placeholders alongside §2.5. Decisions and rationale: ADR-043. Stripe is the locked payments primitive; tax and accounting providers behind adapters with concrete vendors deferred (§5.14, §5.15).

#### 2.6.1 `entitlement` and `purchase` (v1.2 tables, with v1.4 column additions)

```sql
ALTER TABLE entitlement
  ADD COLUMN subscription_id uuid NULL REFERENCES billing_subscription(id);
-- Existing source_purchase_id remains; CHECK that exactly one source
-- (purchase or subscription) is populated per row.

ALTER TABLE purchase
  ADD COLUMN tax_amount_cents     int NOT NULL DEFAULT 0,
  ADD COLUMN tax_jurisdiction_id  uuid NULL REFERENCES tax_jurisdiction(id);
```

#### 2.6.2 Subscriptions (ADR-043)

```sql
billing_subscription (
  id                       uuid PK,
  account_id               uuid NOT NULL REFERENCES account(id),
  stripe_subscription_id   text NOT NULL UNIQUE,
  product_code             text NOT NULL,
  status                   text NOT NULL CHECK (status IN
                             ('trialing','active','past_due','canceled','unpaid','paused')),
  current_period_start     timestamptz NOT NULL,
  current_period_end       timestamptz NOT NULL,
  cancel_at                timestamptz NULL,
  canceled_at              timestamptz NULL,
  source_event_id          uuid REFERENCES stripe_event(id),
  created_at, updated_at
)
INDEX (account_id, status)
```

#### 2.6.3 Invoices (ADR-043)

```sql
invoice (
  id                       uuid PK,
  account_id               uuid NOT NULL,
  stripe_invoice_id        text NOT NULL UNIQUE,
  invoice_number           text NULL,
  subscription_id          uuid NULL REFERENCES billing_subscription(id),
  status                   text NOT NULL CHECK (status IN
                             ('draft','open','paid','void','uncollectible')),
  amount_subtotal_cents    int NOT NULL,
  amount_tax_cents         int NOT NULL DEFAULT 0,
  amount_total_cents       int NOT NULL,
  currency                 text NOT NULL,
  hosted_invoice_url       text NULL,
  pdf_url                  text NULL,
  issued_at                timestamptz NULL,
  paid_at                  timestamptz NULL,
  due_at                   timestamptz NULL,
  source_event_id          uuid REFERENCES stripe_event(id),
  created_at, updated_at
)
INDEX (account_id, issued_at DESC)

invoice_line (
  id                       uuid PK,
  invoice_id               uuid NOT NULL REFERENCES invoice(id),
  account_id               uuid NOT NULL,
  description              text NOT NULL,
  quantity                 int NOT NULL DEFAULT 1,
  unit_amount_cents        int NOT NULL,
  amount_cents             int NOT NULL,
  product_code             text,
  metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at
)
```

#### 2.6.4 Refunds and credits (ADR-043)

```sql
refund (
  id                       uuid PK,
  account_id               uuid NOT NULL,
  purchase_id              uuid NULL REFERENCES purchase(id),
  invoice_id               uuid NULL REFERENCES invoice(id),
  stripe_refund_id         text NOT NULL UNIQUE,
  amount_cents             int NOT NULL,
  currency                 text NOT NULL,
  reason                   text NULL,
  status                   text NOT NULL CHECK (status IN
                             ('pending','succeeded','failed','canceled')),
  source_event_id          uuid REFERENCES stripe_event(id),
  created_at, updated_at
)
INDEX (account_id, created_at DESC)

credit (
  id                       uuid PK,
  account_id               uuid NOT NULL,
  amount_cents             int NOT NULL,
  currency                 text NOT NULL,
  reason                   text NOT NULL,
  expires_at               timestamptz NULL,
  source_event_id          uuid NULL REFERENCES stripe_event(id),
  created_by_user_id       uuid NULL,
  created_at, updated_at
)
INDEX (account_id, expires_at)
-- Consumption order: FIFO by expires_at NULLS LAST, then created_at ASC.
```

#### 2.6.5 Billing address and tax metadata (ADR-043)

```sql
billing_address (
  id                       uuid PK,
  account_id               uuid NOT NULL REFERENCES account(id),
  line1_encrypted          bytea,
  line2_encrypted          bytea,
  city                     text,
  state                    text,
  postal_code              text,
  country                  text NOT NULL,
  tax_id_encrypted         bytea,
  is_primary               boolean NOT NULL DEFAULT true,
  effective_from           timestamptz NOT NULL,
  effective_to             timestamptz NULL,
  source_event_id          uuid REFERENCES stripe_event(id),
  status                   text NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active','superseded','retired')),
  created_at, updated_at, deleted_at
)
INDEX (account_id, is_primary) WHERE deleted_at IS NULL AND is_primary = true

tax_jurisdiction (
  id                       uuid PK,
  account_id               uuid NOT NULL,
  billing_address_id       uuid NOT NULL REFERENCES billing_address(id),
  country                  text NOT NULL,
  state                    text NULL,
  locality                 text NULL,
  jurisdiction_code        text,
  tax_provider             text NULL,
  classified_at            timestamptz NOT NULL,
  raw_classification       jsonb NULL,
  created_at, updated_at
)
INDEX (account_id, classified_at DESC)

tax_exemption (
  id                       uuid PK,
  account_id               uuid NOT NULL,
  exemption_type           text NOT NULL CHECK (exemption_type IN
                             ('reseller','nonprofit','government','custom')),
  jurisdiction             text NOT NULL,
  certificate_ref          text,                   -- external object-storage URL (per §5.9)
  effective_from           timestamptz NOT NULL,
  effective_to             timestamptz NULL,
  status                   text NOT NULL CHECK (status IN
                             ('active','expired','revoked','pending')),
  source                   text NOT NULL CHECK (source IN
                             ('admin','customer_provided','provider_returned')),
  notes                    text,
  created_at, updated_at
)
INDEX (account_id, jurisdiction, status) WHERE status = 'active'
```

#### 2.6.6 Billing audit log (ADR-043)

```sql
billing_event (
  id                       uuid PK,
  account_id               uuid NOT NULL,
  event_type               text NOT NULL,
  -- Seed types: subscription_created, subscription_canceled, subscription_renewed,
  --             invoice_issued, invoice_paid, invoice_voided,
  --             refund_issued, credit_granted, credit_consumed,
  --             address_updated, exemption_recorded, exemption_revoked,
  --             tax_calculated.
  -- Definition-driven (analogous to ADR-040 pattern); new types via migration.
  target_kind              text NOT NULL CHECK (target_kind IN
                             ('subscription','invoice','purchase','refund',
                              'credit','address','exemption','tax_jurisdiction')),
  target_id                uuid NOT NULL,
  payload_hash             bytea,
  source_event_id          uuid NULL REFERENCES stripe_event(id),
  actor_kind               text NOT NULL CHECK (actor_kind IN
                             ('user','system','webhook','admin')),
  actor_user_id            uuid NULL,
  occurred_at              timestamptz NOT NULL,
  created_at
)
INDEX (account_id, occurred_at DESC)
INDEX (target_kind, target_id)
```

---

## Part 3 — Workflow lifecycles

### 3.1 Analysis run lifecycle

```
   create  ──► pending ──► running ──┬──► complete
                                     ├──► partial
                                     └──► failed
   (terminal states immutable except for soft-delete)
```

Invariants:
- Only legal path: `pending → running → terminal`.
- `weight_snapshot`, `prompt_version_snapshot`, `code_sha` sealed at terminal.
- Re-running creates a new `analysis_run`. No reopens.
- Cost cap exhaustion → `partial` with `failure_reason='cost_cap_reached'`, never `failed`.

### 3.2 Signal result lifecycle

```
pending → running → success | failed | skipped
```

Invariants:
- `skipped` requires a reason (cost cap, vertical disabled, missing dependency).
- Failed signals do not necessarily fail the run; the aggregator decides `partial` vs `failed`.

### 3.3 AI probe lifecycle (single transaction)

1. Resolve `prompt_version` by `(vertical_id, probe_name, status='active')`.
2. Build redacted context, hash → cache key.
3. Lookup `external_cache`; on hit, write `ai_probe` (validated=true, retry_count=0).
4. On miss: invoke LLM (with timeout), validate output against schema. On parse fail (once): repair-prompt retry.
5. Write `ai_probe` row (always, even on failure).
6. Atomic `UPDATE analysis_run SET cost_usd_cents = cost_usd_cents + N`.
7. If cost exceeds cap, halt further probes for the run.

Invariants:
- `prompt_version_id` captured at step 1, never changes for the probe.
- `ai_probe` is append-only.

### 3.4 Verification lifecycle

Triggered when `analysis_run.status='complete'` AND (entitlement exists OR `trigger='verification'`).

```
For each signal in run:
  - load signal_result
  - re-fetch external data with cache_bypass=true
  - re-probe with verification prompt (separate probe_name)
  - insert verification_result with status:
      verified     - match within tolerance
      unverified   - no usable re-fetch
      conflicting  - re-fetch contradicts original
      failed       - re-fetch failed
```

Invariants:
- Verification never mutates `signal_result`.
- `conflicting` flags an admin review surface.

### 3.5 Import lifecycle

```
upload CSV → file_hash → existing batch?
  yes & not failed → return existing (idempotent)
  no               → create import_batch(received), stream rows into import_row(queued)
↓
enqueue imports.batch.fanout
↓
worker per import_row(queued):
  - normalize raw → name_norm, location_norm
  - upsert business by dedupe_hash
  - create analysis_run(pending, idempotency_key=hash(batch_id, row_index))
  - mark import_row(dispatched, business_id, analysis_run_id)
  - enqueue scoring.run
↓
import_batch.status rolls up: complete | partial | failed
```

Dedupe: `dedupe_hash = sha256(account_id || '|' || name_norm || '|' || location_norm)` collapses duplicates within an account. Re-uploading same `file_hash` returns the existing batch.

### 3.6 Payment / entitlement lifecycle

```
Stripe Checkout → /v1/webhooks/stripe
  - verify HMAC
  - upsert stripe_event by stripe_event_id (idempotent)
  - enqueue payments.process_event
↓
worker dispatches by event type:
  checkout.session.completed → create purchase + entitlement
  charge.refunded            → purchase.status='refunded', revoke entitlement
  charge.dispute.created     → purchase.status='disputed', revoke entitlement
  - mark stripe_event.processed_at
  - audit_log entry
↓
nightly reconciliation against Stripe API
```

Invariants:
- Webhook idempotent on `stripe_event_id`.
- `entitlement` only created by webhook processor.
- `revoked_at` is the only post-grant mutation.

### 3.7 SMS lifecycle

Outbound: `notifications.send_sms` → opt_out check → render template → upsert thread → insert sms_message(queued) → enqueue → worker calls Twilio → status=sent → delivery callback → status=delivered.

Inbound: `/v1/webhooks/twilio` → HMAC verify → enqueue → worker resolves thread → insert sms_message(inbound) → STOP/UNSUBSCRIBE → write opt_out → carrier ack. Free-text inbound currently no auto-reply (per outstanding decision §5.8).

### 3.8 Auth lifecycle (magic link)

`POST /v1/auth/request` → create magic_link_token (rate-limited per email_hash) → email send. `GET /v1/auth/consume?token=...` → mark consumed → upsert user → issue session → audit_log.

---

## Part 4 — Service boundaries

### 4.1 Module dependency graph

```
       ┌──────────┐
       │   api    │   (HTTP transport only)
       └────┬─────┘
            │
            ▼
      ┌──────────┐         ┌──────────┐
      │  domain  │ ──────► │ clients  │ (external HTTP)
      └────┬─────┘         └────┬─────┘
           │                    │
           ▼                    ▼
      ┌──────────┐         ┌──────────┐
      │   db     │         │  core    │
      └──────────┘         └──────────┘
           ▲                    ▲
           │                    │
      ┌──────────┐               │
      │ workers  │ ──► domain ───┘
      └──────────┘
```

### 4.2 Allowed dependencies

| From | May import | May NOT import |
|---|---|---|
| `api/v1/*` | `domain/*` (public), `core/*`, `shared/schemas` | `clients/*`, `workers/*`, `db/*` |
| `domain/<X>` | own subtree, other `domain/Y` *public*, `clients/*`, `core/*`, `db/repositories/*` | `api/*`, `workers/*`, other `domain/<Y>/internal/*` |
| `clients/*` | `core/*` only | `domain/*`, `api/*`, `workers/*`, `db/*` |
| `workers/*` | `domain/*`, `core/*` | `api/*`, `db/*` directly |
| `db/models/*` | `core/*` | anything else |
| `db/repositories/*` | `db/models/*`, `core/*` | `domain/*`, `api/*` |
| `core/*` | nothing | everything else |

Each `domain/<X>` exposes `public.py`; everything else under it is internal.

### 4.3 Domain modules

```
backend/app/domain/
  identity/        accounts, users, sessions, magic links
  businesses/      records, normalization, dedupe
  scoring/         orchestrator, aggregator, weight resolver
  signals/         per-source modules + registry
  ai/              prompt registry, probe runner, output schemas
  payments/        Stripe checkout, webhook processor, entitlement
  imports/         CSV ingest, batch state machine, dedupe driver
  notifications/   email + sms send paths, opt-out, templates
  verticals/       config loader, weight/copy/prompt resolution
```

Inter-domain communication via audit-event reads or separately-enqueued jobs, never direct internal imports.

---

## Part 5 — Phase A task plan (summary)

Full breakdown in `docs/phase-a-plan.md`.

| # | Task | PR title |
|---|---|---|
| A.0 | Tag baseline | (git tag, no commit) |
| A.1 | Root hygiene + ADR docs | `chore: root .gitignore and ADR documentation` |
| A.2 | Commit existing untracked sources | `chore: commit existing untracked sources at baseline` |
| A.3 | Move backend, add pyproject.toml | `refactor(backend): move app/ into backend/ and adopt pyproject.toml` |
| A.4 | Core layer (config, logging, errors, middleware) | `feat(backend): introduce core layer` |
| A.5 | Versioned API + legacy alias | `feat(backend): version API at /v1 with legacy alias` |
| A.6 | Frontend api client | `refactor(frontend): centralize fetch via lib/api.js` |
| A.7 | Frontend layout cleanup | `refactor(frontend): move ResultsPage.jsx into src/` |
| A.8 | Batch script relocation | `chore(infra): move batch script to infra/scripts/ with CLI args` |
| A.9 | Test harness | `test: add backend pytest and frontend vitest harnesses` |
| A.10 | CI workflows | `ci: add lint, test, and deploy gate workflows` |
| A.11 | Railway environment scaffolding | `infra(railway): document staging and production environment structure` |
| A.12 | Observability | `feat(observability): wire Sentry on backend and frontend` |
| A.13 | Phase A completion review | `docs: phase A exit checklist` |

This commit (A.1) introduces no code changes. A.2 onward are gated on review of this document.

---

## Part 6 — File move plan (summary)

Full plan in `docs/phase-a-plan.md`. Headlines:

- A.3: `app/` → `backend/app/`, restructured under domain/clients/api/core/. `requirements.txt` → `backend/pyproject.toml`.
- A.5: routes move to `backend/app/api/v1/*`; legacy alias `/analyze-business` preserved.
- A.7: `frontend/ResultsPage.jsx` → `frontend/src/ResultsPage.jsx`.
- A.8: `run_batch_test.py` → `infra/scripts/batch_score.py` with argparse.

No files are moved or modified in the A.1 commit. Code-bearing moves begin at A.3.

---

## Part 7 — Commit boundary plan

Each Phase A commit produces a green CI on its own and is independently revertible. Boundaries:

| Commit | Title | Ships behavior change? |
|---|---|---|
| C0 | (tag pre-phase-a-baseline) | n/a |
| C1 | `chore: root .gitignore and ADR documentation` | docs only |
| C2 | `chore: commit existing untracked sources at baseline` | preserves current behavior |
| C3 | `refactor(backend): move app/ into backend/` | layout only |
| C4 | `feat(backend): introduce core layer` | adds middleware/logging |
| C5 | `feat(backend): version API at /v1 with legacy alias` | new prefix; legacy preserved |
| C6 | `refactor(frontend): centralize fetch via lib/api.js` | no functional change |
| C7 | `refactor(frontend): move ResultsPage.jsx into src/` | no functional change |
| C8 | `chore(infra): move batch script` | script path change |
| C9 | `test: add backend pytest and frontend vitest harnesses` | no functional change |
| C10 | `ci: add lint, test, and deploy gate workflows` | no functional change |
| C11 | `infra(railway): document environment structure` | docs only |
| C12 | `feat(observability): wire Sentry` | adds error reporting |
| C13 | `docs: phase A exit checklist` | docs only |

---

## Part 8 — Rollback plan (summary)

Full plan in `docs/rollback-assumptions.md`. Headlines:

- Per commit: `git revert <sha>`. Each commit is independently revertible.
- Phase-level: revert in reverse order, or `git reset --hard pre-phase-a-baseline` (absolute fallback).
- Staging: auto-deploy from `main`; revert at git level.
- Production: tag-driven; redeploy prior tag (Railway retains images).
- Phase A introduces no DB; data rollback is N/A until Phase B.

A rollback drill is required before declaring Phase A complete.

---

## Part 9 — Cross-phase assumptions (summary)

Full document in `docs/migration-assumptions.md` and `docs/scaling-assumptions.md`. Highlights:

**Phase B (persistence + auth) depends on:**
- A4 settings layer ready for `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`, `ENCRYPTION_KEY`.
- A3 domain modules importable at `app.domain.*`.
- A4 logging carries `request_id`; `account_id` slots into the same context.
- UUIDv7 generator in `core.ids` from first migration.

**Phase C (async API + workers) depends on:**
- B's `analysis_run`, `idempotency_key` columns.
- Legacy `/analyze-business` alias preserved through Phase B.

**Phase D (real signals) depends on:**
- B's `business`, `analysis_run`, `signal_result`, `vertical_*`.
- Outstanding decisions §5.4, §5.5 resolved.

**Phase E (payments) depends on:**
- B's `account`, `entitlement`, `purchase`, `stripe_event`.
- Outstanding §5.2, §5.3 resolved.

**Phase F (Twilio) depends on:**
- B's `lead`, `opt_out`, `sms_*` tables.
- 10DLC approved (started no later than Phase B).
- Outstanding §5.8 resolved.

**Phase G (imports v2) depends on:**
- B's `import_*` tables.
- Outstanding §5.9 resolved.

**Phase H (AI workflows) depends on:**
- B's `vertical_prompt_version`, `ai_probe`, `verification_result`, `external_cache`.
- D's real signals.
- Outstanding §5.6, §5.7 resolved.

**Always:** ADR-026, 027, 028, 029, 031, 032 in force from the moment they apply.

---

## Part 10 — Outstanding decisions (deferrable)

Listed for completeness; gates as previously specified. Full text in §3 of the prior architecture review.

| ID | Topic | Gate |
|---|---|---|
| 5.2 | Pricing model | Phase E |
| 5.3 | Refund / expiration policy | Phase E |
| 5.4 | Vertical taxonomy mgmt surface | Phase D |
| 5.5 | Weight resolution semantics | Phase D |
| 5.6 | LLM provider/model defaults | Phase H |
| 5.7 | Cost cap dollar amount | Phase H |
| 5.8 | Twilio auto-reply policy | Phase F |
| 5.9 | Object storage choice | Phase G |
| 5.10 | Secrets manager | Anytime |
| 5.11 | Phone lookup + reassignment provider concrete contract | Phase F |
| 5.12 | Compliance policy authoring path + initial ruleset (attorney input required) | Phase F |
| 5.13 | GDPR-erase / anonymization semantics (attorney input required) | Phase G or earlier on demand |
| 5.14 | Tax provider selection (Stripe Tax / Avalara / TaxJar) | Phase E or first international/multi-state customer |
| 5.15 | Accounting integration (QuickBooks / Xero / NetSuite / none) | Deferred; activate when bookkeeping volume warrants |
| 5.16 | Subscription pricing tiers, trial, dunning, proration | Phase E (gates first subscription product) |

---

## Part 11 — Sign-off

**Phase A may begin (A.2) when:**
1. This document committed at `docs/adr/ARCHITECTURE-LOCK.md`. ✅ this commit
2. 34 ADR files committed at `docs/adr/ADR-NNN-*.md`. ✅ this commit
3. Andrew confirmed US East as Railway region. ✅
4. Andrew confirmed commit boundaries in §7. ✅
5. `pre-phase-a-baseline` tag created. ✅

A.1 (this commit) is docs-only. Subsequent Phase A commits each require their own go-ahead.
