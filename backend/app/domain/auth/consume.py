"""Magic-link consume flow (per docs/phase-b2-plan.md §4 — consume half).

Validates the plaintext token, marks it consumed, decrypts the
encrypted email (per B.2.2-amend) to recover plaintext, then either
reuses an existing user or self-signs-up a new account+user
(decision #6). Always creates a new session bound to the user.

Raises `MagicLinkRejected` on token not found / already consumed /
expired — the routes layer (B.2.4) maps these to 401 without leaking
the reason.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from app.core.config import get_settings
from app.core.crypto import decrypt
from app.core.events import publish_event
from app.db.models import User, UserSession
from app.db.repositories.account_repo import AccountRepository
from app.db.repositories.magic_link_token_repo import MagicLinkTokenRepository
from app.db.repositories.session_repo import SessionRepository
from app.db.repositories.user_repo import UserRepository

RejectionReason = Literal["not_found", "expired"]


class MagicLinkRejected(Exception):
    """Token rejected at consume time.

    `.reason` is for logging / audit only — callers MUST NOT leak it
    in HTTP responses (decision #7 spirit applies to consume too:
    "expired" vs. "not_found" both map to the same 401).
    """

    def __init__(self, reason: RejectionReason) -> None:
        self.reason = reason
        super().__init__(f"magic link rejected: {reason}")


@dataclass(frozen=True)
class ConsumeResult:
    """Successful consume result.

    `is_new_signup` is True when this consume created a new account+user
    (the email_hash had no existing user); False when an existing user
    was found and reused.
    """

    user: User
    session: UserSession
    is_new_signup: bool


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _local_part(email: str) -> str:
    """Return the local part (before '@') of an email; or the whole
    string if no '@' is present (defensive — consume input came from a
    field we encrypted, so well-formed in practice)."""
    return email.split("@", 1)[0] if "@" in email else email


async def consume_magic_link(
    *,
    plaintext_token: str,
    magic_link_repo: MagicLinkTokenRepository,
    user_repo: UserRepository,
    account_repo: AccountRepository,
    session_repo: SessionRepository,
    ip_hash: bytes | None = None,
    user_agent: str | None = None,
    now_fn: Callable[[], datetime] = _default_now,
    session_ttl_days: int | None = None,
) -> ConsumeResult:
    """Consume a magic-link token and return the resulting session.

    Steps (per docs/phase-b2-plan.md §4):
      1. Hash the plaintext; look up an outstanding token row.
      2. If not found OR already consumed -> MagicLinkRejected("not_found").
      3. If expires_at <= now -> MagicLinkRejected("expired").
      4. Mark consumed_at = now.
      5. Decrypt token.email_encrypted -> plaintext email.
      6. Look up user by email_hash (force_cross_account; system context).
      7. If no user: self-signup -> create account (display_name =
         local-part-of-email) + user (account_id, role='owner', email_hash,
         email_encrypted from the token row). Emit auth.signup.completed.
      8. Always: create a new session (issued_at=now, expires_at=now+TTL).
      9. Emit auth.magic_link.consumed.

    The repositories DO NOT need to be tenancy-scoped at construction:
      - magic_link_repo: no account_id column.
      - user_repo: find_by_email_hash uses force_cross_account=True
        internally; create() takes account_id explicitly.
      - account_repo: no account_id column (tenancy root).
      - session_repo: create() denormalizes account_id from the user.
    Pass `account_id=None` to all four constructors at the call site.
    """
    settings = get_settings()
    ttl_days = (
        session_ttl_days
        if session_ttl_days is not None
        else settings.session_ttl_days
    )
    session_ttl = timedelta(days=ttl_days)

    # 1. Lookup
    token_hash = hashlib.sha256(plaintext_token.encode("utf-8")).digest()
    token_row = await magic_link_repo.find_active_by_token_hash(token_hash)

    # 2. Not found / already consumed
    if token_row is None:
        publish_event(
            "auth.magic_link.rejected",
            payload={"reason": "not_found"},
            actor_kind="system",
        )
        raise MagicLinkRejected("not_found")

    # 3. Expired
    now = now_fn()
    if token_row.expires_at <= now:
        publish_event(
            "auth.magic_link.rejected",
            payload={"reason": "expired"},
            actor_kind="system",
            target_kind="magic_link_token",
            target_id=token_row.id,
        )
        raise MagicLinkRejected("expired")

    # 4. Mark consumed
    await magic_link_repo.mark_consumed(token_row.id)

    # 5. Decrypt the email for self-signup display_name + email_encrypted reuse.
    plaintext_email = decrypt(token_row.email_encrypted)

    # 6. Resolve user
    user = await user_repo.find_by_email_hash(token_row.email_hash)
    is_new_signup = user is None

    # 7. Self-signup branch
    if user is None:
        local = _local_part(plaintext_email)
        account = await account_repo.create(display_name=local)
        user = await user_repo.create(
            account_id=account.id,
            email_hash=token_row.email_hash,
            email_encrypted=token_row.email_encrypted,
            display_name=local,
            role="owner",
        )
        publish_event(
            "auth.signup.completed",
            actor_kind="system",
            account_id=account.id,
            target_kind="user",
            target_id=user.id,
        )

    # 8. Always create a new session
    session = await session_repo.create(
        user=user,
        issued_at=now,
        expires_at=now + session_ttl,
        ip_hash=ip_hash,
        user_agent=user_agent,
    )

    # 9. Audit consume success
    publish_event(
        "auth.magic_link.consumed",
        payload={"is_new_signup": is_new_signup},
        actor_kind="system",
        account_id=user.account_id,
        target_kind="session",
        target_id=session.id,
    )

    return ConsumeResult(
        user=user, session=session, is_new_signup=is_new_signup
    )
