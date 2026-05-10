# Phase B.3 — Implementation Plan (core / vertical separation foundation)

| Field | Value |
|---|---|
| Status | **Planning locked, B.3.1 unblocked on `proceed B.3.1`** |
| Date | 2026-05-10 |
| Scope of B.3 | ADRs 045–048 locked · `app/vertical/` pack interface + registry · scoring/signals refactored into a vertical pack · `vertical_*` tables migrated and seeded · scoring engine reads from DB · `account.region` tag · `"TruFindAI"` references in core replaced with `platform_core` placeholder · `POST /v1/account/export` 501 stub locking the data-ownership commitment |
| Out of scope for B.3 | Sara orchestration layer · real email provider · multi-region routing / replication / cross-region DB · frontend auth UI · auth-gating existing routes · lead / lead_event / signals_v2 persistence · real Google Places integration · audit-log export to customers · per-account A/B testing of vertical pack versions · admin UI for editing pack data |
| Supersedes | none. Extends `docs/phase-b-plan.md` + `docs/phase-b2-plan.md`; inherits every Lock + every prior phase ADR. |

---

## 1. Inheritance

Carries forward unchanged:

- Phase B foundations (`docs/phase-b-plan.md`): async SQLAlchemy,
  alembic strategy, repository pattern, env-var contract baseline,
  PITR posture, rollback expectations.
- Phase B.2 (`docs/phase-b2-plan.md`): magic-link auth flow,
  `account` / `user` / `session` / `magic_link_token` tables,
  AES-256-GCM PII encryption, signed-cookie session model.
- Architecture lock through v1.5 — all 44 ADRs.

New constraints introduced by **Platform Directive v1** (Andrew,
2026-05-10) + the **Logical Modularity Before Physical Distribution**
rule + the **Platform Identity Placeholder** rule:

- ADR-045 — Platform identity placeholder (`platform_core`).
- ADR-046 — Multi-region / data-residency posture.
- ADR-047 — Customer data ownership vs. platform IP.
- ADR-048 — Vertical pack lifecycle (operationalizes ADR-011).

---

## 2. Decisions locked for B.3

| # | Question | Locked answer |
|---|---|---|
| 1 | Platform identity in code/docs | **`platform_core` placeholder** until a future naming ADR supersedes. No new hardcoded `"TruFindAI"` in shared core (ADR-045). |
| 2 | What lives in core vs. vertical packs | Per the directive's ownership lists: core owns auth/session, tenancy, audit/event, AI intelligence primitives, scoring/benchmarking primitives, workflow/automation primitives, CRM/lead primitives, reporting/analytics infrastructure, integration surfaces, deployment discipline. Packs own prompts, scoring weights, terminology, territory rules, benchmarks, reports, workflows, outreach templates, integrations, dashboards, KPIs, market-specific logic. |
| 3 | Source layout for packs | `backend/app/vertical/packs/<pack_id>/` per ADR-048. |
| 4 | Pack-engine seam | Protocol-based registry (`app/vertical/registry.py`) mirroring `app/core/event_registry.py`. Idempotent registration. |
| 5 | Reference pack name | `local_business_ai_visibility` — carries the current scoring/signals content. |
| 6 | When DB takes over from pack module | B.3.4 — engine reads from `vertical_*` tables via repositories. Pack module becomes the SEED for new deployments + tests. |
| 7 | Region representation | `account.region` (TEXT NOT NULL DEFAULT 'us'; CHECK allowlist `{'us','ca','uk'}`). Informational only in B.3. |
| 8 | Default region for new accounts | `Settings.default_region` (env `DEFAULT_REGION`; default `'us'`). |
| 9 | Customer-data export | `POST /v1/account/export` API surface lands as a 501 stub with documented response schema. Implementation deferred. |
| 10 | Audit-log access for customers | Deferred. Stub MUST NOT return `audit_log` rows; future endpoint requires explicit ADR. |
| 11 | Aggregate benchmarks | Platform IP. Per-customer percentiles within aggregates are exportable; aggregates themselves are not (ADR-047). |
| 12 | Locale coverage in vertical_copy | `'en-US'` only in B.3. ADR-046's no-US-only rule covers structure (locale-keyed schema); content for non-US locales is a future phase. |
| 13 | Physical distribution work in B.3 | **None.** Single FastAPI process, single Postgres, single Railway deployment. Modularity is logical-only per the binding rule. |
| 14 | Sara | Out of scope for B.3. Directive identifies it as a future modular intelligence/orchestration layer; no code lands in B.3. |

---

## 3. Architecture after B.3

