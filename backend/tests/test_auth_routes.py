"""B.2.4 tests for the auth routes + cookie helpers + get_current_user.

Three layers:
  1. Cookie helpers (`_sign_session_id`, `_verify_session_cookie`) —
     pure-function tests, no FastAPI.
  2. `get_current_user` dependency — direct invocation with a mocked
     AsyncSession + monkey-patched repository methods. Covers every
     401 path.
  3. Routes (`/v1/auth/{request,consume,logout,me}`) — TestClient with
     `app.dependency_overrides`. Auth-domain functions
     (issue/consume/revoke) are monkey-patched at the import site
     inside `app.api.v1.auth` so the route tests focus on transport
     behavior (status codes, request parsing, cookie shape, error
     mapping) rather than re-testing domain logic (already covered by
     test_auth_domain.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.deps import (
    SESSION_COOKIE_NAME,
    _sign_session_id,
    _verify_session_cookie,
    get_current_user,
)
from app.core.config import get_settings
from app.db.models import User, UserSession
from app.db.repositories.session_repo import SessionRepository
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session
from app.domain.auth import ConsumeResult, MagicLinkRejected
from app.main import app


# ============================================================================
# Helpers + fixtures
# ============================================================================


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(account_id: UUID | None = None) -> User:
    return User(
        id=uuid4(),
        account_id=account_id or uuid4(),
        email_hash=b"\x00" * 32,
        email_encrypted=b"\x00" * 64,
        display_name="Alice",
        role="owner",
    )


def _make_session(
    user: User,
    *,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> UserSession:
    now = _utc_now()
    return UserSession(
        id=uuid4(),
        user_id=user.id,
        account_id=user.account_id,
        issued_at=issued_at or now,
        expires_at=expires_at or (now + timedelta(days=30)),
        revoked_at=revoked_at,
    )


@pytest.fixture
def mock_async_session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.rollback = AsyncMock()
    return s


@pytest.fixture
def client(mock_async_session: AsyncMock) -> Iterator[TestClient]:
    """TestClient with `get_session` overridden to yield a mock AsyncSession.

    Cleared after each test so dependency_overrides don't leak between
    tests in this module.
    """

    async def _fake_get_session():
        yield mock_async_session

    app.dependency_overrides[get_session] = _fake_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def authenticated_client() -> Iterator[tuple[TestClient, User]]:
    """TestClient with `get_current_user` overridden to return a fixed User.

    Use for /me + any future routes that depend on get_current_user
    without exercising the cookie-validation path itself (covered
    separately in the get_current_user unit tests below).
    """
    user = _make_user()

    async def _fake_user() -> User:
        return user

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        yield TestClient(app), user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ============================================================================
# Cookie helpers (pure functions)
# ============================================================================


def test_sign_session_id_is_deterministic() -> None:
    sid = uuid4()
    secret = "test-secret"
    assert _sign_session_id(sid, secret) == _sign_session_id(sid, secret)


def test_sign_session_id_format() -> None:
    sid = uuid4()
    cookie = _sign_session_id(sid, "secret")
    assert cookie.startswith(f"{sid}.")
    sig = cookie.split(".", 5)[-1]  # UUID has 4 dashes; sig is the trailing field
    # sha256 hex = 64 chars
    assert len(sig) == 64


def test_verify_session_cookie_roundtrip() -> None:
    sid = uuid4()
    secret = "test-secret"
    cookie = _sign_session_id(sid, secret)
    assert _verify_session_cookie(cookie, secret) == sid


def test_verify_session_cookie_rejects_tampered_signature() -> None:
    sid = uuid4()
    cookie = _sign_session_id(sid, "test-secret")
    # Flip the last hex digit of the signature.
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
    assert _verify_session_cookie(tampered, "test-secret") is None


def test_verify_session_cookie_rejects_wrong_secret() -> None:
    sid = uuid4()
    cookie = _sign_session_id(sid, "secret-A")
    assert _verify_session_cookie(cookie, "secret-B") is None


def test_verify_session_cookie_rejects_malformed() -> None:
    """Empty / no-dot / non-UUID prefix all return None."""
    assert _verify_session_cookie("", "s") is None
    assert _verify_session_cookie("not-a-cookie", "s") is None
    assert _verify_session_cookie("not-a-uuid.deadbeef", "s") is None


# ============================================================================
# get_current_user — direct invocation with mocks
# ============================================================================


async def test_get_current_user_returns_user_for_valid_cookie(
    monkeypatch: pytest.MonkeyPatch,
    mock_async_session: AsyncMock,
) -> None:
    settings = get_settings()
    user = _make_user()
    sess = _make_session(user)

    cookie_val = _sign_session_id(sess.id, settings.session_secret)
    request = MagicMock()
    request.cookies = {SESSION_COOKIE_NAME: cookie_val}

    # SessionRepository.find_one returns the active session row.
    monkeypatch.setattr(
        SessionRepository,
        "find_one",
        AsyncMock(return_value=sess),
    )
    # UserRepository.get returns the user.
    monkeypatch.setattr(
        UserRepository, "get", AsyncMock(return_value=user)
    )

    result = await get_current_user(request, mock_async_session)
    assert result is user


async def test_get_current_user_401_when_no_cookie(
    mock_async_session: AsyncMock,
) -> None:
    request = MagicMock()
    request.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request, mock_async_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_401_when_signature_invalid(
    mock_async_session: AsyncMock,
) -> None:
    settings = get_settings()
    sid = uuid4()
    cookie_val = _sign_session_id(sid, "wrong-secret")  # signed with wrong secret
    request = MagicMock()
    request.cookies = {SESSION_COOKIE_NAME: cookie_val}

    # Sanity: verify the cookie won't pass against the real secret.
    assert _verify_session_cookie(cookie_val, settings.session_secret) is None

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request, mock_async_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_401_when_session_unknown(
    monkeypatch: pytest.MonkeyPatch,
    mock_async_session: AsyncMock,
) -> None:
    settings = get_settings()
    sid = uuid4()
    cookie_val = _sign_session_id(sid, settings.session_secret)
    request = MagicMock()
    request.cookies = {SESSION_COOKIE_NAME: cookie_val}

    monkeypatch.setattr(
        SessionRepository, "find_one", AsyncMock(return_value=None)
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request, mock_async_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_401_when_session_revoked(
    monkeypatch: pytest.MonkeyPatch,
    mock_async_session: AsyncMock,
) -> None:
    settings = get_settings()
    user = _make_user()
    sess = _make_session(user, revoked_at=_utc_now() - timedelta(minutes=1))

    cookie_val = _sign_session_id(sess.id, settings.session_secret)
    request = MagicMock()
    request.cookies = {SESSION_COOKIE_NAME: cookie_val}

    monkeypatch.setattr(
        SessionRepository, "find_one", AsyncMock(return_value=sess)
    )
    # UserRepository.get must NOT be called once the revoke check fails.
    user_get = AsyncMock(return_value=user)
    monkeypatch.setattr(UserRepository, "get", user_get)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request, mock_async_session)
    assert exc_info.value.status_code == 401
    user_get.assert_not_awaited()


async def test_get_current_user_401_when_session_expired(
    monkeypatch: pytest.MonkeyPatch,
    mock_async_session: AsyncMock,
) -> None:
    settings = get_settings()
    user = _make_user()
    sess = _make_session(
        user,
        issued_at=_utc_now() - timedelta(days=31),
        expires_at=_utc_now() - timedelta(minutes=1),
    )

    cookie_val = _sign_session_id(sess.id, settings.session_secret)
    request = MagicMock()
    request.cookies = {SESSION_COOKIE_NAME: cookie_val}

    monkeypatch.setattr(
        SessionRepository, "find_one", AsyncMock(return_value=sess)
    )
    user_get = AsyncMock(return_value=user)
    monkeypatch.setattr(UserRepository, "get", user_get)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request, mock_async_session)
    assert exc_info.value.status_code == 401
    user_get.assert_not_awaited()


async def test_get_current_user_401_when_user_missing(
    monkeypatch: pytest.MonkeyPatch,
    mock_async_session: AsyncMock,
) -> None:
    """Session points to a user that no longer exists (or is soft-deleted
    so the tenancy-scoped UserRepository.get returns None)."""
    settings = get_settings()
    user = _make_user()
    sess = _make_session(user)

    cookie_val = _sign_session_id(sess.id, settings.session_secret)
    request = MagicMock()
    request.cookies = {SESSION_COOKIE_NAME: cookie_val}

    monkeypatch.setattr(
        SessionRepository, "find_one", AsyncMock(return_value=sess)
    )
    monkeypatch.setattr(UserRepository, "get", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request, mock_async_session)
    assert exc_info.value.status_code == 401


# ============================================================================
# POST /v1/auth/request
# ============================================================================


def test_request_returns_200_and_calls_issue(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    issue_calls: list[dict] = []

    async def fake_issue(**kwargs):
        issue_calls.append(kwargs)

    monkeypatch.setattr(
        "app.api.v1.auth.issue_magic_link", fake_issue
    )

    r = client.post(
        "/v1/auth/request", json={"email": "alice@example.com"}
    )

    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert len(issue_calls) == 1
    assert issue_calls[0]["email"] == "alice@example.com"
    # frontend_origin is sourced from settings (default localhost:5173 in dev).
    assert issue_calls[0]["frontend_origin"].startswith("http")


def test_request_rejects_invalid_email_with_422(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Pydantic EmailStr validation -> 422; issue_magic_link not called."""
    fake_issue = AsyncMock()
    monkeypatch.setattr("app.api.v1.auth.issue_magic_link", fake_issue)

    r = client.post("/v1/auth/request", json={"email": "not-an-email"})
    assert r.status_code == 422
    fake_issue.assert_not_awaited()


