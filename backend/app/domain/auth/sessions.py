"""Session revoke (logout) — domain layer (per docs/phase-b2-plan.md §4).

Thin wrapper over `SessionRepository.revoke` that adds an audit event
emission. The routes layer (B.2.4) calls this from `POST /v1/auth/logout`
with the authenticated user's actor identity.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.core.events import publish_event
from app.db.repositories.session_repo import SessionRepository

# What `actor_kind` may be for a session-revoke event. The auth event
# definition (events.py) constrains this set.
RevokeActorKind = Literal["user", "system"]


async def revoke_session(
    *,
    session_id: UUID,
    session_repo: SessionRepository,
    actor_kind: RevokeActorKind = "system",
    actor_user_id: UUID | None = None,
) -> bool:
    """Revoke a session by id. Returns True if a row was actually revoked
    (False is the idempotent no-op for an already-revoked session).

    Caller must construct `session_repo` with the session-owner's
    `account_id` so the tenancy WHERE clause restricts revocation to
    sessions the user owns. The routes layer reads the account_id off
    the authenticated user (per B.2.4 — `get_current_user` dependency).

    `actor_kind="user"` is the typical value (user clicks logout).
    `actor_kind="system"` is the placeholder for admin or scheduled
    revocations until admin RBAC lands (decision #13 — deferred).
    """
    revoked = await session_repo.revoke(session_id)
    if revoked:
        publish_event(
            "auth.session.revoked",
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            target_kind="session",
            target_id=session_id,
        )
    return revoked
