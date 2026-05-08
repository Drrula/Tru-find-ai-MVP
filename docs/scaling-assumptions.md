# Scaling Assumptions

Where the architecture is designed to scale, and where it is not. Listing the inflection points so we know in advance what will need to change before we hit them.

## Headline

The architecture is designed to scale comfortably to roughly **10,000 analyses/day**, **50–100 concurrent users**, **a handful of verticals**, and **single-region operation**. Beyond those points, specific components need rework — listed below.

This is plenty of headroom for Phase 2 and most of Phase 3. The assumptions below describe what changes when each ceiling is approached, not when they break.

## A. API tier

**Designed for.** Stateless FastAPI behind Railway's edge, multiple replicas. Async-with-poll contract (ADR-005) keeps requests short.

**Scales to.** 100s of req/s per replica; horizontal scaling adds replicas linearly. Bottleneck is Postgres connections, not Python.

**First inflection.** ~1000 req/s sustained: introduce PgBouncer between API replicas and Postgres to keep connection count bounded.

**Second inflection.** Multi-region read serving: requires Postgres read replicas + region-aware routing. Not feasible without splitting writes.

**Will need rework.** Real-time features (server-pushed updates) — currently not designed for. Will require a sticky pub/sub layer or a separate WebSocket service.

## B. Worker tier

**Designed for.** `arq` workers (ADR-004) scaled per queue. Each queue scales independently.

**Scales to.** Tens of thousands of jobs/hour per queue with low concurrency. Higher with tuned concurrency.

**First inflection.** ~10k jobs/hour per queue: split queue into two by job class (e.g. fast signals vs slow LLM) so head-of-line blocking doesn't stall fast work.

**Second inflection.** DAG-style workflows (job A fan-out → join → job B chain): arq doesn't model this natively. Consider Temporal or Inngest if Phase 3 introduces multi-step verification chains.

**Will need rework.** Long-running jobs (>15 min). Currently capped at worker timeout. Required if verification eventually involves human-in-the-loop or batch LLM calls.

## C. Postgres

**Designed for.** Single Postgres instance on Railway. UUIDv7 keys (ADR-033) keep B-tree inserts sequential. Repository pattern (ADR-031) keeps query shape predictable.

**Scales to.** ~10k analyses/day comfortably; 100k/day with index tuning.

**First inflection.** Largest table reaches ~10M rows (likely `signal_result` or `external_cache`): partition by month or by `account_id`. Partition keys are already in place (`account_id` on every derived table; `created_at` on every row).

**Second inflection.** Read pressure for analytics: introduce a read replica; route analytics-style queries (e.g. "score distribution by vertical") to replica.

**Third inflection.** Write throughput ceiling on a single primary: this is years out at projected volumes. When approached, options are (a) per-tenant sharding (fits naturally because of `account_id` everywhere), (b) split read-heavy domains into separate Postgres instances (`audit_log`, `external_cache`, `job_run` are independent candidates).

**Will need rework.**
- Cross-region writes — requires architectural change (active-active or per-region tenancy).
- Vector search (semantic similarity over business descriptions) — Postgres `pgvector` for first 100k vectors; dedicated store (Qdrant, Pinecone) beyond.
- Full-text search — `pg_trgm` for first iteration; Meilisearch/Typesense if relevance demands tuning.

## D. Redis

**Designed for.** Job queue + rate limit + hot cache. In-memory.

**Scales to.** Tens of thousands of ops/sec on a single instance.

**First inflection.** Memory pressure: prune cache entries more aggressively (lower TTLs in Redis hot tier; rely on Postgres `external_cache`).

**Second inflection.** Throughput pressure: vertical-scale Redis to a larger instance.

**Will need rework.** Sharding Redis is non-trivial; we will hit Postgres limits first. If Redis becomes the bottleneck, the answer is usually "stop using Redis for that thing" (move durable queue to Postgres-as-queue or SQS).

## E. External APIs

**Designed for.** `Cached(client)` wrapper (ADR-012) absorbs repeated lookups. `external_cache` TTLs tuned per provider.

**Scales to.** Bounded by upstream quota.

