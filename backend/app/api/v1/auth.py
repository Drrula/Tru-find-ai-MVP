"""Auth routes — `/v1/auth/{request,consume,logout,me}`.

Per docs/phase-b2-plan.md §4 + §9. Thin HTTP transport on top of the
B.2.3 domain layer (`app.domain.auth`). Routes:
  - POST /v1/auth/request — issue a magic link; always 200 (decision #7).
  - GET  /v1/auth/consume — consume a magic-link token; sets cookie
                             on success; 401 on rejection (opaque).
  - POST /v1/auth/logout  — revoke session + clear cookie; always 200.
  - GET  /v1/auth/me      — return current user; 401 if unauthenticated.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SESSION_COOKIE_NAME,
    _verify_session_cookie,
    clear_session_cookie,
    get_current_user,
    set_session_cookie,
)
from app.core.config import get_settings
from app.db.models import User
from app.db.repositories.account_repo import AccountRepository
from app.db.repositories.magic_link_token_repo import MagicLinkTokenRepository
from app.db.repositories.session_repo import SessionRepository
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session
from app.domain.auth import (
    MagicLinkRejected,
    consume_magic_link,
    issue_magic_link,
    revoke_session,
)
from app.domain.notifications.email import EmailSender, LoggingEmailSender

router = APIRouter(prefix="/auth", tags=["auth"])

log = structlog.get_logger("app.api.v1.auth")


# --- Request / response schemas


class AuthRequestBody(BaseModel):
    email: EmailStr


class AuthRequestResponse(BaseModel):
    status: str = "ok"


class ConsumeResponse(BaseModel):
    user_id: str
    account_id: str
    is_new_signup: bool


class MeResponse(BaseModel):
    user_id: str
    account_id: str
    role: str
    display_name: str | None


class LogoutResponse(BaseModel):
    status: str = "ok"


# --- Helpers


def _ip_hash_from_request(request: Request) -> bytes | None:
    """Hash the client IP for forensics (per ADR-013 — never store
    plaintext IP). Returns None when the client IP isn't available
    (e.g. test client without a peer)."""
    client = request.client
    if client is None or not client.host:
        return None
    return hashlib.sha256(client.host.encode("utf-8")).digest()


def _get_email_sender() -> EmailSender:
    """Composition root for the EmailSender. B.2: LoggingEmailSender only.

    A real provider lands in a follow-up commit by changing this one
    line — the routes + domain layer take an EmailSender via Protocol
    so the swap is one DI change (per phase-b2-plan.md §7 + §10).
    """
    return LoggingEmailSender()


# --- Routes


@router.post("/request", response_model=AuthRequestResponse)
async def request_magic_link(
    body: AuthRequestBody,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthRequestResponse:
    """Request a magic link. Returns 200 unconditionally — never leak
    whether the email maps to a known user (decision #7).

    Failures inside the issue flow (DB errors, encryption errors,
    EmailSender errors) are caught and logged here so the response
    shape is stable regardless of outcome.
    """
    settings = get_settings()
    magic_link_repo = MagicLinkTokenRepository(db_session, account_id=None)
    sender = _get_email_sender()

    try:
        await issue_magic_link(
            email=body.email,
            magic_link_repo=magic_link_repo,
            email_sender=sender,
            frontend_origin=settings.frontend_origin,
            ip_hash=_ip_hash_from_request(request),
        )
    except Exception:
        # Email-enumeration protection: never surface failures.
        # Operators see the underlying error in structured logs.
        log.exception("magic_link_request_failed")

    return AuthRequestResponse()


@router.get("/consume", response_model=ConsumeResponse)
async def consume_link(
    token: str,
    request: Request,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_session)],
) -> ConsumeResponse:
    """Consume a magic-link token. On success: sets the signed
    HttpOnly cookie and returns user info. On rejection
    (`MagicLinkRejected`): returns 401 with an opaque message — the
    reason ('not_found' vs 'expired') is in the audit log only."""
    settings = get_settings()
    magic_link_repo = MagicLinkTokenRepository(db_session, account_id=None)
    user_repo = UserRepository(db_session, account_id=None)
    account_repo = AccountRepository(db_session, account_id=None)
    session_repo = SessionRepository(db_session, account_id=None)

    try:
        result = await consume_magic_link(
            plaintext_token=token,
            magic_link_repo=magic_link_repo,
            user_repo=user_repo,
            account_repo=account_repo,
            session_repo=session_repo,
            ip_hash=_ip_hash_from_request(request),
            user_agent=request.headers.get("User-Agent"),
        )
    except MagicLinkRejected as e:
        # Same opaque 401 for not_found AND expired — caller (UI) shows
        # a generic "invalid or expired link" message and offers re-request.
        log.info("auth_consume_rejected", reason=e.reason)
        raise HTTPException(
            status_code=401, detail="Invalid or expired link"
        )

    set_session_cookie(response, result.session, settings)

    return ConsumeResponse(
        user_id=str(result.user.id),
        account_id=str(result.user.account_id),
        is_new_signup=result.is_new_signup,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_session)],
) -> LogoutResponse:
    """Revoke the current session and clear the cookie. Always returns 200.

    Logout never requires the cookie to be valid — browsers should be
    able to clear stale state. If the cookie IS valid, the server
    revokes the corresponding session row and emits the audit event;
    otherwise the only effect is clearing the client-side cookie.
    """
    settings = get_settings()
    assert settings.session_secret is not None  # validator guarantees

    cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_val:
        session_id = _verify_session_cookie(
            cookie_val, settings.session_secret
        )
        if session_id is not None:
            # Two-step: load session to learn account_id (system context),
            # then revoke through a tenancy-scoped repo so the audit event
            # carries actor_user_id.
            lookup_repo = SessionRepository(db_session, account_id=None)
            target = await lookup_repo.find_one(
                force_cross_account=True, id=session_id
            )
            if target is not None and target.revoked_at is None:
                scoped_repo = SessionRepository(
                    db_session, account_id=target.account_id
                )
                await revoke_session(
                    session_id=session_id,
                    session_repo=scoped_repo,
                    actor_kind="user",
                    actor_user_id=target.user_id,
                )

    clear_session_cookie(response, settings)
    return LogoutResponse()


@router.get("/me", response_model=MeResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> MeResponse:
    """Return the current authenticated user's identity."""
    return MeResponse(
        user_id=str(user.id),
        account_id=str(user.account_id),
        role=user.role,
        display_name=user.display_name,
    )
