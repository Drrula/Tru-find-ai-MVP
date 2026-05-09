"""Global exception handlers + stable error envelope.

Per ADR-030: errors return a JSON envelope, not a Python traceback.
Sentry capture is delegated to `app.core.observability.report_exception`,
which is a no-op stub until A.12.

Envelope shape:
  {
    "error": {
      "code": "<machine_readable_code>",
      "message": "<human_readable>",
      "request_id": "<uuid_or_null>"
    }
  }
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.observability import report_exception

log = structlog.get_logger("app.core.errors")


def _envelope(code: str, message: str, request_id: str | None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    """Wire global exception handlers on the FastAPI app."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.warning(
            "http_error",
            status=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code=f"http_{exc.status_code}",
                message=str(exc.detail),
                request_id=request_id,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.warning(
            "validation_error",
            path=request.url.path,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            content=_envelope(
                code="validation_error",
                message="Request validation failed.",
                request_id=request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.error(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            path=request.url.path,
            exc_info=exc,
        )
        report_exception(exc)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                code="internal_error",
                message="An internal error occurred.",
                request_id=request_id,
            ),
        )
