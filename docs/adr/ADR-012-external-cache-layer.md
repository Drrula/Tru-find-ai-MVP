# ADR-012 — `external_cache` as a layer outside clients

| Field | Value |
|---|---|
| Status | Locked-default |
| Class | Data |
| Date locked | 2026-05-08 |
| Blocking ADR (per ADR-034) | No |
| Supersedes | none |
| Superseded by | none |

## Decision
A single `external_cache(provider, key_hash, payload, fetched_at, ttl_at, hit_count)` table plus a thin Redis hot tier. Clients don't cache themselves; a `Cached(client)` wrapper does. Cache key hashes include every input that affects the response (query, locale, API version, field mask).

## Why
Caching inside a client conflates "make the request" with "decide whether to make the request." TTL changes, invalidation, cost accounting, and force-refresh flows then need surgery on the client. Pulling caching out makes each concern testable in isolation and lets verification (ARCHITECTURE-LOCK §3.4) bypass cache without a flag in the client.

## Tradeoffs
- One extra layer of indirection per call.
- Cache key design becomes a decision (omitting an input is a silent correctness bug).

## Future limitations
- Per-tenant cache requires `account_id` in the key.
- Probabilistic cache (negative cache + jitter) requires extending the wrapper.

## Migration cost if revisited
Adding a cache layer to a codebase that has caches inside clients is a multi-week refactor. Doing it now is a single module.

## Scaling implications
Cuts external API spend by 50–95% on hot keys. Postgres carries the cache cost — far cheaper than re-hitting Places at $17/1000 lookups.

## Operational complexity
Medium. Monitor cache hit rate, TTL appropriateness, stale-data complaints.

## Constraints this ADR imposes
- All external HTTP wrapped: `Cached(GooglePlacesClient(...))`.
- `external_cache.key_hash = sha256(serialized_inputs)`.
- Verification path passes `cache_bypass=true` to wrapper, not to client.

## See also
- ARCHITECTURE-LOCK §3.3, §3.4
- ADR-003 (Redis hot tier)
