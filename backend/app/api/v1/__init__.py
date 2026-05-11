"""v1 API surface. Aggregates per-feature routers under the `/v1` prefix.

Per ADR-017 (path-based versioning). New routers register here; the
unversioned legacy alias for `/analyze-business` lives in `main.py` and
is `include_in_schema=False`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import account, analyses_legacy, auth, health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(analyses_legacy.router)
api_router.include_router(auth.router)
api_router.include_router(account.router)
