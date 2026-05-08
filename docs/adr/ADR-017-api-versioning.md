# ADR-017 — Path-based API versioning (`/v1/...`)

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Application |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
All API routes live under `/v1/...`. New incompatible versions get `/v2/`. Old versions are kept until usage drops below a measurable threshold and then sunset on a deprecation schedule.

## Why
Path versioning is visible in logs, OpenAPI, client code, and customer integrations. Header-based versioning is invisible until production breaks. With external consumers (the batch script today, partners later) we want the version contract obvious and individually fetchable.

## Tradeoffs
- Two versions in flight = code duplication during transitions. Mitigated by versioning at the *router* layer only; domain services are version-free.
- Slightly noisier OpenAPI surface.

## Future limitations
- API surface eventually splits into `public/v1` (stable) and `internal/v1` (frontend-coupled, can break with deploys).

## Migration cost if revisited
Adding versioning to an unversioned API is a public-contract change. Adding it now costs one path segment.

## Scaling implications
None.

## Operational complexity
Low. The discipline is "don't change `/v1` semantics" — bake breaking changes into a `/v2`.

## Constraints this ADR imposes
- All routers under `backend/app/api/v1/`.
- OpenAPI exposed at `/v1/openapi.json`.
- Health check at `/v1/health` (the only non-versioned exception is `/` and `/docs`).
- Legacy `/analyze-business` alias preserved through Phase B.

## See also
- ARCHITECTURE-LOCK §5
- ADR-005 (async-poll API contract)
