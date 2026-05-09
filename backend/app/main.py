"""FastAPI factory: configures cross-cutting infrastructure then registers routes.

Per ADR-007 (routers thin), ADR-030 (logging / request_id / Sentry stub).
The /analyze-business legacy alias is preserved through Phase B per ADR-005.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.events import publish_event
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.core.observability import init_sentry
from app.domain.scoring import analyze
from app.schemas import AnalyzeRequest, AnalyzeResponse


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level)
    init_sentry(dsn=settings.sentry_dsn, env=settings.app_env)

    app = FastAPI(title="AI Visibility Scoring MVP", version="0.1.0")
    register_middleware(app, settings)
    register_error_handlers(app)

    log = get_logger("app.main")
    log.info("app_initialized", env=settings.app_env)

    # First production emit: proves end-to-end flow per ADR-044 (B.0.3).
    publish_event(
        "system.app.started",
        payload={"env": settings.app_env, "version": app.version},
        actor_kind="system",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/analyze-business", response_model=AnalyzeResponse)
    def analyze_business(payload: AnalyzeRequest) -> AnalyzeResponse:
        return analyze(payload.business_name, payload.location, payload.trade)

    return app


app = create_app()
