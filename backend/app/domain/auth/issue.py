"""Magic-link issue flow (per docs/phase-b2-plan.md §4 — request half).

Mints a plaintext token, hashes it for storage, encrypts the email so
consume can recover the plaintext (per B.2.2-amend), writes the
magic_link_token row, and hands a sign-in URL to the injected
EmailSender. ALWAYS succeeds from the caller's perspective —
email-enumeration protection (decision #7) is the routes layer's
job (always 200 regardless of outcome here).

B.3.6 (per ADR-045 + phase-b3-plan.md §9): the email subject + body
are NOT hardcoded here — they come from the active vertical pack's
copy table under the keys `auth.email.sign_in.subject` and
`auth.email.sign_in.body`. The body template carries `{link}` and
`{minutes}` placeholders.

`now_fn` and `token_fn` are injectable for deterministic testing;
production callers omit them and get `datetime.now(timezone.utc)` +
`secrets.token_urlsafe(32)` respectively.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.core.config import get_settings
from app.core.crypto import encrypt, hash_for_lookup
from app.core.events import publish_event
from app.db.repositories.magic_link_token_repo import MagicLinkTokenRepository
from app.domain.notifications.email import EmailSender
from app.vertical.db_pack import get_active_pack
from app.vertical.pack import VerticalPack
from app.vertical.registry import UnknownPackError

_DEFAULT_LOCALE = "en-US"


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_token() -> str:
    # 32 random bytes -> ~43-char URL-safe string. Per phase-b2-plan.md §4.
    return secrets.token_urlsafe(32)


def _get_pack() -> VerticalPack:
    """Resolve the active vertical pack for auth email copy.

    Same pattern as `app.domain.scoring._get_pack` /
    `app.domain.signals._get_pack`: DB-backed pack on cache hit,
    source-module fallback on miss, defensive load-on-miss for test
    contexts that bypass `app.main`.
    """
    pack_id = get_settings().default_vertical_pack_id
    try:
        return get_active_pack(pack_id)
    except UnknownPackError:
        from app.vertical import load_default_packs

        load_default_packs()
        return get_active_pack(pack_id)


async def issue_magic_link(
    *,
    email: str,
    magic_link_repo: MagicLinkTokenRepository,
    email_sender: EmailSender,
    frontend_origin: str,
    ip_hash: bytes | None = None,
    now_fn: Callable[[], datetime] = _default_now,
    token_fn: Callable[[], str] = _default_token,
    ttl_minutes: int | None = None,
) -> None:
    """Issue a magic link to `email`.

    Returns None — the caller does not learn the plaintext token (it
    only ever exists in the email body and briefly in this function's
    scope), and does not learn whether the email maps to an existing
    account (decision #7 — caller returns 200 unconditionally).

    Side effects:
      1. INSERT magic_link_token (staged on the repo's session).
      2. EmailSender.send(...) called with the sign-in URL.
      3. `auth.magic_link.requested` audit event published.
    """
    settings = get_settings()
    ttl = timedelta(
        minutes=ttl_minutes
        if ttl_minutes is not None
        else settings.magic_link_token_ttl_min
    )

    email_hash = hash_for_lookup(email)
    email_encrypted = encrypt(email)

    plaintext_token = token_fn()
    token_hash = hashlib.sha256(plaintext_token.encode("utf-8")).digest()

    issued_at = now_fn()
    expires_at = issued_at + ttl

    token_row = await magic_link_repo.create(
        email_hash=email_hash,
        email_encrypted=email_encrypted,
        token_hash=token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
        ip_hash=ip_hash,
    )

    link = f"{frontend_origin.rstrip('/')}/auth/consume?token={plaintext_token}"
    minutes = int(ttl.total_seconds() // 60)

    # Resolve subject + body from the active vertical pack's copy.
    # Per ADR-045 + phase-b3-plan.md §9, brand strings live in the
    # pack, not in this file. A pack missing these keys will raise
    # KeyError -- caught by the routes layer's email-enumeration
    # protection (always-200), so operators see the failure in logs
    # without leaking it to the caller.
    pack_copy = _get_pack().copy()
    subject = pack_copy[(_DEFAULT_LOCALE, "auth.email.sign_in.subject")]
    body_template = pack_copy[(_DEFAULT_LOCALE, "auth.email.sign_in.body")]
    body = body_template.format(link=link, minutes=minutes)

    await email_sender.send(
        to=email,
        subject=subject,
        body_text=body,
    )

    publish_event(
        "auth.magic_link.requested",
        payload={
            "expires_in_minutes": minutes,
        },
        actor_kind="system",
        target_kind="magic_link_token",
        target_id=token_row.id,
    )
