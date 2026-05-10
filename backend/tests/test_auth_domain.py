"""B.2.3 behavior tests for the auth domain layer.

Mocks every repository + the EmailSender. Uses the `recording_publisher`
fixture (conftest.py) to assert which audit events were emitted.

Covers:
  - app.domain.auth.issue.issue_magic_link
  - app.domain.auth.consume.consume_magic_link (existing user + self-signup)
  - app.domain.auth.sessions.revoke_session
  - app.domain.auth.events registration (auth.* event types are known
    to the registry after import + are idempotent across re-registration)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.crypto import decrypt, hash_for_lookup
from app.core.events import RecordingEventPublisher
from app.db.models import Account, MagicLinkToken, User, UserSession
from app.domain.auth import (
    ConsumeResult,
    MagicLinkRejected,
    consume_magic_link,
    issue_magic_link,
    revoke_session,
)
from app.domain.auth.events import register_auth_event_types
from app.domain.notifications.email import LoggingEmailSender


# Ensure auth.* event types are registered for every test in this module
# (defensive: another test may have called reset_registry()).
@pytest.fixture(autouse=True)
def _ensure_auth_events_registered() -> None:
    register_auth_event_types()


# --- Helpers


def _utc(year: int, month: int, day: int, h: int = 12, m: int = 0) -> datetime:
    return datetime(year, month, day, h, m, tzinfo=timezone.utc)


def _make_account(display_name: str = "Test Account") -> Account:
    return Account(id=uuid4(), display_name=display_name)


def _make_user(account_id: UUID, email_hash: bytes) -> User:
    return User(
        id=uuid4(),
        account_id=account_id,
        email_hash=email_hash,
        email_encrypted=b"\x00" * 64,
    )


def _make_token(
    *,
    email: str,
    expires_at: datetime,
    issued_at: datetime | None = None,
) -> MagicLinkToken:
    """Build a MagicLinkToken row whose email_encrypted decrypts back to `email`.

    Uses the real `app.core.crypto.encrypt` so consume's `decrypt(...)` step
    actually works (we're testing the round-trip, not mocking it).
    """
    from app.core.crypto import encrypt

    return MagicLinkToken(
        id=uuid4(),
        email_hash=hash_for_lookup(email),
        email_encrypted=encrypt(email),
        token_hash=b"\x00" * 32,  # not asserted by these tests
        issued_at=issued_at or expires_at - timedelta(minutes=15),
        expires_at=expires_at,
    )


# ============================================================================
# issue_magic_link
# ============================================================================


async def test_issue_writes_token_with_correct_hashes(
    recording_publisher: RecordingEventPublisher,
) -> None:
    magic_link_repo = AsyncMock()
    magic_link_repo.create = AsyncMock(
        return_value=MagicLinkToken(
            id=uuid4(),
            email_hash=b"\x00" * 32,
            email_encrypted=b"\x00" * 64,
            token_hash=b"\x00" * 32,
            issued_at=_utc(2026, 5, 10),
            expires_at=_utc(2026, 5, 10, 12, 15),
        )
    )
    sender = AsyncMock(spec=LoggingEmailSender)
    fixed_now = _utc(2026, 5, 10)

    await issue_magic_link(
        email="Alice@Example.com",
        magic_link_repo=magic_link_repo,
        email_sender=sender,
        frontend_origin="https://app.example.com",
        now_fn=lambda: fixed_now,
        token_fn=lambda: "test-token-abc",
        ttl_minutes=15,
    )

    magic_link_repo.create.assert_awaited_once()
    kwargs = magic_link_repo.create.await_args.kwargs

    # Lookup hash is deterministic + case/whitespace-normalized.
    assert kwargs["email_hash"] == hash_for_lookup("Alice@Example.com")
    assert kwargs["email_hash"] == hash_for_lookup("alice@example.com")

    # token_hash matches sha256(plaintext_token).
    assert kwargs["token_hash"] == hashlib.sha256(b"test-token-abc").digest()

    # email_encrypted is real ciphertext that decrypts back to the input.
    assert decrypt(kwargs["email_encrypted"]) == "Alice@Example.com"

    # Issue + expiry stamp.
    assert kwargs["issued_at"] == fixed_now
    assert kwargs["expires_at"] == fixed_now + timedelta(minutes=15)


async def test_issue_sends_email_with_signin_link(
    recording_publisher: RecordingEventPublisher,
) -> None:
    magic_link_repo = AsyncMock()
    magic_link_repo.create = AsyncMock(
        return_value=MagicLinkToken(
            id=uuid4(),
            email_hash=b"\x00" * 32,
            email_encrypted=b"\x00" * 64,
            token_hash=b"\x00" * 32,
            issued_at=_utc(2026, 5, 10),
            expires_at=_utc(2026, 5, 10, 12, 15),
        )
    )
    sender = AsyncMock(spec=LoggingEmailSender)

    await issue_magic_link(
        email="alice@example.com",
        magic_link_repo=magic_link_repo,
        email_sender=sender,
        frontend_origin="https://app.example.com/",  # trailing slash stripped
        token_fn=lambda: "the-token",
        ttl_minutes=10,
    )

    sender.send.assert_awaited_once()
    kwargs = sender.send.await_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert "sign-in" in kwargs["subject"].lower()
    body = kwargs["body_text"]
    # URL is constructed from frontend_origin (trimmed) + token.
    assert "https://app.example.com/auth/consume?token=the-token" in body
    # TTL is surfaced in the body so the recipient knows the window.
    assert "10 minutes" in body


async def test_issue_publishes_audit_event(
    recording_publisher: RecordingEventPublisher,
) -> None:
    token_id = uuid4()
    magic_link_repo = AsyncMock()
    magic_link_repo.create = AsyncMock(
        return_value=MagicLinkToken(
            id=token_id,
            email_hash=b"\x00" * 32,
            email_encrypted=b"\x00" * 64,
            token_hash=b"\x00" * 32,
            issued_at=_utc(2026, 5, 10),
            expires_at=_utc(2026, 5, 10, 12, 15),
        )
    )
    sender = AsyncMock(spec=LoggingEmailSender)

    await issue_magic_link(
        email="alice@example.com",
        magic_link_repo=magic_link_repo,
        email_sender=sender,
        frontend_origin="https://app.example.com",
        ttl_minutes=15,
    )

    requested = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.magic_link.requested"
    ]
    assert len(requested) == 1
    assert requested[0].target_kind == "magic_link_token"
    assert requested[0].target_id == token_id
    assert requested[0].actor_kind == "system"
    assert requested[0].payload == {"expires_in_minutes": 15}


async def test_issue_uses_settings_default_ttl_when_unspecified(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """ttl_minutes=None falls back to Settings.magic_link_token_ttl_min (15)."""
    magic_link_repo = AsyncMock()
    magic_link_repo.create = AsyncMock(
        return_value=MagicLinkToken(
            id=uuid4(),
            email_hash=b"\x00" * 32,
            email_encrypted=b"\x00" * 64,
            token_hash=b"\x00" * 32,
            issued_at=_utc(2026, 5, 10),
            expires_at=_utc(2026, 5, 10, 12, 15),
        )
    )
    sender = AsyncMock(spec=LoggingEmailSender)
    fixed_now = _utc(2026, 5, 10)

    await issue_magic_link(
        email="alice@example.com",
        magic_link_repo=magic_link_repo,
        email_sender=sender,
        frontend_origin="https://app.example.com",
        now_fn=lambda: fixed_now,
    )

    kwargs = magic_link_repo.create.await_args.kwargs
    assert kwargs["expires_at"] == fixed_now + timedelta(minutes=15)


async def test_issue_passes_ip_hash_through(
    recording_publisher: RecordingEventPublisher,
) -> None:
    magic_link_repo = AsyncMock()
    magic_link_repo.create = AsyncMock(
        return_value=MagicLinkToken(
            id=uuid4(),
            email_hash=b"\x00" * 32,
            email_encrypted=b"\x00" * 64,
            token_hash=b"\x00" * 32,
            issued_at=_utc(2026, 5, 10),
            expires_at=_utc(2026, 5, 10, 12, 15),
        )
    )
    sender = AsyncMock(spec=LoggingEmailSender)
    ip = b"\xab" * 32

    await issue_magic_link(
        email="alice@example.com",
        magic_link_repo=magic_link_repo,
        email_sender=sender,
        frontend_origin="https://app.example.com",
        ip_hash=ip,
    )

    assert magic_link_repo.create.await_args.kwargs["ip_hash"] == ip


# ============================================================================
# consume_magic_link — rejection paths
# ============================================================================


async def test_consume_rejects_when_token_not_found(
    recording_publisher: RecordingEventPublisher,
) -> None:
    magic_link_repo = AsyncMock()
    magic_link_repo.find_active_by_token_hash = AsyncMock(return_value=None)
    user_repo = AsyncMock()
    account_repo = AsyncMock()
    session_repo = AsyncMock()

    with pytest.raises(MagicLinkRejected) as exc_info:
        await consume_magic_link(
            plaintext_token="missing",
            magic_link_repo=magic_link_repo,
            user_repo=user_repo,
            account_repo=account_repo,
            session_repo=session_repo,
        )

    assert exc_info.value.reason == "not_found"
    # Did NOT mark consumed, did NOT touch user/account/session.
    magic_link_repo.mark_consumed.assert_not_called()
    user_repo.find_by_email_hash.assert_not_called()
    account_repo.create.assert_not_called()
    session_repo.create.assert_not_called()

    rejected = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.magic_link.rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].payload == {"reason": "not_found"}
    assert rejected[0].target_id is None


async def test_consume_rejects_when_token_expired(
    recording_publisher: RecordingEventPublisher,
) -> None:
    expired_token = _make_token(
        email="alice@example.com",
        expires_at=_utc(2026, 5, 10, 11, 0),  # 1h before now
    )
    magic_link_repo = AsyncMock()
    magic_link_repo.find_active_by_token_hash = AsyncMock(
        return_value=expired_token
    )
    user_repo = AsyncMock()
    account_repo = AsyncMock()
    session_repo = AsyncMock()

    with pytest.raises(MagicLinkRejected) as exc_info:
        await consume_magic_link(
            plaintext_token="anything",
            magic_link_repo=magic_link_repo,
            user_repo=user_repo,
            account_repo=account_repo,
            session_repo=session_repo,
            now_fn=lambda: _utc(2026, 5, 10, 12, 0),
        )

    assert exc_info.value.reason == "expired"
    magic_link_repo.mark_consumed.assert_not_called()
    session_repo.create.assert_not_called()

    rejected = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.magic_link.rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].payload == {"reason": "expired"}
    # Expired emits target_id (we know which token was rejected).
    assert rejected[0].target_id == expired_token.id


# ============================================================================
# consume_magic_link — existing-user path
# ============================================================================


async def test_consume_existing_user_creates_session_no_signup(
    recording_publisher: RecordingEventPublisher,
) -> None:
    now = _utc(2026, 5, 10, 12, 0)
    token = _make_token(
        email="alice@example.com",
        expires_at=_utc(2026, 5, 10, 12, 10),
    )
    existing_user = _make_user(
        account_id=uuid4(), email_hash=token.email_hash
    )
    new_session = UserSession(
        id=uuid4(),
        user_id=existing_user.id,
        account_id=existing_user.account_id,
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )

    magic_link_repo = AsyncMock()
    magic_link_repo.find_active_by_token_hash = AsyncMock(return_value=token)
    magic_link_repo.mark_consumed = AsyncMock(return_value=True)
    user_repo = AsyncMock()
    user_repo.find_by_email_hash = AsyncMock(return_value=existing_user)
    account_repo = AsyncMock()
    session_repo = AsyncMock()
    session_repo.create = AsyncMock(return_value=new_session)

    result = await consume_magic_link(
        plaintext_token="x",
        magic_link_repo=magic_link_repo,
        user_repo=user_repo,
        account_repo=account_repo,
        session_repo=session_repo,
        ip_hash=b"\xff" * 32,
        user_agent="UA/1.0",
        now_fn=lambda: now,
        session_ttl_days=30,
    )

    assert isinstance(result, ConsumeResult)
    assert result.user is existing_user
    assert result.session is new_session
    assert result.is_new_signup is False

    # Marked consumed; resolved by email_hash; did NOT create account/user.
    magic_link_repo.mark_consumed.assert_awaited_once_with(token.id)
    user_repo.find_by_email_hash.assert_awaited_once_with(token.email_hash)
    account_repo.create.assert_not_called()
    user_repo.create.assert_not_called()

    # Session created with correct TTL + ip_hash + user_agent.
    sess_kwargs = session_repo.create.await_args.kwargs
    assert sess_kwargs["user"] is existing_user
    assert sess_kwargs["issued_at"] == now
    assert sess_kwargs["expires_at"] == now + timedelta(days=30)
    assert sess_kwargs["ip_hash"] == b"\xff" * 32
    assert sess_kwargs["user_agent"] == "UA/1.0"

    # No signup event; consumed event fired with is_new_signup=False.
    assert not [
        e for e in recording_publisher.events if e.event_type == "auth.signup.completed"
    ]
    consumed = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.magic_link.consumed"
    ]
    assert len(consumed) == 1
    assert consumed[0].payload == {"is_new_signup": False}
    assert consumed[0].target_id == new_session.id
    assert consumed[0].account_id == existing_user.account_id


# ============================================================================
# consume_magic_link — self-signup path
# ============================================================================


async def test_consume_self_signup_creates_account_and_user(
    recording_publisher: RecordingEventPublisher,
) -> None:
    now = _utc(2026, 5, 10, 12, 0)
    token = _make_token(
        email="bob@example.com",
        expires_at=_utc(2026, 5, 10, 12, 10),
    )
    new_account = _make_account(display_name="bob")
    new_user = _make_user(account_id=new_account.id, email_hash=token.email_hash)
    new_session = UserSession(
        id=uuid4(),
        user_id=new_user.id,
        account_id=new_account.id,
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )

    magic_link_repo = AsyncMock()
    magic_link_repo.find_active_by_token_hash = AsyncMock(return_value=token)
    magic_link_repo.mark_consumed = AsyncMock(return_value=True)
    user_repo = AsyncMock()
    user_repo.find_by_email_hash = AsyncMock(return_value=None)
    user_repo.create = AsyncMock(return_value=new_user)
    account_repo = AsyncMock()
    account_repo.create = AsyncMock(return_value=new_account)
    session_repo = AsyncMock()
    session_repo.create = AsyncMock(return_value=new_session)

    result = await consume_magic_link(
        plaintext_token="x",
        magic_link_repo=magic_link_repo,
        user_repo=user_repo,
        account_repo=account_repo,
        session_repo=session_repo,
        now_fn=lambda: now,
        session_ttl_days=30,
    )

    assert result.is_new_signup is True
    assert result.user is new_user
    assert result.session is new_session

    # Account created with local-part-of-email display_name.
    account_repo.create.assert_awaited_once_with(display_name="bob")

    # User created with reused email_hash + email_encrypted from the token.
    user_kwargs = user_repo.create.await_args.kwargs
    assert user_kwargs["account_id"] == new_account.id
    assert user_kwargs["email_hash"] == token.email_hash
    assert user_kwargs["email_encrypted"] == token.email_encrypted
    assert user_kwargs["display_name"] == "bob"
    assert user_kwargs["role"] == "owner"

    # Both signup + consumed events fired.
    signup = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.signup.completed"
    ]
    assert len(signup) == 1
    assert signup[0].account_id == new_account.id
    assert signup[0].target_id == new_user.id
    assert signup[0].target_kind == "user"

    consumed = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.magic_link.consumed"
    ]
    assert len(consumed) == 1
    assert consumed[0].payload == {"is_new_signup": True}


async def test_consume_self_signup_handles_email_with_no_at_sign(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Defensive — local part falls back to whole string if @ is absent
    (the encryption round-trip preserves whatever was issued)."""
    from app.core.crypto import encrypt

    now = _utc(2026, 5, 10, 12, 0)
    weird = "weirdstring"  # not a real email but defensive path
    token = MagicLinkToken(
        id=uuid4(),
        email_hash=hash_for_lookup(weird),
        email_encrypted=encrypt(weird),
        token_hash=b"\x00" * 32,
        issued_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=10),
    )
    new_account = _make_account(display_name=weird)
    new_user = _make_user(account_id=new_account.id, email_hash=token.email_hash)
    new_session = UserSession(
        id=uuid4(),
        user_id=new_user.id,
        account_id=new_account.id,
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )

    magic_link_repo = AsyncMock()
    magic_link_repo.find_active_by_token_hash = AsyncMock(return_value=token)
    magic_link_repo.mark_consumed = AsyncMock(return_value=True)
    user_repo = AsyncMock()
    user_repo.find_by_email_hash = AsyncMock(return_value=None)
    user_repo.create = AsyncMock(return_value=new_user)
    account_repo = AsyncMock()
    account_repo.create = AsyncMock(return_value=new_account)
    session_repo = AsyncMock()
    session_repo.create = AsyncMock(return_value=new_session)

    await consume_magic_link(
        plaintext_token="x",
        magic_link_repo=magic_link_repo,
        user_repo=user_repo,
        account_repo=account_repo,
        session_repo=session_repo,
        now_fn=lambda: now,
    )

    account_repo.create.assert_awaited_once_with(display_name=weird)


