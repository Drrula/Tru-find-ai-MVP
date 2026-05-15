"""
app.db.connection — TruSignalAI Phase 0 substrate database bootstrap.

Responsibilities (Day-1 Step 2 scope only):
    - Resolve the substrate DSN from environment (TRUSIGNAL_DATABASE_URL),
      with a local-docker default.
    - Apply pending numbered SQL migrations from app/db/migrations/, in order,
      each in its own transaction, recorded in schema_migrations.
    - Verify expected append-only triggers are present and enabled. Refuse to
      proceed on any deviation (loud failure, never silent degradation).

Locked references:
    - Phase_0_Execution_Blueprint.md §4  (psycopg, Python 3.11+)
    - Phase_0_Execution_Blueprint.md §7  (append-only enforcement on events)
    - Phase_0_Execution_Blueprint.md §19 (Day 1 deliverables 4–5)
    - Phase_0_Governance_and_Replayability.md §"Append-only enforcement
      validation" (startup trigger-presence check; loud refusal)
    - Phase_0_Governance_Reconciliation.md ruling D2 / finding F-H5
      (events-only enforcement scope)

Out of scope for Day-1 Step 2 (do NOT add here):
    - Event model (Pydantic) — Day-1 Step 4, app/events/models.py
    - Emitter — Day-1 Step 4, app/events/emitter.py
    - Replay runner — Day-1 Step 4, app/events/replay.py
    - Projectors — Day-1 Step 5, app/entities/projectors.py
    - Ontology, scoring, indicators, evidence, CLI — later days.
"""

from __future__ import annotations

import os
import pathlib

import psycopg

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Local docker-compose default. Production / staging values come from
#: TRUSIGNAL_DATABASE_URL. Host port 5433 because the legacy backend already
#: binds 5432 via infra/dev/docker-compose.yml.
DEFAULT_DSN: str = "postgresql://trusignal:trusignal@localhost:5433/trusignal"

#: Trigger names that the startup verification expects to find present and
#: enabled. The naming convention contains "append_only" so the verification
#: query's `tgname LIKE '%append_only%'` predicate (per Governance &
#: Replayability §"Append-only enforcement validation") matches them.
#:
#: Coverage:
#:   - update / delete : row-level (BEFORE UPDATE / BEFORE DELETE)
#:   - truncate        : statement-level (BEFORE TRUNCATE FOR EACH STATEMENT) —
#:                       closes the TRUNCATE bypass path that row-level
#:                       triggers do not cover.
EXPECTED_APPEND_ONLY_TRIGGERS: tuple[str, ...] = (
    "events_append_only_update",
    "events_append_only_delete",
    "events_append_only_truncate",
)

#: Directory holding numbered .sql migrations. Resolved relative to this file
#: so it works regardless of CWD.
MIGRATIONS_DIR: pathlib.Path = pathlib.Path(__file__).parent / "migrations"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AppendOnlyTriggerViolation(RuntimeError):
    """
    Raised when expected append-only triggers are missing or disabled.

    This is a substrate-integrity failure. Per Phase_0_Governance_and_
    Replayability.md §"Append-only enforcement validation", the substrate
    must refuse to start in this condition; silent degradation is forbidden.
    """


# ---------------------------------------------------------------------------
# DSN / connection
# ---------------------------------------------------------------------------


def get_dsn() -> str:
    """Resolve the substrate DSN. Reads TRUSIGNAL_DATABASE_URL, else default."""
    return os.environ.get("TRUSIGNAL_DATABASE_URL", DEFAULT_DSN)


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Open a new connection to the substrate database."""
    return psycopg.connect(dsn or get_dsn())


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------
#
# Convention:
#   - Files live in app/db/migrations/.
#   - Filenames are sorted lexicographically (use zero-padded prefixes:
#     001_*.sql, 002_*.sql, ...).
#   - The filename stem (without .sql) is the migration "version" recorded in
#     schema_migrations.
#   - Each migration runs in its own transaction. If a migration raises, the
#     transaction is rolled back and the runner re-raises. Already-applied
#     migrations are skipped.
#
# The runner is deliberately minimal: no DSL, no down-migrations, no version
# graph. Anti-cathedral discipline (Blueprint §25).
# ---------------------------------------------------------------------------


def _ensure_schema_migrations_table(conn: psycopg.Connection) -> None:
    """Create the migration-tracking table if it does not exist."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     TEXT        PRIMARY KEY,
                    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _applied_versions(conn: psycopg.Connection) -> set[str]:
    """Return the set of migration versions already recorded as applied."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            rows = cur.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {row[0] for row in rows}


def _pending_migrations(applied: set[str]) -> list[pathlib.Path]:
    """List numbered .sql migrations not yet applied, in lexicographic order."""
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.stem not in applied]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """
    Apply pending migrations in order. Returns the list of newly-applied
    versions. Each migration runs in its own transaction.
    """
    _ensure_schema_migrations_table(conn)
    applied = _applied_versions(conn)
    newly_applied: list[str] = []
    for path in _pending_migrations(applied):
        version = path.stem
        sql = path.read_text(encoding="utf-8")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        newly_applied.append(version)
    return newly_applied


# ---------------------------------------------------------------------------
# Trigger verification
# ---------------------------------------------------------------------------


def verify_append_only_triggers(conn: psycopg.Connection) -> None:
    """
    Refuse to proceed if expected append-only triggers are missing or disabled.

    Per Phase_0_Governance_and_Replayability.md §"Append-only enforcement
    validation": this check must run at application startup. Trigger state is
    a substrate-integrity invariant; missing or disabled triggers cause loud
    refusal, never silent degradation.

    pg_trigger.tgenabled values:
        'O' — origin/local (enabled in normal operation)        ← required
        'D' — disabled
        'R' — replica (fires only on replica)
        'A' — always (fires on origin and replica)
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tgname, tgenabled
                FROM pg_trigger
                WHERE tgname LIKE '%append_only%'
                  AND NOT tgisinternal
                """,
            )
            rows = cur.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    by_name: dict[str, str] = {name: status for name, status in rows}

    missing = [name for name in EXPECTED_APPEND_ONLY_TRIGGERS if name not in by_name]
    if missing:
        raise AppendOnlyTriggerViolation(
            "Expected append-only triggers are missing: "
            f"{missing}. Substrate refuses to start. Re-run migrations or "
            "investigate manual schema changes."
        )

    disabled = [
        name for name in EXPECTED_APPEND_ONLY_TRIGGERS if by_name[name] != "O"
    ]
    if disabled:
        raise AppendOnlyTriggerViolation(
            "Expected append-only triggers are present but not in origin-enabled "
            f"state (tgenabled != 'O'): {disabled}. Substrate refuses to start. "
            "Re-enable triggers and investigate why they were disabled — per "
            "Phase_0_Governance_and_Replayability.md replay-breaking mistake #3."
        )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def bootstrap(dsn: str | None = None) -> list[str]:
    """
    Substrate DB bootstrap: apply pending migrations, then verify append-only
    enforcement. Refuses to return if either step fails.

    Returns the list of newly-applied migration versions (empty if nothing
    was pending).
    """
    conn = connect(dsn)
    try:
        newly_applied = apply_migrations(conn)
        verify_append_only_triggers(conn)
    finally:
        conn.close()
    return newly_applied