def test_request_returns_200_even_when_issue_raises(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Email-enumeration protection (decision #7): caller cannot
    distinguish 'we sent it' from 'an error occurred'."""

    async def boom(**kwargs):
        raise RuntimeError("simulated DB / encryption failure")

    monkeypatch.setattr("app.api.v1.auth.issue_magic_link", boom)

    r = client.post(
        "/v1/auth/request", json={"email": "alice@example.com"}
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ============================================================================
# GET /v1/auth/consume
# ============================================================================


def test_consume_success_returns_200_and_sets_cookie(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    user = _make_user()
    sess = _make_session(user)
    fake_result = ConsumeResult(
        user=user, session=sess, is_new_signup=True
    )

    async def fake_consume(**kwargs):
        return fake_result

    monkeypatch.setattr("app.api.v1.auth.consume_magic_link", fake_consume)

    r = client.get("/v1/auth/consume?token=opaque-token")

    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(user.id)
    assert body["account_id"] == str(user.account_id)
    assert body["is_new_signup"] is True

    # Cookie is set on the response with the signed format.
    cookie = r.cookies.get(SESSION_COOKIE_NAME)
    assert cookie is not None
    settings = get_settings()
    assert _verify_session_cookie(cookie, settings.session_secret) == sess.id


def test_consume_rejected_returns_401_no_cookie(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def reject(**kwargs):
        raise MagicLinkRejected("not_found")

    monkeypatch.setattr("app.api.v1.auth.consume_magic_link", reject)

    r = client.get("/v1/auth/consume?token=anything")
    assert r.status_code == 401
    # Opaque message — does not leak 'not_found' vs 'expired'.
    assert "Invalid or expired" in r.json()["error"]["message"]
    # No cookie set on a rejection.
    assert r.cookies.get(SESSION_COOKIE_NAME) is None


def test_consume_expired_returns_401_no_cookie(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Expired and not_found return the SAME 401 message (no enumeration of
    which reason fired)."""

    async def reject(**kwargs):
        raise MagicLinkRejected("expired")

    monkeypatch.setattr("app.api.v1.auth.consume_magic_link", reject)

    r = client.get("/v1/auth/consume?token=anything")
    assert r.status_code == 401
    assert "Invalid or expired" in r.json()["error"]["message"]


# ============================================================================
# POST /v1/auth/logout
# ============================================================================


def test_logout_clears_cookie_when_no_cookie_present(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Logout without a cookie still returns 200 and clears the (absent)
    cookie. Browsers should be able to issue logout to clear stale state."""
    revoke_calls: list = []

    async def fake_revoke(**kwargs):
        revoke_calls.append(kwargs)
        return True

    monkeypatch.setattr("app.api.v1.auth.revoke_session", fake_revoke)

    r = client.post("/v1/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert revoke_calls == []  # nothing to revoke


def test_logout_with_invalid_cookie_returns_200_no_revoke(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    revoke_calls: list = []

    async def fake_revoke(**kwargs):
        revoke_calls.append(kwargs)
        return True

    monkeypatch.setattr("app.api.v1.auth.revoke_session", fake_revoke)

    r = client.post(
        "/v1/auth/logout",
        cookies={SESSION_COOKIE_NAME: "garbage-not-a-valid-cookie"},
    )
    assert r.status_code == 200
    assert revoke_calls == []  # invalid signature -> no revoke


def test_logout_with_valid_cookie_revokes_and_clears(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    settings = get_settings()
    user = _make_user()
    sess = _make_session(user)
    cookie_val = _sign_session_id(sess.id, settings.session_secret)

    revoke_calls: list = []

    async def fake_revoke(**kwargs):
        revoke_calls.append(kwargs)
        return True

    # SessionRepository.find_one returns the active session.
    monkeypatch.setattr(
        SessionRepository, "find_one", AsyncMock(return_value=sess)
    )
    monkeypatch.setattr("app.api.v1.auth.revoke_session", fake_revoke)

    r = client.post(
        "/v1/auth/logout",
        cookies={SESSION_COOKIE_NAME: cookie_val},
    )
    assert r.status_code == 200
    assert len(revoke_calls) == 1
    assert revoke_calls[0]["session_id"] == sess.id
    assert revoke_calls[0]["actor_kind"] == "user"
    assert revoke_calls[0]["actor_user_id"] == user.id


def test_logout_with_already_revoked_cookie_does_not_re_revoke(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """If the session is already revoked, do NOT re-call revoke_session
    (avoids spurious audit events)."""
    settings = get_settings()
    user = _make_user()
    sess = _make_session(
        user, revoked_at=_utc_now() - timedelta(minutes=10)
    )
    cookie_val = _sign_session_id(sess.id, settings.session_secret)

    fake_revoke = AsyncMock(return_value=True)
    monkeypatch.setattr(
        SessionRepository, "find_one", AsyncMock(return_value=sess)
    )
    monkeypatch.setattr("app.api.v1.auth.revoke_session", fake_revoke)

    r = client.post(
        "/v1/auth/logout",
        cookies={SESSION_COOKIE_NAME: cookie_val},
    )
    assert r.status_code == 200
    fake_revoke.assert_not_awaited()


# ============================================================================
# GET /v1/auth/me
# ============================================================================


def test_me_returns_user_when_authenticated(
    authenticated_client: tuple[TestClient, User],
) -> None:
    client, user = authenticated_client
    r = client.get("/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(user.id)
    assert body["account_id"] == str(user.account_id)
    assert body["role"] == "owner"
    assert body["display_name"] == "Alice"


def test_me_returns_401_when_no_cookie(client: TestClient) -> None:
    """Without a cookie, get_current_user raises 401 before touching DB."""
    r = client.get("/v1/auth/me")
    assert r.status_code == 401


# ============================================================================
# OpenAPI surface — auth routes are documented
# ============================================================================


def test_auth_routes_appear_in_openapi(client: TestClient) -> None:
    r = client.get("/v1/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for p in (
        "/v1/auth/request",
        "/v1/auth/consume",
        "/v1/auth/logout",
        "/v1/auth/me",
    ):
        assert p in paths, f"missing OpenAPI path {p}"
