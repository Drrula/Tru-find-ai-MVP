"""Legacy analyses endpoint (versioned alias).

Mirrors the pre-A.5 `POST /analyze-business`. The new canonical path is
`POST /v1/analyses-legacy`; the old path remains as a back-compat alias
in `main.py` (per ADR-005, preserved through at least Phase B).

The async-with-poll `POST /v1/analyses` (per ADR-005) lands in Phase C
alongside worker-based scoring. Until then this synchronous handler is
the only analysis endpoint.

B.6B.3 wiring (2026-05-12): the handler stays sync + the response
shape stays byte-identical, but it now schedules a post-response
shadow persistence task via FastAPI BackgroundTasks. Per
docs/phase-b6b-plan.md §4.6: the shadow task is gated by the
`b6b_shadow_scoring_enabled` flag (default OFF in every environment);
when OFF it returns from a single bool check; when ON it persists
the canonical-stack rows via the B.6A.4 orchestrator. The HTTP
response is delivered BEFORE the shadow task runs, so shadow
execution can never affect the response.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from app.domain.bridge_shadow import run_shadow_persist_if_enabled
from app.domain.scoring import analyze
from app.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


def run_analysis(payload: AnalyzeRequest) -> AnalyzeResponse:
    """Pure handler. Reusable by the back-compat alias in `main.py`."""
    return analyze(payload.business_name, payload.location, payload.trade)


def _schedule_shadow(
    background_tasks: BackgroundTasks, payload: AnalyzeRequest
) -> None:
    """Queue the post-response shadow persistence task. Idempotent
    helper shared with the `/analyze-business` back-compat alias
    in `main.py`. The task itself is flag-gated; scheduling is
    unconditional so the flag check happens inside the shadow
    function (preserves invariant §6.5: scheduling is cheap; the
    task body is a single bool-check when flag is OFF)."""
    background_tasks.add_task(
        run_shadow_persist_if_enabled,
        business_name=payload.business_name,
        location=payload.location,
        trade=payload.trade,
    )


@router.post("/analyses-legacy", response_model=AnalyzeResponse, tags=["analyses"])
def analyses_legacy(
    payload: AnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> AnalyzeResponse:
    response = run_analysis(payload)
    _schedule_shadow(background_tasks, payload)
    return response
