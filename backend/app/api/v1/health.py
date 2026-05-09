"""Health endpoint (versioned).

Replaces the unversioned `/health` from pre-A.5. New canonical path is
`/v1/health`. Railway health checks point here once A.11 provisions services.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe. Returns 200 with a constant body."""
    return {"status": "ok"}