**Inflection points by provider:**
- **Google Places.** Quota in $/day. Cache TTL 24h on `place_id` lookups, 7d on details. Expect $X/1000 lookups; budget gates the throughput.
- **LLM (Anthropic).** Per-account rate limit + per-run cost cap (ADR-022). Watch p99 latency; if Anthropic latency degrades, Sonnet → Haiku fallback per probe class.
- **Stripe.** Webhook delivery has its own retry. Reconciliation job catches drops.
- **Twilio.** Rate-limited by 10DLC tier. Higher trust scores unlock higher TPS (ADR-025).

**Will need rework.**
- Multi-provider LLM (Anthropic + OpenAI fallback) — currently single-provider. Adapter exists (`clients/llm.py`) but provider switch is currently a config change, not a runtime fallback.
- Multi-region for Places — Google quota is global; not an issue.

## F. AI cost

**Designed for.** Per-run cost cap (ADR-022) bounds blast radius. Cost recorded per probe (`ai_probe`).

**Scales to.** Linearly with run volume × per-run cost.

**Inflection points:**
- Per-run cost > $1: re-tune prompts, downgrade model, increase cache TTL.
- Daily AI spend > $X (configurable): trigger alert; consider per-account caps.

**Will need rework.** Cost-gated free tier. Currently the cost cap is per-run, not per-account. A free tier requires a per-account cumulative cap (extension of ADR-022).

## G. Frontend

**Designed for.** Vite + React SPA, single page-load + dynamic data fetches.

**Scales to.** Static assets served from Railway edge; arbitrary client count.

**Inflection points.**
- Bundle size > 500KB gzip: code-split routes (router introduced in Phase B).
- SEO requirements: SPA → SSR migration is a project (Next.js or Remix), not a tweak.

**Will need rework.** Mobile app — current architecture supports it (clean API surface), but no mobile client exists.

## H. Tenancy

**Designed for.** Single-tenant-per-account, with `parent_account_id` for future agency/white-label.

**Scales to.** Thousands of accounts.

**Inflection point.** Per-account customization beyond config (e.g. custom signal sets, custom branding) — Phase 3 design.

**Will need rework.** True multi-tenancy with isolated data planes per major customer (enterprise tier) — would shift to per-tenant Postgres schemas or per-tenant databases. Current design accommodates this with `account_id` everywhere; it's not free, but it's not a rewrite.

## I. Verticals

**Designed for.** A handful (5–15) of verticals, configured via `vertical_*` tables (ADR-011).

**Scales to.** Dozens, with the same data-driven model.

**Inflection point.** Hundreds of verticals: prompt/copy administration becomes a real product surface (admin UI, approval workflow, A/B testing). Outstanding decision §5.4 deferred until then.

**Will need rework.** Vertical taxonomy that has hierarchy (industries → sub-industries → micro-niches) — currently flat. Hierarchical lookup is a schema change but not a rewrite.

## J. Compliance

**Designed for.** US-only, CCPA-aware, no PHI, opt-out-respecting.

**Scales to.** US-only operations indefinitely.

**Inflection point.** International expansion — GDPR (EU), PIPEDA (Canada), country-specific SMS/voice regs. Each is a real project.

**Will need rework.**
- Data residency. Currently single-region; multi-region with data residency rules requires architectural change.
- Right-to-erasure tooling. Phase B's GDPR-erase routine is a separate path; will be exercised before launch.
- Audit-log immutability. `audit_log` table is append-only by convention; true immutability (object-locked S3 export) is a Phase 3 task.

## Summary table

| Layer | Headroom | First rework | Far horizon |
|---|---|---|---|
| API | 100s req/s/replica | PgBouncer at ~1000 req/s | Multi-region serving |
| Workers | 10k jobs/hour/queue | Split queue by class | DAG runtime (Temporal) |
| Postgres | 10k–100k analyses/day | Partition large tables | Sharding by account_id |
| Redis | 10k ops/sec | Vertical scale + lower TTLs | Replace, don't shard |
| External APIs | Provider quota | Multi-provider LLM fallback | Region-aware routing |
| AI cost | Per-run cap | Per-account cap | Free-tier daily cap |
| Frontend | Single bundle | Code-split routes | SSR if SEO needed |
| Tenancy | Thousands of accounts | Per-account customization | Per-tenant data plane |
| Verticals | 5–15 | Admin UI at >15 | Hierarchical taxonomy |
| Compliance | US only | International expansion | Audit-log immutability |

The pattern: every layer scales by an order of magnitude beyond Phase 2 needs, and each rework point is well-understood with a clear path. Nothing in this architecture has a hidden ceiling that requires throwing it away.
