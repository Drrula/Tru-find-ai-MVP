# Phase B.2 — Implementation Plan (identity + magic-link auth)

| Field | Value |
|---|---|
| Status | **Planning locked, B.2.1 unblocked on `proceed B.2.1`** |
| Date | 2026-05-10 |
| Scope of B.2 | `user` + `session` + `magic_link_token` tables · their ORM models + repositories · AES-GCM crypto for PII (per ADR-013) · magic-link request/consume domain layer · auth routes (`/v1/auth/*`) + `get_current_user` FastAPI dependency · session cookie wiring · self-signup model (first valid magic-link consume creates account + user + session) |
| Out of scope for B.2 | Auth-gating any existing route (`/v1/analyses-legacy` etc. stay open); real email provider integration (LoggingEmailSender stub only); per-email rate limiting; MFA; SSO; API tokens; password fallback; sliding session refresh; admin RBAC enforcement |
| Supersedes | none. Extends `docs/phase-b-plan.md` (Phase B foundations); inherits all its locks |

---

## 1. Inheritance

Carries forward unchanged:

- All of `docs/phase-b-plan.md` §1–§11 (topology, async SQLAlchemy, alembic strategy, repository pattern, env-var contract baseline, backup/PITR posture, rollback expectations).
- All Blocking ADRs from the architecture lock — particularly:
  - **ADR-008** tenancy (`account_id NOT NULL` on every owned/derived table; `user.account_id` is the first concrete instance).
  - **ADR-013** PII (`(hash, encrypted)` for email; ENCRYPTION_KEY required in non-dev).
  - **ADR-015** audit_log (privileged auth operations log to structlog now; `audit_log` table writes land when the table comes online — system-table phase).
  - **ADR-016** soft-delete on user; `magic_link_token` and `session` use explicit `consumed_at` / `revoked_at` semantics instead.
  - **ADR-018** DIY magic-link auth, with `external_auth_id` reserved for the future hosted-provider escape hatch (the column lands in B.2 even though no value is set yet).
  - **ADR-031** repository pattern (every read/write through repos).
  - **ADR-032** idempotency keys (magic_link_token's `token_hash` is the idempotency key — UNIQUE).

---

## 2. Decisions locked for B.2

| # | Question | Locked answer |
|---|---|---|
| 1 | Session storage model | **DB-backed `session` rows + signed HttpOnly cookie carrying `session.id`.** The cookie is the bearer; the row is the source of truth (revocable, expirable). |
| 2 | Cookie name | `trufindai_session` |
| 3 | Cookie security | `HttpOnly=True`, `SameSite=Lax`, `Secure=True` in staging/production (controlled by `APP_ENV`); `Secure=False` in dev so localhost works |
| 4 | Session TTL | **30 days** absolute (no sliding refresh in B.2). Configurable via new `SESSION_TTL_DAYS` env var (default 30). |
| 5 | Magic-link TTL | 15 min (already in Settings: `MAGIC_LINK_TOKEN_TTL_MIN=15`) |
| 6 | Magic-link consume model | **Self-signup.** First successful consume of a token whose email_hash has no `user` row creates: `account` (display_name = local part of email), `user` (account_id = new account, role = `owner`), `session`. Subsequent consumes for an existing email reuse the user/account and create only a new `session`. |
| 7 | Email-enumeration protection | **`/v1/auth/request` always returns 200**, regardless of whether the email exists, the rate limit fires, or the email send fails. Existence/state is never leaked through the response. |
| 8 | Email provider | **`LoggingEmailSender` stub only in B.2.** Writes the magic-link URL to structlog; operator copies it from logs in dev or watches log shipping in staging. Real provider (Resend / SendGrid / SES — separate decision §5.X) lands in a follow-up commit, behind an `EmailSender` Protocol so the swap is one DI change. |
| 9 | PII encryption | **AES-GCM** via `cryptography` library. Key in `ENCRYPTION_KEY` env var (32 bytes, base64-encoded). Dev default: hardcoded constant clearly marked DEV ONLY (matches the docker-compose pattern from B.1.1). Staging/production: required, fail-fast at startup if unset. |
| 10 | Email hash for lookup | `sha256(lower(strip(email)).encode("utf-8"))` → 32 bytes. Stable across environments (no per-env salt) so the same email maps to the same hash everywhere — needed for cross-env data migration if it ever happens. |
| 11 | Per-email rate limit on `/v1/auth/request` | **Deferred.** Existing in-process IP-based rate limit (B.0.1 middleware) is the only gate in B.2. Per-email rate limit lands in a future commit when abuse is observed. |
| 12 | Auth-gating existing routes | **Deferred.** `/v1/health`, `/v1/analyses-legacy`, `/analyze-business` alias remain unauthenticated in B.2. Adding `Depends(get_current_user)` to any of them is its own commit with its own behavior change. |
| 13 | Admin RBAC enforcement | **Deferred.** `user.role` column exists with the CHECK constraint, but no endpoint enforces a specific role. Lands when an admin-only endpoint exists. |
| 14 | Audit log writes | **Stubbed via structlog** in B.2 (privileged operations log structured events). Real `audit_log` table writes wired when the table comes online (system-table phase). Hooks designed so that wiring is a single-call addition per privileged path. |

---

## 3. Schema (re-stated from ARCHITECTURE-LOCK §2.3)

Three new tables. All inherit `account_id NOT NULL` discipline (per ADR-008) — for `user` directly; for `session` via the user; `magic_link_token` is pre-account-binding (the consume step is what binds it to an account).

### user

```sql
user (
  id                    uuid PK,
  account_id            uuid NOT NULL REFERENCES account(id),
  email_hash            bytea NOT NULL,
  email_encrypted       bytea NOT NULL,
  display_name          text,
  external_auth_id      text NULL,                    -- ADR-018 escape hatch
  role                  text NOT NULL DEFAULT 'owner'
                        CHECK (role IN ('owner','admin','member')),
  last_login_at         timestamptz,
  created_at, updated_at, deleted_at
)
UNIQUE (email_hash) WHERE deleted_at IS NULL
INDEX (account_id)
```

### session

```sql
session (
  id                    uuid PK,
  user_id               uuid NOT NULL REFERENCES user(id),
  account_id            uuid NOT NULL,                -- denormalized from user; matches Lock §2.1
  issued_at             timestamptz NOT NULL,
  expires_at            timestamptz NOT NULL,
  revoked_at            timestamptz NULL,             -- soft-revoke; explicit semantics, not deleted_at
  ip_hash               bytea,                        -- sha256 for forensics; never IP plaintext
  user_agent            text                          -- truncated to 256 chars at write time
)
INDEX (user_id, expires_at)
```

### magic_link_token

```sql
magic_link_token (
  id                    uuid PK,
  email_hash            bytea NOT NULL,
  email_encrypted       bytea NOT NULL,               -- B.2.2-amend: AES-256-GCM ciphertext; consume decrypts to recover plaintext for self-signup
  token_hash            bytea NOT NULL UNIQUE,        -- sha256(plaintext_token); plaintext only in the email
  issued_at             timestamptz NOT NULL,
  expires_at            timestamptz NOT NULL,
  consumed_at           timestamptz NULL,
  ip_hash               bytea
)
INDEX (token_hash) WHERE consumed_at IS NULL
```

> **B.2.2-amend note:** `email_encrypted` was added by migration 0006
> (`0006_magic_link_token_email_encrypted`) after B.2.2 shipped. A design
> gap surfaced during B.2.3 planning: the consume flow (§4 below)
> needs the plaintext email to populate `user.email_encrypted` and
> `account.display_name = local part of email` on self-signup, but the
> consume URL only carries the opaque token. Storing the ciphertext on
> the magic_link_token row at issue time keeps the email out of URLs
> (per ADR-013) while letting consume recover the plaintext. The amend
> was safe as a NOT NULL add because B.2.2 had not deployed past local
> dev yet.

### Tenancy notes

- `user.account_id` is the FIRST table that enforces tenancy filtering through `BaseRepository`. The B.1.5 introspection logic auto-detects the column and applies the WHERE clause.
- `session.account_id` is denormalized from `user` so reads of session-bound data don't need a join. Set at session creation; never updated.
- `magic_link_token` is intentionally pre-account: it carries `email_hash` only. The consume step resolves the email to an existing user (if any) and creates the session bound to that account, OR self-signs-up a new account (per decision #6).

---

## 4. Auth flow

```
Request a link
  → POST /v1/auth/request {"email": "..."}
  → backend computes email_hash + email_encrypted (AES-256-GCM via app.core.crypto.encrypt)
  → mints plaintext_token (32 bytes urlsafe via secrets.token_urlsafe(32))
  → INSERT magic_link_token (email_hash, email_encrypted, token_hash = sha256(plaintext_token))
  → LoggingEmailSender.send(email, link) — link = f"{frontend_origin}/auth/consume?token={plaintext_token}"
  → return 200 always (decision #7)

Consume a link
  → GET /v1/auth/consume?token=<plaintext>
  → backend computes token_hash = sha256(plaintext)
  → SELECT magic_link_token WHERE token_hash=:h AND consumed_at IS NULL AND expires_at > now()
  → if not found: 401 (or 200 with redirect to /login?error=expired — TBD per frontend)
  → mark consumed_at = now()
  → decrypt token.email_encrypted -> plaintext_email (per B.2.2-amend, see §3 note)
  → resolve user by email_hash (UserRepository.find_by_email_hash, force_cross_account=True):
      if exists: reuse user + account
      if not exists: create account (display_name = local-part-of-plaintext_email)
                    + user (account_id = new account, role = owner,
                            email_hash = token.email_hash,
                            email_encrypted = token.email_encrypted)
  → INSERT session (user_id, account_id, issued_at, expires_at, ip_hash, user_agent)
  → set HttpOnly Secure-in-prod cookie "trufindai_session" with session.id (signed by SESSION_SECRET)
  → return 200 with user info (or redirect to frontend root)

Use the session
  → any request with cookie "trufindai_session"
  → middleware validates signature → loads session row by id
  → if revoked_at IS NOT NULL or expires_at < now(): clear cookie, return 401
  → else: set request.state.user = User row, request.state.account_id = Account row
  → handlers receive User via Depends(get_current_user)

Logout
  → POST /v1/auth/logout
  → mark session.revoked_at = now()
  → clear cookie
  → return 200

Current user
  → GET /v1/auth/me
  → returns {user_id, account_id, role, display_name, email_masked}
  → email_masked = "j***@example.com" (UI display; never the full plaintext over the wire on this route)
```

---

## 5. Crypto module design (`app.core.crypto`)

Single file. Two pure functions:

```python
def hash_for_lookup(value: str) -> bytes:
    """sha256(lower(strip(value)).encode("utf-8")) → 32 bytes. Stable across envs."""

def encrypt(plaintext: str) -> bytes:
    """AES-256-GCM. Output: nonce(12) + ciphertext + tag. Key from ENCRYPTION_KEY."""

def decrypt(ciphertext: bytes) -> str:
    """Inverse of encrypt. Raises on tag mismatch."""
```

- `cryptography` library (`AESGCM` from `cryptography.hazmat.primitives.ciphers.aead`).
- Key loaded from `Settings.encryption_key` (base64-decoded).
- Dev key: hardcoded `b"\x00" * 32` constant, with a comment that says NEVER use this in non-dev. The Settings validator checks that `APP_ENV != development` requires a real ENCRYPTION_KEY.

Tests verify round-trip (`decrypt(encrypt(x)) == x`), tamper detection (mutated ciphertext raises), hash determinism.

---

## 6. Cookie + session details

| Field | Value |
|---|---|
| Name | `trufindai_session` |
| HttpOnly | `True` always (no JS access) |
| Secure | `True` when `APP_ENV in {"staging","production"}`; `False` in `development` |
| SameSite | `Lax` |
| Path | `/` |
| Max-Age | `session.expires_at - now()` in seconds |
| Domain | unset (defaults to current host) |
| Value | `f"{session_id}.{signature}"` where signature = HMAC-SHA256 of `session_id` using `SESSION_SECRET` |

`SESSION_SECRET` joins `ENCRYPTION_KEY` and `DATABASE_URL` as a non-dev-required env var (Settings validator handles all three identically per pattern).

---

## 7. Email stub posture

`app.domain.notifications.email.LoggingEmailSender` implements an `EmailSender` Protocol:

```python
class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body_text: str) -> None: ...
```

Default implementation: emit a structlog `info` line with `to`, `subject`, and the magic-link URL. Operator reads the line from `docker compose logs api` in dev or from log shipping in staging.

A real implementation (e.g. `ResendEmailSender`) lands in a separate commit when:
- A provider is chosen (currently a deferred decision; possibly §5.X — needs a new outstanding decision row).
- The 10DLC-equivalent posture for email (DKIM/SPF/DMARC for the sender domain) is settled.

Until then, `LoggingEmailSender` is the active publisher.

---

## 8. Env-var contract additions in B.2

| Var | Required when | Default in dev |
|---|---|---|
| `ENCRYPTION_KEY` | `APP_ENV != "development"` | hardcoded zero-key constant (clearly marked DEV ONLY) |
| `SESSION_SECRET` | `APP_ENV != "development"` | hardcoded constant `"dev-session-secret"` |
| `SESSION_TTL_DAYS` | optional always | `30` |
| `MAGIC_LINK_TOKEN_TTL_MIN` | optional always | `15` (already in Settings since B.0.1) |

`backend/app/core/config.py` `Settings._resolve_database_url` validator extends to also enforce `ENCRYPTION_KEY` and `SESSION_SECRET` on staging / production startup.

`.env.example` and `infra/railway/staging.env.template` / `production.env.template` already list `SESSION_SECRET` and `ENCRYPTION_KEY` — no template change needed beyond confirming the Railway dashboard values are set before B.2 deploys to staging.

---

## 9. Sub-task breakdown

Each sub-task is one commit, verify-then-commit per the locked phase-gating rule.

| Sub | Title | Files | Verifies |
|---|---|---|---|
| **B.2.0** | Phase B.2 planning doc | `docs/phase-b2-plan.md` (this file) | Plan exists; future commits trace to it |
| **B.2.1** | Crypto module + ENCRYPTION_KEY/SESSION_SECRET validators + `LoggingEmailSender` stub | `backend/app/core/crypto.py` (new), `backend/app/core/config.py` (extend validator), `backend/app/domain/notifications/__init__.py` (new), `backend/app/domain/notifications/email.py` (new EmailSender Protocol + LoggingEmailSender), `backend/tests/test_core_crypto.py`, `backend/tests/test_notifications_email.py`. Adds `cryptography` dep to pyproject. | Round-trip encryption · hash determinism · tamper detection · validator raises in non-dev without keys · LoggingEmailSender emits structured line. Existing 105/105 tests still pass. |
| **B.2.2** | Migrations 0003–0005 + ORM models + repositories | `backend/alembic/versions/0003_user.py`, `0004_session.py`, `0005_magic_link_token.py` · `backend/app/db/models/user.py`, `session.py`, `magic_link_token.py` (and `__init__.py` re-exports) · `backend/app/db/repositories/user_repo.py`, `session_repo.py`, `magic_link_token_repo.py` · `backend/tests/test_user_model.py`, `test_session_model.py`, `test_magic_link_token_model.py`, `test_user_repo.py`, `test_session_repo.py`, `test_magic_link_token_repo.py` | Models match Lock §2.3 column-by-column · partial unique index on `user.email_hash WHERE deleted_at IS NULL` · partial index on `magic_link_token.token_hash WHERE consumed_at IS NULL` · repos enforce tenancy where applicable (UserRepository inherits BaseRepository defaults — first repo with `account_id` filter actually firing) · migrations parse + chain correctly |
| **B.2.3** | Auth domain layer (`app.domain.auth`) | `backend/app/domain/auth/__init__.py` (new), `backend/app/domain/auth/issue.py` (issue_magic_link), `backend/app/domain/auth/consume.py` (consume_magic_link with self-signup), `backend/app/domain/auth/sessions.py` (revoke), `backend/app/core/config.py` (add SESSION_TTL_DAYS field if not already), `backend/tests/test_auth_domain.py` | Issue: writes magic_link_token row + calls EmailSender · Consume: validates token, creates user+account+session on first email, reuses on subsequent · Revoke: marks session.revoked_at · Behavior tests use mock session + mock email sender |
| **B.2.4** | Auth routes + `get_current_user` dependency + cookie wiring | `backend/app/api/v1/auth.py` (POST /request, GET /consume, POST /logout, GET /me), `backend/app/api/v1/__init__.py` (include auth router), `backend/app/api/deps.py` (new — `get_current_user`, signed-cookie helpers), `backend/tests/test_auth_routes.py` | Requests return 200 (no email enumeration) · Consume sets HttpOnly cookie · /me returns current user when cookie present · /me returns 401 when cookie absent · /logout clears cookie + revokes session |

5 commits total. Each independently revertible.

---

## 10. What B.2 explicitly does NOT do

- Does not gate existing routes (`/v1/health`, `/v1/analyses-legacy`, `/analyze-business`) behind auth. Those stay open. Adding `Depends(get_current_user)` to any of them is a separate commit with its own behavior change.
- Does not implement a real email provider. `LoggingEmailSender` is the only sender in B.2; real provider is a follow-up.
- Does not implement per-email rate limiting on `/v1/auth/request`. In-process IP rate limit (B.0.1) is the only gate.
- Does not implement MFA / SSO / OAuth / passwords. ADR-018: passwordless magic-link, with hosted-provider as the future escape hatch (column reserved, not used in B.2).
- Does not enforce `user.role` anywhere. Stored, not gated. Lands when an admin-only endpoint exists.
- Does not write to an `audit_log` table — the table doesn't exist yet (system-table phase). Privileged auth operations log via structlog; the call sites are designed so wiring `audit_log.record(...)` is a single-call addition when the table comes online.
- Does not implement sliding session refresh. Absolute 30-day TTL only. Refresh logic lands when UX feedback demands it.
- Does not implement API tokens / bearer tokens for non-browser clients. Cookie-based only in B.2.

---

## 11. Cross-phase implications activated by B.2

When B.2 lands:

- **Tenancy filtering is exercised for the first time.** B.1.5's `BaseRepository._has_account_id_column` was True for no model (Account is the tenancy root). B.2 introduces three models with `account_id`. Bugs in the tenancy filter surface here.
- **PII columns in real use.** ADR-013 `(hash, encrypted)` pattern actually carries data for the first time. The encryption key rotation story becomes load-bearing.
- **PITR on staging Postgres becomes recommended.** Per B.1.0 §7: "Staging PITR required before B.2 auth tables land." Andrew should enable PITR on Railway staging Postgres before B.2.2 is deployed.
- **`get_current_user` dependency available** for any B.X+ route that wants auth-gating (none in B.2 itself).

---

## 12. Pre-flight items for Andrew (between now and `proceed B.2.1`)

- [ ] Confirm the 14 decisions in §2 (or override any).
- [ ] Confirm sub-task ordering in §9 (or rebundle).
- [ ] Confirm scope deferrals in §10 (especially the no-real-email-provider call).
- [ ] Operational: enable PITR on Railway staging Postgres before B.2.2 deploys (per §11).

## 13. Sign-off / next gate

| Action | Requires |
|---|---|
| Commit this plan | (this commit) |
| Push | `push` |
| Begin B.2.1 (crypto + email stub + validator extensions) | `proceed B.2.1` |
| Override any decision in §2 | reply with override + revised `proceed B.2.0-amend` |

No auto-proceed beyond this planning commit.