```
backend/app/
├── core/                      # protected platform_core internals
│   ├── config.py              # Settings (gains default_region)
│   ├── crypto.py
│   ├── events.py
│   ├── event_registry.py
│   ├── ids.py
│   ├── logging.py
│   ├── middleware.py
│   ├── observability.py
│   └── pii.py
├── api/                       # transport
│   ├── deps.py
│   └── v1/
│       ├── auth.py
│       ├── analyses_legacy.py
│       ├── health.py
│       └── account.py         # NEW (B.3.7) — /v1/account/export 501 stub
├── db/                        # persistence
│   ├── base.py
│   ├── engine.py
│   ├── session.py
│   ├── models/                # adds vertical_*, account.region
│   └── repositories/          # adds vertical_repo (B.3.3+)
├── domain/                    # platform_core domain logic
│   ├── auth/
│   ├── notifications/
│   └── scoring/               # ENGINE only (B.3.2 moves vertical content out)
│       ├── engine.py
│       └── signals/           # signal primitives, NOT weights/copy
├── vertical/                  # NEW (B.3.1)
│   ├── pack.py                # VerticalPack Protocol
│   ├── registry.py
│   └── packs/
│       └── local_business_ai_visibility/
│           ├── __init__.py    # registers on import
│           ├── weights.py
│           ├── copy.py
│           ├── competitors.py
│           ├── tiers.py
│           └── categories.py
```

Key invariants after B.3:

- No `if vertical_id == "..."` branches anywhere in `app/core/`,
  `app/domain/`, or `app/api/`.
- No hardcoded `"TruFindAI"` in any file under `app/core/`,
  `app/api/`, `app/db/`, or `app/domain/`.
- Every account row has a `region`.
- The TruFindAI brand string lives only inside
  `app/vertical/packs/local_business_ai_visibility/` (or wherever a
  future TruFindAI vertical pack ends up) + in `vertical_copy` rows.

---

## 4. VerticalPack interface (indicative shape — finalized at B.3.1)

```python
# backend/app/vertical/pack.py

from typing import Protocol

class VerticalPack(Protocol):
    pack_id: str           # e.g. "local_business_ai_visibility"
    display_name: str
    schema_version: int

    def signal_weights(self) -> dict[str, float]: ...
    def copy(self) -> dict[tuple[str, str], str]: ...  # (locale, key) -> text
    def competitor_pool(self) -> list[str]: ...
    def tier_thresholds(self) -> dict[str, tuple[int, str]]: ...
    def category_mapping(self) -> dict[str, str]: ...
```

Final method signatures finalize in the B.3.1 commit. The registry
pattern matches `app/core/event_registry.py` for consistency.

---

## 5. `vertical_*` schema (B.3.3 migrations 0007–0011)

Per ARCHITECTURE-LOCK §2.3 (re-stated for completeness):

```sql
vertical (
  id                    uuid PK,
  pack_id               text NOT NULL UNIQUE,        -- maps to source layout
  display_name          text NOT NULL,
  schema_version        int NOT NULL,
  created_at, updated_at
)

vertical_signal_weight (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  signal_name           text NOT NULL,
  weight                numeric NOT NULL,
  effective_from        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (vertical_id, signal_name, effective_from)
)

vertical_copy (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  locale                text NOT NULL,               -- ISO 639-1 + region per ADR-046
  key                   text NOT NULL,               -- e.g. 'gap.no_website'
  text                  text NOT NULL,
  UNIQUE (vertical_id, locale, key)
)

vertical_template (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  name                  text NOT NULL,
  config_json           jsonb NOT NULL              -- signal set, tier thresholds, etc.
)

vertical_prompt_version (
  id                    uuid PK,
  vertical_id           uuid NOT NULL REFERENCES vertical(id),
  prompt_key            text NOT NULL,
  version               int NOT NULL,
  prompt_text           text NOT NULL,
  status                text NOT NULL,              -- 'draft' | 'active' | 'archived'
  UNIQUE (vertical_id, prompt_key, version)
)
```

All five tables are **platform-owned** per ADR-047 — not exported in
`/v1/account/export`.

---

## 6. `account.region` (B.3.5 migration 0012)

```sql
ALTER TABLE account
  ADD COLUMN region text NOT NULL DEFAULT 'us'
  CHECK (region IN ('us', 'ca', 'uk'));
```

Default `'us'` lets every existing account row backfill without
intervention. The CHECK constraint enforces the allowlist; future
regions are added by a separate migration + CHECK amendment +
explicit ADR-046 supersede note.

`Settings.default_region` (env `DEFAULT_REGION`) supplies the value
when account creation sites don't specify.

---

## 7. `/v1/account/export` stub (B.3.7)

