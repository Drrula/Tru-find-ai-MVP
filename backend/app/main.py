"""FastAPI factory: configures cross-cutting infrastructure then registers routes.

Per ADR-007 (routers thin), ADR-017 (path-based versioning), ADR-030
(logging / request_id / Sentry stub), ADR-044 (event envelope wired in B.0.2).
The `/analyze-business` legacy alias is preserved through at least Phase B
per ADR-005. OpenAPI lives under `/v1/*` to keep the documented surface
versioned alongside the routes.

B.3.4 adds a FastAPI lifespan event that pre-loads vertical packs from
the `vertical_*` tables into a process-global cache (per ADR-048
lifecycle stage "DB-runtime"). DB-load failures are tolerated — the
cache stays empty for the affected pack and `app.vertical.db_pack.
get_active_pack` falls back to the source-module pack via the registry.
This keeps the scoring path SYNC end-to-end while making ADR-011
actually true on production traffic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.v1 import api_router
from app.api.v1.analyses_legacy import run_analysis
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.events import publish_event
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.core.observability import init_sentry
from app.db.session import _get_sessionmaker
from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.vertical import load_default_packs
from app.vertical.db_pack import clear_pack_cache, populate_pack_cache


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: pre-load vertical packs from DB into the cache.
    Shutdown: clear the cache.

    DB-load failures are tolerated and logged — the cache stays empty
    for the affected pack and `get_active_pack` falls back to the
    source-module pack. This lets tests + fresh deployments operate
    without DB-seeded rows; production deploys get the DB-backed pack
    once the seed utility has run.
    """
    log = get_logger("app.main.lifespan")
    try:
        sessionmaker = _get_sessionmaker()
        async with sessionmaker() as session:
            await populate_pack_cache(session)
    except Exception:
        log.warning("lifespan_vertical_pack_load_failed", exc_info=True)
    yield
    clear_pack_cache()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level)
    init_sentry(dsn=settings.sentry_dsn, env=settings.app_env)

    # Register canonical vertical packs (per ADR-048). Each pack's
    # module __init__ side-effect-registers it with the registry; this
    # call ensures the canonical packs are loaded before any request
    # routes through the scoring engine.
    load_default_packs()

    app = FastAPI(
        title="AI Visibility Scoring",
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        lifespan=_lifespan,
    )
    register_middleware(app, settings)
    register_error_handlers(app)

    app.include_router(api_router)

    # Back-compat alias for the pre-A.5 batch script and frontend.
    # Per ADR-005, removed no earlier than Phase B. `include_in_schema=False`
    # keeps it out of OpenAPI; clients should migrate to `/v1/analyses-legacy`
    # (or, when Phase C lands, `/v1/analyses`).
    @app.post(
        "/analyze-business",
        response_model=AnalyzeResponse,
        include_in_schema=False,
    )
    def analyze_business_legacy(payload: AnalyzeRequest) -> AnalyzeResponse:
        return run_analysis(payload)

    log = get_logger("app.main")
    log.info("app_initialized", env=settings.app_env)

    # First production emit: proves end-to-end flow per ADR-044 (B.0.3).
    publish_event(
        "system.app.started",
        payload={"env": settings.app_env, "version": app.version},
        actor_kind="system",
    )

    return app


app = create_app()
