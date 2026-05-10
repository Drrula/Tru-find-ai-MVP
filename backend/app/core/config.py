"""Application settings, loaded from environment + .env.

Every external value the system will use is enumerated here so that adding
a new dependency in a later phase is a field addition, not a new config
layer. Concrete provider/model defaults are deferred to outstanding
decisions §5.6 / §5.11 / §5.14.

Per ADR-002, ADR-003, ADR-013, ADR-018, ADR-024, ADR-025, ADR-030.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local-dev defaults. Auto-applied by the model_validator below when the
# corresponding env var is unset and APP_ENV is development. Staging /
# production must set each value explicitly (validator raises otherwise).
#
# Per docs/phase-b-plan.md §6 (DATABASE_URL) + docs/phase-b2-plan.md §8
# (ENCRYPTION_KEY + SESSION_SECRET).
_DEV_DATABASE_URL = "postgresql+asyncpg://trufindai:trufindai@localhost:5432/trufindai"
# 32-byte zero key, base64-encoded. Cryptographically WEAK by design — the
# validator below forbids this fallback in non-dev. Marked DEV ONLY.
_DEV_ENCRYPTION_KEY = base64.b64encode(b"\x00" * 32).decode("ascii")
_DEV_SESSION_SECRET = "dev-session-secret-do-not-use-in-non-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application
    app_env: Literal["development", "staging", "production"] = Field(default="development")

    # --- Logging / observability (ADR-030)
    log_level: str = Field(default="INFO")
    request_id_header: str = Field(default="X-Request-ID")
    sentry_dsn: str | None = Field(default=None)

    # --- HTTP layer
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_per_minute: int = Field(default=60)

    # --- Postgres (ADR-002, B.1.1). DATABASE_URL is required when APP_ENV is
    # staging / production; in development it defaults to the docker-compose URL.
    database_url: str | None = Field(default=None)
    database_echo: bool = Field(default=False)

    # --- Phase C placeholder (Redis) — ADR-003
    redis_url: str | None = Field(default=None)

    # --- Phase B+ placeholders (auth) — ADR-018
    session_secret: str | None = Field(default=None)
    encryption_key: str | None = Field(default=None)
    magic_link_token_ttl_min: int = Field(default=15)

    # --- Phase E placeholders (Stripe) — ADR-023, ADR-043
    stripe_secret_key: str | None = Field(default=None)
    stripe_webhook_secret: str | None = Field(default=None)

    # --- Phase F placeholders (Twilio — gated on 10DLC per ADR-025)
    twilio_account_sid: str | None = Field(default=None)
    twilio_auth_token: str | None = Field(default=None)
    twilio_from_number: str | None = Field(default=None)

    # --- Phase D / H placeholders (LLM, Places). Concrete values per §5.6 / §5.11.
    llm_provider: str | None = Field(default=None)
    llm_api_key: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    google_places_api_key: str | None = Field(default=None)

    @model_validator(mode="after")
    def _resolve_secrets(self) -> "Settings":
        """Apply dev defaults; require explicit values in staging / production.

        Covers DATABASE_URL (per docs/phase-b-plan.md §6),
        ENCRYPTION_KEY (per docs/phase-b2-plan.md §8 — AES-256-GCM key
        used by app.core.crypto for PII encryption per ADR-013), and
        SESSION_SECRET (per docs/phase-b2-plan.md §8 — HMAC key used to
        sign session cookies per ADR-018).

        In dev, each unset field falls back to a hardcoded constant
        marked DEV ONLY. In staging / production, raises ValueError so
        startup fails fast.
        """
        # Order: validation reports the FIRST missing secret, so list
        # them in the order an operator most likely needs to know about.
        required: list[tuple[str, str]] = [
            ("database_url", _DEV_DATABASE_URL),
            ("encryption_key", _DEV_ENCRYPTION_KEY),
            ("session_secret", _DEV_SESSION_SECRET),
        ]
        for field, dev_default in required:
            if not getattr(self, field):
                if self.app_env == "development":
                    # Mutable BaseSettings — direct assignment is fine.
                    setattr(self, field, dev_default)
                else:
                    raise ValueError(
                        f"{field.upper()} is required when APP_ENV is "
                        f"{self.app_env!r}; set it explicitly in the environment."
                    )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings; safe to call from any module.

    The cache is process-local; tests that need a fresh Settings should
    call `get_settings.cache_clear()` first or instantiate `Settings(...)`
    directly.
    """
    return Settings()