```
POST /v1/account/export
  Auth: required (Depends(get_current_user))
  Response: 501 Not Implemented
  Body: {
    "error": {
      "code": "not_implemented",
      "message": "Account export is committed but not yet implemented; the response schema below is stable.",
      "request_id": "<uuid>"
    },
    "schema_version": 1,
    "contents_when_implemented": {
      "account": "...",
      "users": "[...]",
      "businesses": "[...]",
      "leads": "[...]",
      "purchases": "[...]",
      "opt_outs": "[...]"
    }
  }
```

The exact contents shape is the seed of the actual export's response
schema and matches the customer-owned classification in ADR-047 §1.
Implementation lands when an enterprise customer requires it (a
future phase explicitly).

---

## 8. Hard rules for every B.3+ commit

Distilled from the Platform Directive v1 + the modularity rule +
ADRs 045–048:

1. **Logical seams only.** New code lands as Protocols, registries,
   tables, repository methods, or API routes — never as new
   processes, containers, or out-of-process services.
2. **Single FastAPI process + single Postgres** throughout B.3.
   Worker processes per ADR-004 are permitted but no new ones land
   in B.3.
3. **No hardcoded vertical branches** in `app/core/`, `app/domain/`,
   `app/api/`, or `app/db/`.
4. **No hardcoded `"TruFindAI"` in shared core** (B.3.6 cleans up
   existing leaks).
5. **No US-only assumptions in new code** (per ADR-046).
6. **Customer-owned data is exportable; platform IP is not** — every
   new table classifies itself in the docstring per ADR-047.
7. **Baseline preserved at every step.** `analyze('Joe Pizza',
   'Brooklyn, NY').score == 60` after each commit, with the
   `local_business_ai_visibility` pack loaded as default.
8. **Verify-before-commit.** Backend pytest + frontend vitest + Vite
   build + import smoke before staging each commit.
9. **No auto-proceed between sub-phases.** Each B.3.X gates on
   explicit confirmation.

---

## 9. Sub-task breakdown

Each sub-task is one commit, verify-then-commit per the locked rule.

| Sub | Title | Files | Verifies |
|---|---|---|---|
| **B.3.0** | Phase B.3 planning doc + ADRs 045–048 + ARCHITECTURE-LOCK v1.6 | `docs/phase-b3-plan.md` (this file), `docs/adr/ADR-045-platform-identity-placeholder.md`, `docs/adr/ADR-046-multi-region-posture.md`, `docs/adr/ADR-047-customer-data-ownership.md`, `docs/adr/ADR-048-vertical-pack-lifecycle.md`, `docs/adr/ARCHITECTURE-LOCK.md` (version bump, ADR index extended to 48) | Docs-only commit. Plan exists; future commits trace to it. No code change. Backend + frontend tests still pass at the prior baselines. |
| **B.3.1** | `app/vertical/` skeleton — Protocol + registry + empty reference pack | `backend/app/vertical/__init__.py`, `backend/app/vertical/pack.py`, `backend/app/vertical/registry.py`, `backend/app/vertical/packs/__init__.py`, `backend/app/vertical/packs/local_business_ai_visibility/__init__.py` (stub), `backend/tests/test_vertical_registry.py` | Protocol declared; registry register/lookup works; idempotent re-registration; reference pack imports + registers itself with `pack_id="local_business_ai_visibility"`. No scoring change. |
| **B.3.2** | Move scoring/signals content into the reference pack; refactor engine to read from pack via registry | `backend/app/vertical/packs/local_business_ai_visibility/{weights,copy,competitors,tiers,categories}.py`, refactor of `backend/app/domain/scoring.py` (or split into `app/domain/scoring/engine.py`), `backend/app/domain/signals.py` (signal primitives stay; weights move out), updated tests | Baseline preserved: `analyze('Joe Pizza','Brooklyn, NY').score == 60` with pack loaded. No DB change. No core `"TruFindAI"` leak introduced. |
| **B.3.3** | Migrations 0007–0011: `vertical`, `vertical_signal_weight`, `vertical_copy`, `vertical_template`, `vertical_prompt_version` + ORM models + repositories + seed-from-pack utility | `backend/alembic/versions/0007_*.py` through `0011_*.py`, `backend/app/db/models/vertical*.py`, `backend/app/db/repositories/vertical_repo.py`, seed utility, tests | Migrations chain cleanly; ORM matches Lock §2.3; repository pattern preserved; seed utility writes pack data into DB; engine still reads from pack module (DB rows aspirational until B.3.4). Baseline preserved. |
| **B.3.4** | Wire scoring engine to read from `vertical_*` via repository instead of pack module | refactor of engine + signal primitives to take a `Vertical`-resolved configuration; pack module becomes seed-only; tests | After this commit, ADR-011 is actually true — verticals are data. Baseline preserved (the seeded pack rows produce the same `60`). Pack module unchanged structurally; only the read path differs. |
| **B.3.5** | Migration 0012: `account.region` column + `Settings.default_region` | `backend/alembic/versions/0012_account_region.py`, `backend/app/db/models/account.py` (add column), `backend/app/core/config.py` (add field), tests | Column added with default `'us'` and CHECK allowlist. Existing tests pass. No routing behavior change. |
| **B.3.6** | Replace `"TruFindAI"` references in shared core with `platform_core` placeholder; move brand strings into vertical pack | `backend/app/domain/notifications/email.py` (subject string moves to vertical_copy), audit pass on `backend/app/core/`, `backend/app/api/`, `backend/app/db/`, `backend/app/domain/` for any other leaks, README + frontend unchanged (deployment-brand surfaces) | No new hardcoded `"TruFindAI"` in core code paths. Existing operational identifiers (package name `trufindai-backend`, Sentry release tags, etc.) deferred to a future naming-finalization commit. Baseline preserved. |
| **B.3.7** | `POST /v1/account/export` 501 stub with documented response schema | `backend/app/api/v1/account.py` (new router), `backend/app/api/v1/__init__.py` (include), tests | Endpoint returns 501 with the documented contents-when-implemented schema. OpenAPI shows it. ADR-047 commitment is now load-bearing in the URL surface. |

