# ADR-048 — Vertical pack lifecycle

| Field | Value |
|---|---|
| Status | **Locked** |
| Class | Canonical entities · Irreversible schema · Operations |
| Date locked | 2026-05-10 |
| Blocking ADR (per ADR-034) | Yes |
| Supersedes | none — operationalizes ADR-011 |
| Superseded by | none |

## Decision

ADR-011 ("Verticals are data, not code") locks the principle.
ADR-048 locks the operational mechanics: how packs are organized
in source, registered at runtime, seeded into the DB, and read by
the scoring engine.

### Source layout

```
backend/app/vertical/
  __init__.py
  pack.py              # VerticalPack Protocol
  registry.py          # register / lookup; mirrors app/core/event_registry.py
  packs/
    __init__.py
    local_business_ai_visibility/
      __init__.py      # side-effect registration on import
      weights.py       # signal_name -> weight (seed values for vertical_signal_weight)
      copy.py          # (locale, key) -> string  (seed values for vertical_copy)
      competitors.py   # competitor_pool seed
      tiers.py         # score tier thresholds + advice strings
      categories.py    # signal_name -> presentation category mapping
```

The `local_business_ai_visibility` pack carries what's currently
hardcoded in `app/domain/scoring.py` + `app/domain/signals.py`. After
B.3.2 the core no longer holds this content; after B.3.4 the DB holds
it and the pack module is purely the SEED.

### VerticalPack Protocol (B.3.1)

```python
class VerticalPack(Protocol):
    """Declarative description of one vertical's configuration."""

    pack_id: str           # e.g. "local_business_ai_visibility"
    display_name: str      # human-readable; lives in vertical.display_name
    schema_version: int    # bump when seed data shape changes

    def signal_weights(self) -> dict[str, float]: ...
    def copy(self) -> dict[tuple[str, str], str]: ...  # (locale, key) -> text
    def competitor_pool(self) -> list[str]: ...
    def tier_thresholds(self) -> dict[str, tuple[int, str]]: ...
    def category_mapping(self) -> dict[str, str]: ...
```

(Final method names + signatures finalize at B.3.1 commit; this is
the indicative shape.)

### Registry

`app/vertical/registry.py` exposes `register(pack)` + `lookup(pack_id)`.
Idempotent registration (re-importing a pack module does not raise),
matching the pattern in `app/core/event_registry.py` and
`app/domain/auth/events.py`.

### Lifecycle stages

1. **Source-time** (B.3.1): pack module exists; registers on import.
   Engine reads weights/copy from the registered pack instance.
2. **Schema-time** (B.3.3): `vertical_*` tables migrate. A seed
   command writes pack rows into `vertical_*` from the registered
   pack instances. Engine still reads from the pack module —
   tables are aspirational.
3. **DB-runtime** (B.3.4): engine switches to read from
   `vertical_*` tables via the repository layer (per ADR-031). Pack
   module becomes the AUTHORITATIVE SEED for new deployments and
   for tests; production reads are from DB. ADR-011 is now actually
   true.

### Pack versioning

`schema_version` on the pack declares the seed-shape version.
`vertical.schema_version` on the row records what version was last
seeded. A mismatch between pack and row triggers a documented
re-seed operation (manual in B.3+; promotes to admin UI in Phase D+
per ADR-011's outstanding decision §5.4).

### Multi-locale support

`vertical_copy` is keyed by `(vertical_id, locale, key)`. Packs
declare a default locale (likely `'en-US'` initially); future
locales register additional entries. This is the seam that absorbs
ADR-046's "no US-only assumptions" rule on the copy surface.

## Why

ADR-011 stated the principle ("verticals are data, not code")
without specifying how packs are organized, registered, seeded, or
versioned. Without that operational shape, ADR-011 stayed paper-
only — and indeed, `app/domain/scoring.py` + `app/domain/signals.py`
currently violate ADR-011 by hardcoding weights, gap strings,
competitor pool, and category mapping in core code.

The directive's "Core engine separate from vertical configuration"
requires the SOURCE LAYOUT to physically separate these surfaces,
not just the DB layout. A pack-module-per-vertical seam (B.3.1)
gives the engine a clear interface; the DB tables (B.3.3) make the
runtime mutable without a deploy; the seed mechanism (B.3.4) lets
both coexist.

This is also where "plug-and-play by vertical" from the directive
becomes operational: a new vertical = a new directory under
`app/vertical/packs/<name>/` + a migration that seeds its rows.

## Tradeoffs

- Pack-module → DB seeding adds a synchronization concern (drift
  between source and DB). Mitigated by the schema_version check.
- Reading copy from DB on every request is slower than reading from
  a Python dict. Mitigated by in-process caching (deferred; B.3
  reads on every call until profiling justifies the cache).
- Requires every new vertical to follow the pack convention — but
  that's the directive's intent.

## Future limitations

- A truly novel vertical may need different signal SETS, not just
  different weights. `vertical_template` (per ADR-011) anticipates
  this — but B.3 does not exercise it. Same-signals-different-
  weights is the assumption.
- Editing pack data via admin UI vs. migration: outstanding decision
  per ADR-011 §5.4. Gated by Phase D.
- A/B testing pack versions per account: future. The seam exists
  (`account.vertical_id` reference) but no behavioral A/B framework
  lands in B.3.

## Migration cost if revisited

Pack source layout is cheap to refactor (it's not yet exercised by
external integrations). The DB schema (`vertical_*` tables) is
expensive to change once seeded — additive evolution per ADR-027.

## Scaling implications

Negligible — pack count is small (<100), copy table small, weights
table small. In-process caching deferred until justified.

## Operational complexity

Low: pack lives in source; seed runs at deploy / migration time.
Medium when admin UI lands (Phase D+) — pack edits via UI need
audit trail + rollback per ADR-011 (already specified).

## Constraints this ADR imposes

- Every vertical lives under `app/vertical/packs/<pack_id>/`.
- New verticals MUST register via the registry — no implicit
  discovery (matches the explicit-registration pattern of
  `app/core/event_registry.py`).
- No `if vertical_id == "..."` branches in core code (reiterates
  ADR-011).
- Pack reads happen through the registry in B.3.1–B.3.3 and through
  the DB repository in B.3.4+ — domain code never imports pack
  modules directly.
- Copy MUST be locale-keyed from the start (per ADR-046), even if
  only one locale is populated in B.3.

## See also

- Platform Directive v1 (Andrew, 2026-05-10)
- ADR-011 (verticals as data, not code — the principle this ADR
  operationalizes)
- ADR-020 (versioned prompts — analogous lifecycle for prompts
  inside packs)
- ADR-031 (repository pattern — DB reads in B.3.4 go through repos)
- ADR-040 (definition-driven event taxonomy — registry pattern
  analog)
- ADR-044 (canonical event envelope — registry pattern analog)
- ADR-046 (multi-region / data-residency — drives locale-keyed copy)
- ADR-047 (customer data ownership — packs are platform IP)
- ARCHITECTURE-LOCK §2.3 (vertical_* table shapes)
