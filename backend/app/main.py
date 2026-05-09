"""FastAPI factory: configures cross-cutting infrastructure then registers routes.

Per ADR-007 (routers thin), ADR-017 (path-based versioning), ADR-030
(logging / request_id / Sentry stub), ADR-044 (event envelope wired in B.0.2).
The `/analyze-business` legacy alias is preserved through at least Phase B
per ADR-005. OpenAPI lives under `/v1/*` to keep the documented surface
versioned alongside the routes.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import api_router
from app.api.v1.analyses_legacy import run_analysis
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.events import publish_event
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.core.observability import init_sentry
from app.schemas import AnalyzeRequest, AnalyzeResponse


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level)
    init_sentry(dsn=settings.sentry_dsn, env=settings.app_env)

    app = FastAPI(
        title="AI Visibility Scoring",
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
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