**8 commits total. Each independently revertible.**

---

## 10. What B.3 explicitly does NOT do

- No Sara orchestration layer code lands. Sara is identified by the
  directive as a future modular intelligence/orchestration layer;
  B.3 makes it possible (vertical packs are the seam Sara will
  eventually plug into) without building it.
- No real email provider integration. `LoggingEmailSender` remains
  the active publisher (per phase-b2-plan.md §7).
- No multi-region routing, replication, or cross-region anything.
  `account.region` is informational only.
- No frontend auth UI; no auth-gating of existing routes
  (`/v1/health`, `/v1/analyses-legacy`, `/analyze-business` alias
  stay open).
- No lead / lead_event / signals_v2 persistence — those land in a
  future phase after the vertical foundation stabilizes.
- No real Google Places integration (signals stay mock).
- No audit-log export to customers — explicit future-ADR requirement
  per ADR-047.
- No admin UI for editing pack data — per ADR-048, deferred to
  Phase D+.
- No A/B testing of vertical pack versions per account — seam exists
  but no behavior lands.
- No rename of operational identifiers (`trufindai-backend` package
  name, Sentry tags, CI env names, etc.). Deferred to a future
  naming-finalization commit when the placeholder is replaced.
- No `pyproject.toml` package rename. High blast radius for a
  placeholder; revisit when a real name lands.

---

## 11. Cross-phase implications activated by B.3

When B.3 lands:

- **ADR-011 becomes actually true** for the first time — verticals
  are data, runtime-mutable via `vertical_*` tables, not hardcoded
  in core modules.
- **The directive's "Core engine separate from vertical
  configuration" line is enforceable** — the engine code under
  `app/domain/scoring/` no longer holds vertical content; pack
  source layout makes the boundary visible.
- **Multi-region work has a concrete starting point** —
  `account.region` exists; future routing/replication code reads
  from it.
- **Customer-export work has a URL surface** — `/v1/account/export`
  is a 501 stub today; the URL is locked, implementation can land
  any future phase without coordinating with consumers.
- **TruFindAI is operationally a vertical pack + a deployed brand
  string** — naming finalization (a future ADR superseding ADR-045)
  is the next logical step, but not in B.3.
- **New verticals become a small, predictable change**: a directory
  under `app/vertical/packs/<name>/` + a migration that seeds rows.

---

## 12. Pre-flight items for Andrew (between now and `proceed B.3.1`)

- [ ] Confirm the 14 decisions in §2 (or override any).
- [ ] Confirm sub-task ordering in §9 (or rebundle).
- [ ] Confirm OUT-OF-SCOPE list in §10 (especially Sara deferral +
      no-frontend-auth-UI).
- [ ] Operator-side: nothing required for B.3.0 itself. B.3.3 will
      need `alembic upgrade head` against docker-compose Postgres
      before staging deploy.

---

## 13. Sign-off / next gate

| Action | Requires |
|---|---|
| Commit this plan + ADRs + LOCK v1.6 | (this commit — B.3.0) |
| Push | `push B.3.0` |
| Begin B.3.1 (vertical pack skeleton) | `proceed B.3.1` |
| Override any decision in §2 or §9 | reply with override + revised `proceed B.3.0-amend` |

No auto-proceed beyond this planning commit.
