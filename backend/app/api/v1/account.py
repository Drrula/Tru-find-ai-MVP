"""Account-scoped endpoints (per ADR-047 customer-data-ownership commitment).

B.3.7 lands the `POST /v1/account/export` endpoint as a 501 stub
with a documented response schema. The URL surface + response shape
are LOCKED here so the ADR-047 right-to-export commitment becomes
load-bearing in code, not just in docs. Implementation is deferred
to a future phase that the platform will need before the first
enterprise customer onboards.

Auth-gated via `Depends(get_current_user)`. Unauthenticated requests
return 401 from the dependency without ever reaching this handler.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.db.models import User

router = APIRouter(prefix="/account", tags=["account"])


# --- Response schema (locks the eventual export shape)


class _ExportErrorEnvelope(BaseModel):
    """Matches the platform-wide ADR-030 error envelope shape so
    callers can branch on the same `error.code` they branch on for
    every other error."""

    code: str = "not_implemented"
    message: str = (
        "Account export is committed but not yet implemented; "
        "the response schema below is stable."
    )
    request_id: str | None = None


class _ExportContentsSchema(BaseModel):
    """Sketch of what the future implementation will include.

    Each field is a human-readable description of the data shape
    that will land at the corresponding key once the export
    implementation lands. Per ADR-047 + plan §10, customer-owned
    tables are exportable; platform-owned (`vertical_*`,
    `signal_definition`, prompts, audit log, blocklist intelligence)
    are NOT and do not appear here.
    """

    account: str = Field(
        default=(
            "single account row: id, display_name, region, status, "
            "created_at, updated_at"
        )
    )
    users: str = Field(
        default="all users associated with this account"
    )
    businesses: str = Field(
        default=(
            "businesses owned by this account (lands when business "
            "persistence ships in a later phase)"
        )
    )
    leads: str = Field(
        default=(
            "leads owned by this account (lands when lead "
            "persistence ships in a later phase)"
        )
    )
    purchases: str = Field(
        default=(
            "billing records for this account (lands when billing "
            "persistence ships in a later phase)"
        )
    )
    opt_outs: str = Field(
        default=(
            "opt-out records scoped to this account (account-scoped "
            "slice only; global blocklist intelligence stays platform-owned)"
        )
    )


class ExportNotImplementedResponse(BaseModel):
    """Response body for the 501 stub. Both surfaces are stable:
    consumers can branch on `error.code == 'not_implemented'` AND
    inspect `contents_when_implemented` to know what to expect when
    the endpoint lights up."""

    error: _ExportErrorEnvelope
    schema_version: int = 1
    contents_when_implemented: _ExportContentsSchema


# --- Route


@router.post(
    "/export",
    response_model=ExportNotImplementedResponse,
    status_code=501,
)
async def export_account(
    user: Annotated[User, Depends(get_current_user)],
    request: Request,
) -> ExportNotImplementedResponse:
    """Initiate an account-scoped data export.

    **Status: 501 Not Implemented** (per ADR-047 — the URL surface +
    response schema are locked; the implementation is a future
    phase). Authenticated callers receive the stable contents
    sketch; unauthenticated callers receive 401 from
    `get_current_user`.
    """
    request_id = getattr(request.state, "request_id", None)
    return ExportNotImplementedResponse(
        error=_ExportErrorEnvelope(
            request_id=str(request_id) if request_id else None,
        ),
        contents_when_implemented=_ExportContentsSchema(),
    )
