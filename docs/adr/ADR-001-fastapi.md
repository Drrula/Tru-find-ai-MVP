# ADR-001 — FastAPI as the API framework

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Foundation |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
Use FastAPI for the HTTP layer.

## Why
Already in use; Pydantic-native typing matches the schema-first approach; ASGI absorbs slow LLM calls without thread-pool gymnastics; OpenAPI generation is free and feeds frontend types. With one engineer, switching frameworks costs weeks and buys nothing.

## Tradeoffs
- Less prescriptive than Django/Rails: no built-in admin, ORM, or auth.
- We assemble those ourselves (SQLAlchemy, Alembic, magic-link auth).

## Future limitations
- Async-only handlers force thread-pool wrappers around blocking SDKs.
- No batteries-included server-side rendering or admin tooling.

## Migration cost if revisited
Low-to-medium. Routers are thin transport (ADR-007), so swapping to Litestar or a Go service later is plumbing. Migrating *off* Pydantic would touch every domain boundary.

## Scaling implications
ASGI under Uvicorn/Gunicorn scales horizontally; Railway runs multiple replicas. Throughput bound by event-loop latency, not the framework.

## Operational complexity
Low. One process model, one logging story, OpenAPI as a CI artifact.

## Constraints this ADR imposes
- Routers stay thin; all business logic lives in `domain/*` (ADR-007).
- Pydantic models define the API contract (`shared/schemas/`).

## See also
- ARCHITECTURE-LOCK §4
- ADR-005 (async-with-poll API)
- ADR-007 (monorepo, domain-oriented layout)
