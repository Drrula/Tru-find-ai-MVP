"""Auth domain layer (per docs/phase-b2-plan.md §4 + §9).

Pure domain logic: no FastAPI imports, no HTTP concerns. Routes
(B.2.4) wire these functions to HTTP and own cookie / signature
handling. Functions take their repository + sender dependencies as
keyword arguments so behavior tests can inject mocks.

Importing this package triggers registration of the `auth.*` event
types via `app.domain.auth.events` (side-effect import).
"""

from __future__ import annotations

from app.domain.auth import events  # noqa: F401 — side-effect: registers event types
from app.domain.auth.consume import (
    ConsumeResult,
    MagicLinkRejected,
    consume_magic_link,
)
from app.domain.auth.issue import issue_magic_link
from app.domain.auth.sessions import revoke_session

__all__ = [
    "ConsumeResult",
    "MagicLinkRejected",
    "consume_magic_link",
    "issue_magic_link",
    "revoke_session",
]