async def test_consume_uses_settings_default_session_ttl(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """session_ttl_days=None falls back to Settings.session_ttl_days (30)."""
    now = _utc(2026, 5, 10, 12, 0)
    token = _make_token(
        email="alice@example.com",
        expires_at=now + timedelta(minutes=10),
    )
    user = _make_user(account_id=uuid4(), email_hash=token.email_hash)

    magic_link_repo = AsyncMock()
    magic_link_repo.find_active_by_token_hash = AsyncMock(return_value=token)
    magic_link_repo.mark_consumed = AsyncMock(return_value=True)
    user_repo = AsyncMock()
    user_repo.find_by_email_hash = AsyncMock(return_value=user)
    account_repo = AsyncMock()
    session_repo = AsyncMock()
    session_repo.create = AsyncMock(
        return_value=UserSession(
            id=uuid4(),
            user_id=user.id,
            account_id=user.account_id,
            issued_at=now,
            expires_at=now + timedelta(days=30),
        )
    )

    await consume_magic_link(
        plaintext_token="x",
        magic_link_repo=magic_link_repo,
        user_repo=user_repo,
        account_repo=account_repo,
        session_repo=session_repo,
        now_fn=lambda: now,
    )

    sess_kwargs = session_repo.create.await_args.kwargs
    assert sess_kwargs["expires_at"] == now + timedelta(days=30)


# ============================================================================
# revoke_session
# ============================================================================


async def test_revoke_calls_repo_and_emits_event_when_revoked(
    recording_publisher: RecordingEventPublisher,
) -> None:
    session_repo = AsyncMock()
    session_repo.revoke = AsyncMock(return_value=True)
    sid = uuid4()
    actor_uid = uuid4()

    revoked = await revoke_session(
        session_id=sid,
        session_repo=session_repo,
        actor_kind="user",
        actor_user_id=actor_uid,
    )

    assert revoked is True
    session_repo.revoke.assert_awaited_once_with(sid)

    events = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.session.revoked"
    ]
    assert len(events) == 1
    assert events[0].actor_kind == "user"
    assert events[0].actor_user_id == actor_uid
    assert events[0].target_kind == "session"
    assert events[0].target_id == sid


