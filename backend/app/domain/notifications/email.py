"""Email sending — Protocol + LoggingEmailSender stub.

Per docs/phase-b2-plan.md §7. The `EmailSender` Protocol defines the
interface every sender implements. `LoggingEmailSender` is the only
implementation in B.2 — it emits a structured log line carrying the
message details so operators can read magic-link URLs from logs in
dev or via log shipping in staging.

A real provider implementation (Resend / SendGrid / SES — separate
decision) lands in a follow-up commit by adding a sibling class that
implements the same Protocol. No domain code changes; the auth flow
in B.2.3 takes an `EmailSender` via constructor injection.
"""

from __future__ import annotations

from typing import Protocol

import structlog


class EmailSender(Protocol):
    """Producer-side API for sending email. All senders are async."""

    async def send(self, *, to: str, subject: str, body_text: str) -> None: ...


class LoggingEmailSender:
    """DEV-FOCUSED sender: emits the email as a structured log line.

    PII WARNING: this sender writes the recipient address and the full
    body text to structlog under non-PII-named keys (`recipient`,
    `body_text`) — so the standard PII redactor (per ADR-013, app.core.
    pii) does NOT redact them. That's intentional in dev (operator uses
    the logged URL) but unsafe in production.

    Before any production deploy, swap in a real `EmailSender`
    implementation. Wiring is one DI change at the auth-domain
    composition site.
    """

    def __init__(
        self, logger_name: str = "app.domain.notifications.email"
    ) -> None:
        self._log = structlog.get_logger(logger_name)

    async def send(self, *, to: str, subject: str, body_text: str) -> None:
        self._log.info(
            "email_logged",
            recipient=to,  # NOT 'email' — bypasses PII redactor; see class docstring
            subject=subject,
            body_text=body_text,
        )
