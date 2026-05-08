# ADR-007 — Monorepo, domain-oriented layout

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
One repo: `backend/`, `frontend/`, `infra/`, `shared/`, `docs/`. Within `backend/app/`, organize by domain (`identity`, `scoring`, `signals`, `payments`, `notifications`, `imports`, `verticals`, `ai`), not by layer.

## Why
Domain-oriented layout localizes change: adding a new signal touches one folder. Layered (controllers/services/models) forces grep across the repo for every feature. A monorepo lets the frontend consume backend-generated types and lets one PR atomically ship a backend + frontend change.

## Tradeoffs
- Domain-oriented is harder for newcomers used to Django-style.
- CI gets slightly more complex (frontend/backend test paths).
- Monorepo grows a deploy pipeline that distinguishes "what changed."

## Future limitations
- Splitting into microservices means peeling off a domain folder — natural seam, much easier than peeling a "service" out of `services/`.
- Polyglot frontends (mobile, partner SDK) fit fine.

## Migration cost if revisited
From this layout to microservices: medium, by design. From layered to domain-oriented (the alternative): high, requires moving every file.

## Scaling implications
Codebase scales to ~50k LOC before feeling cramped, well beyond Phase 2.

## Operational complexity
One repo, one CI pipeline, one issue tracker. The simplest organization that survives growth.

## Constraints this ADR imposes
- Routers do no business logic.
- Each `domain/<X>` exposes `public.py`; everything else under it is internal.
- Inter-domain communication via audit-event reads or separately-enqueued jobs, never internal imports.
- Forbidden import edges enforced in CI (see ARCHITECTURE-LOCK §4.2).

## See also
- ARCHITECTURE-LOCK §4
- ADR-031 (repository pattern)
- CONTRIBUTING.md
