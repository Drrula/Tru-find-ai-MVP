"""Legacy analyses endpoint (versioned alias).

Mirrors the pre-A.5 `POST /analyze-business`. The new canonical path is
`POST /v1/analyses-legacy`; the old path remains as a back-compat alias
in `main.py` (per ADR-005, preserved through at least Phase B).

The async-with-poll `POST /v1/analyses` (per ADR-005) lands in Phase C
alongside worker-based scoring. Until then this synchronous handler is
the only analysis endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.scoring import analyze
from app.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


def run_analysis(payload: AnalyzeRequest) -> AnalyzeResponse:
    """Pure handler. Reusable by the back-compat alias in `main.py`."""
    return analyze(payload.business_name, payload.location, payload.trade)


@router.post("/analyses-legacy", response_model=AnalyzeResponse, tags=["analyses"])
def analyses_legacy(payload: AnalyzeRequest) -> AnalyzeResponse:
    return run_analysis(payload)
