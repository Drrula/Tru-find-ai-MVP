"""PII field registry. Keep aligned with ADR-013.

Single source of truth for which dict keys count as PII and must be
redacted before leaving the process. Used by:
  - app.core.logging (structlog processor)
  - app.core.observability (Sentry beforeSend hook + breadcrumb scrubber)

When a new sensitive field type is introduced anywhere in the codebase,
add it here — both the logging and observability paths pick it up
automatically.
"""

from __future__ import annotations

PII_FIELDS: frozenset[str] = frozenset(
    {
        "email",
        "email_plaintext",
        "phone",
        "phone_plaintext",
        "address",
        "tax_id",
        "ssn",
        "password",
        "api_key",
        "secret",
        "access_token",
        "session_token",
        "magic_link_token",
        "encryption_key",
    }
)
