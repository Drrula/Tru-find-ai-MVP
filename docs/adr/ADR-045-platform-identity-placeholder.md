# ADR-045 — Platform identity placeholder (`platform_core`)

| Field | Value |
|---|---|
| Status | **Locked (placeholder until naming finalizes)** |
| Class | Operations · Naming · Governance |
| Date locked | 2026-05-10 |
| Blocking ADR (per ADR-034) | No (Locked-default) |
| Supersedes | none |
| Superseded by | a future naming ADR (slot reserved; explicitly empty) |

## Decision

The platform's permanent name is undecided. Until a future ADR
supersedes:

- The shared core is referred to internally as **`platform_core`** —
  in ADR text, in code identifiers, in module names, in settings
  keys, in telemetry tags.
- **TruFindAI** is the current deployed vertical/brand layer, NOT
  the permanent platform identity. Treat as (a) a vertical pack
  loaded by the platform, and (b) a deployment-specific brand string
  for user-facing surfaces.
- New shared-core code MUST NOT introduce hardcoded `"TruFindAI"`
  references. Existing references in core (READMEs, frontend titles,
  email subject lines, telemetry tags, package name) are leaks
  tagged for B.3.6 cleanup; they do not violate this ADR
  retroactively but block any new additions.

## Why

The platform must remain flexible for multi-vertical, white-label,
international, and enterprise deployments (per the Platform
Directive v1, 2026-05-10). Picking a candidate name now and
architecting around it has the same lock-in cost as picking the
final name — a rename across CI/CD, package names, telemetry tags,
secrets prefixes, OpenAPI titles, and external integrations has
high blast radius. Deferring until product / market / partner
direction settles is cheaper than committing prematurely.

## Tradeoffs

- Some friction reading code/docs that use a placeholder name.
- Future naming ADR triggers a rename pass — but rename scope is
  bounded because `platform_core` only appears in core, never in
  vertical packs or in operator-facing branding surfaces.

## Future limitations

- The placeholder must be replaced before any user-facing surface
  (onboarding email branding from the platform itself, public
  partner-facing docs) uses it.
- Internal identifiers (settings keys, telemetry tags) MAY outlive
  the placeholder if the eventual rename is purely mechanical.

## Migration cost if revisited

Mechanical search-and-replace once the naming ADR lands. Discipline
now (keep `platform_core` out of operationally-coupled places like
secret-manager prefixes) keeps that future scope tight.

## Scaling implications

None.

## Operational complexity

Low. CI / IaC / telemetry continue to use the existing
`trufindai-backend` package identifier and operational labels until
the naming ADR addresses operational rename explicitly. The
internal placeholder is for new code + new docs + new ADRs only.

## Constraints this ADR imposes

- **In core:** identifiers, module names, ADR cross-references,
  internal docs, telemetry tags introduced in B.3+ use
  `platform_core` (or similarly neutral terms — never a marketing
  name).
- **In vertical packs:** `TruFindAI` is a correct + expected
  identifier inside `app/vertical/packs/trufindai_*` (when that pack
  lands per ADR-048).
- **In operator-facing surfaces (email subject lines, frontend
  titles, marketing copy):** `TruFindAI` is correct as the deployed
  brand string and MUST live in `vertical_copy` rows, not in core
  source files.

## See also

- Platform Directive v1 (Andrew, 2026-05-10)
- ARCHITECTURE-LOCK §2 (uses `platform_core` from v1.6)
- ADR-048 (vertical pack lifecycle — defines how the TruFindAI pack
  lives alongside the placeholder)