async def test_revoke_does_not_emit_event_when_no_row_revoked(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Idempotent no-op (already-revoked session): NO event published."""
    session_repo = AsyncMock()
    session_repo.revoke = AsyncMock(return_value=False)

    revoked = await revoke_session(
        session_id=uuid4(),
        session_repo=session_repo,
    )

    assert revoked is False
    assert not [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.session.revoked"
    ]


async def test_revoke_default_actor_kind_is_system(
    recording_publisher: RecordingEventPublisher,
) -> None:
    """Default `actor_kind="system"` covers admin/scheduled revocations."""
    session_repo = AsyncMock()
    session_repo.revoke = AsyncMock(return_value=True)

    await revoke_session(session_id=uuid4(), session_repo=session_repo)

    [event] = [
        e
        for e in recording_publisher.events
        if e.event_type == "auth.session.revoked"
    ]
    assert event.actor_kind == "system"
    assert event.actor_user_id is None


# ============================================================================
# events module — registration + idempotency
# ============================================================================


def test_auth_event_types_registered() -> None:
    """All five auth.* event types are in the registry after import."""
    from app.core.event_registry import lookup

    for event_type in (
        "auth.magic_link.requested",
        "auth.magic_link.consumed",
        "auth.magic_link.rejected",
        "auth.signup.completed",
        "auth.session.revoked",
    ):
        definition = lookup(event_type)
        assert definition.event_type == event_type
        assert definition.category == "audit"
        assert definition.target_table == "audit_log"


def test_register_auth_event_types_is_idempotent() -> None:
    """Re-calling register_auth_event_types() does not raise."""
    register_auth_event_types()
    register_auth_event_types()  # second call must not raise DuplicateRegistrationError


# ============================================================================
# Settings.session_ttl_days field
# ============================================================================


def test_settings_session_ttl_days_default_30(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SESSION_TTL_DAYS", raising=False)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development")
    assert s.session_ttl_days == 30


def test_settings_session_ttl_days_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import Settings

    s = Settings(_env_file=None, app_env="development", session_ttl_days=7)
    assert s.session_ttl_days == 7
