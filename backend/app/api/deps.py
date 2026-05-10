"""HTTP transport dependencies — cookie helpers + `get_current_user`.

Per docs/phase-b2-plan.md §6 (cookie design) + §4 (consume / me flows).
Pure transport-layer concerns: signing the session-id cookie, parsing
+ verifying it on subsequent requests, and resolving the cookie back
to a `User` via the database.

The cookie value format is `f"{session_id}.{signature}"` where
signature is a hex-encoded HMAC-SHA256 of the session-id bytes using
`Settings.session_secret`. The session row in the DB is the source of
truth — the cookie is a bearer that points to it.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import User, UserSession
from app.db.repositories.session_repo import SessionRepository
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session

SESSION_COOKIE_NAME = "trufindai_session"


# --- Cookie signing


def _sign_session_id(session_id: UUID, secret: str) -> str:
    """Build the signed cookie value for a session_id.

    Format: `f"{session_id}.{hex_hmac_sha256(secret, session_id.bytes)}"`.
    Deterministic for the same (session_id, secret) pair.
    """
    sig = hmac.new(
        secret.encode("utf-8"), session_id.bytes, hashlib.sha256
    ).hexdigest()
    return f"{session_id}.{sig}"


def _verify_session_cookie(cookie_value: str, secret: str) -> UUID | None:
    """Parse + verify a signed cookie value. Returns the session_id on
    success, None on any failure (malformed, bad UUID, signature mismatch).

    Constant-time signature comparison via `hmac.compare_digest` to
    avoid timing oracles.
    """
    if not cookie_value or "." not in cookie_value:
        return None
    sid_str, sig = cookie_value.rsplit(".", 1)
    try:
        sid = UUID(sid_str)
    except (ValueError, AttributeError):
        return None
    expected_sig = hmac.new(
        secret.encode("utf-8"), sid.bytes, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    return sid


# --- Cookie set / clear


def _is_secure_env(settings: Settings) -> bool:
    """Per phase-b2-plan.md §6: Secure=True in staging/prod, False in dev."""
    return settings.app_env in ("staging", "production")


def set_session_cookie(
    response: Response, session: UserSession, settings: Settings
) -> None:
    """Write the signed session cookie onto `response`.

    Max-Age = (session.expires_at - now()) in seconds, clamped >= 0.
    HttpOnly always; Secure only in staging/prod; SameSite=Lax; Path=/.
    """
    assert settings.session_secret is not None  # validator guarantees
    now = datetime.now(timezone.utc)
    max_age = max(int((session.expires_at - now).total_seconds()), 0)
    cookie_value = _sign_session_id(session.id, settings.session_secret)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=_is_secure_env(settings),
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Clear the session cookie. Attribute set must match `set_session_cookie`
    so the browser deletes the right entry."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_secure_env(settings),
    )


# --- get_current_user dependency


async def get_current_user(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """FastAPI dependency: resolve the cookie to an authenticated `User`.

    Raises HTTPException(401) on every failure mode (no cookie, bad
    signature, unknown session, revoked session, expired session,
    deleted user). The reason is logged via the global exception
    handler chain but not surfaced to the caller — same opaque 401 in
    all cases (ADR-018 / phase-b2-plan.md §4).
    """
    settings = get_settings()
    assert settings.session_secret is not None  # validator guarantees

    cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_val:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_id = _verify_session_cookie(cookie_val, settings.session_secret)
    if session_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # System-context lookup (we don't yet know account_id) via the
    # documented force_cross_account escape hatch on BaseRepository.
    session_repo = SessionRepository(db_session, account_id=None)
    user_session = await session_repo.find_one(
        force_cross_account=True, id=session_id
    )
    if user_session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if user_session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if user_session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Now we know the account_id; tenancy filter applies on user lookup.
    user_repo = UserRepository(
        db_session, account_id=user_session.account_id
    )
    user = await user_repo.get(user_session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user
