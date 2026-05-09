"""HTTP middleware: request_id minting, CORS, in-process rate limit.

Per ADR-030 (request_id), ADR-006 (stateless API), ADR-003 (Redis-backed
rate limiter is Phase C; this implementation is in-process and replaced
then).

Middleware execution order on request: CORS → RequestID → RateLimit → handler.
On response: handler → RateLimit → RequestID → CORS. Starlette wraps
middleware in reverse-add-order, so the LAST `add_middleware` call is the
OUTERMOST.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.core.ids import new_id

log = structlog.get_logger("app.core.middleware")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Mint a UUIDv7 request_id per request; expose on response and bind to log context.

    Honors an inbound `X-Request-ID` if the client supplied one (useful for
    upstream reverse proxies and trace correlation).
    """

    def __init__(self, app: Any, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        inbound = request.headers.get(self.header_name)
        request_id = inbound or str(new_id())
        request.state.request_id = request_id

        # Bind to logging context (works with structlog.contextvars.merge_contextvars).
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[self.header_name] = request_id
        return response


class TokenBucketRateLimiter(BaseHTTPMiddleware):
    """In-process per-IP sliding-window rate limiter.

    Replaced by a Redis-backed limiter in Phase C (per ADR-003). Until then,
    this is per-process and resets on restart — acceptable for Phase A.
    """

    def __init__(self, app: Any, requests_per_minute: int = 60) -> None:
        super().__init__(app)
        self.window_seconds = 60.0
        self.capacity = requests_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        hits = self._hits[client_ip]
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.capacity:
            request_id = getattr(request.state, "request_id", None)
            log.warning("rate_limited", client_ip=client_ip, hits=len(hits))
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests.",
                        "request_id": request_id,
                    }
                },
            )

        hits.append(now)
        return await call_next(request)


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Wire HTTP middleware in the right order.

    Starlette wraps middleware in reverse-add-order (last added = outermost).
    Desired request order: CORS → RequestID → RateLimit → handler. So we add
    in the reverse of that desired order.
    """
    app.add_middleware(TokenBucketRateLimiter, requests_per_minute=settings.rate_limit_per_minute)
    app.add_middleware(RequestIDMiddleware, header_name=settings.request_id_header)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[settings.request_id_header],
    )
