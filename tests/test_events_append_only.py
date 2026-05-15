"""
tests/test_events_append_only.py

Day-1 Step 2 smoke verification: the canonical Phase_0_Execution_Blueprint.md
§22 Test 1 (Append-only event enforcement). Three behaviours under test:

    1. INSERT into events succeeds.
    2. UPDATE on events is rejected by the append-only trigger.
    3. DELETE on events is rejected by the append-only trigger.

Plus one structural check derived from Phase_0_Governance_and_Replayability.md
§"Append-only enforcement validation":

    4. Both expected append-only triggers exist and are in origin-enabled state.

Scope discipline:
    - No event model imports (Pydantic model lands Day-1 Step 4).
    - No emitter imports (emitter lands Day-1 Step 4).
    - Tests interact with the events table directly via psycopg, exercising
      the substrate's trigger contract — not application logic.

Isolation:
    - Tests open per-test connections and rollback at teardown. Successful
      INSERTs never commit, so the events table is left unchanged.
    - Trigger-rejection tests rely on the BEFORE trigger raising before the
      row reaches the table, so there is nothing to clean up.
    - The DB is bootstrapped once per session (apply_migrations + verify).

Environment:
    - DSN comes from TRUSIGNAL_TEST_DATABASE_URL if set, else falls back to
      TRUSIGNAL_DATABASE_URL (resolved by app.db.connection.get_dsn).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.db import connection as db


def _resolved_dsn() -> str:
    return os.environ.get("TRUSIGNAL_TEST_DATABASE_URL") or db.get_dsn()


@pytest.fixture(scope="session", autouse=True)
def bootstrap_substrate_db() -> None:
    """
    Apply migrations and verify append-only triggers exactly once per test
    session. If verification fails, the session aborts before any test runs.
    """
    db.bootstrap(dsn=_resolved_dsn())


@pytest.fixture()
def conn() -> psycopg.Connection:
    """
    Yield a connection in default (non-autocommit) mode. Rollback at teardown
    so successful INSERTs in tests do not persist.
    """
    c = psycopg.connect(_resolved_dsn())
    try:
        yield c
    finally:
        try:
            c.rollback()
        finally:
            c.close()


def _sample_event(event_id: uuid.UUID | None = None) -> dict:
    """Build a minimal valid event row. No emitter, no Pydantic — direct dict."""
    now = datetime.now(timezone.utc)
    return {
        "event_id": event_id or uuid.uuid4(),
        "event_type": "test.smoke",
        "aggregate_type": "test_aggregate",
        "aggregate_id": uuid.uuid4(),
        "payload": json.dumps({"smoke": True}),
        "schema_version": "0.0.1",
        "occurred_at": now,
        "recorded_at": now,
        "actor_type": "test",
        "actor_id": "append-only-smoke",
        "causation_id": None,
        "correlation_id": None,
    }


_INSERT_SQL = """
INSERT INTO events (
    event_id, event_type, aggregate_type, aggregate_id,
    payload, schema_version, occurred_at, recorded_at,
    actor_type, actor_id, causation_id, correlation_id
) VALUES (
    %(event_id)s, %(event_type)s, %(aggregate_type)s, %(aggregate_id)s,
    %(payload)s::jsonb, %(schema_version)s, %(occurred_at)s, %(recorded_at)s,
    %(actor_type)s, %(actor_id)s, %(causation_id)s, %(correlation_id)s
)
"""


# ---------------------------------------------------------------------------
# Blueprint §22 Test 1 — Append-only event enforcement
# ---------------------------------------------------------------------------


def test_insert_into_events_succeeds(conn: psycopg.Connection) -> None:
    event = _sample_event()
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, event)
        cur.execute(
            "SELECT event_id, event_type FROM events WHERE event_id = %s",
            (event["event_id"],),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == event["event_id"]
    assert row[1] == "test.smoke"


def test_update_on_events_is_rejected(conn: psycopg.Connection) -> None:
    event = _sample_event()
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, event)
        with pytest.raises(psycopg.errors.RaiseException) as excinfo:
            cur.execute(
                "UPDATE events SET event_type = 'mutated' WHERE event_id = %s",
                (event["event_id"],),
            )
    assert "append_only_violation" in str(excinfo.value)


def test_delete_on_events_is_rejected(conn: psycopg.Connection) -> None:
    event = _sample_event()
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, event)
        with pytest.raises(psycopg.errors.RaiseException) as excinfo:
            cur.execute(
                "DELETE FROM events WHERE event_id = %s",
                (event["event_id"],),
            )
    assert "append_only_violation" in str(excinfo.value)


def test_truncate_on_events_is_rejected(conn: psycopg.Connection) -> None:
    """
    TRUNCATE does not fire row-level UPDATE/DELETE triggers; the substrate
    relies on a statement-level BEFORE TRUNCATE trigger to keep the event log
    truly insert-only. This test exercises that path with no rows present —
    the trigger fires unconditionally on the TRUNCATE statement itself.
    """
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException) as excinfo:
            cur.execute("TRUNCATE events")
    assert "append_only_violation" in str(excinfo.value)
    assert "TRUNCATE" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Governance & Replayability §"Append-only enforcement validation"
# ---------------------------------------------------------------------------


def test_expected_append_only_triggers_are_present_and_enabled(
    conn: psycopg.Connection,
) -> None:
    """Mirror of the startup verification: both triggers present, tgenabled='O'."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tgname, tgenabled
            FROM pg_trigger
            WHERE tgname LIKE '%append_only%'
              AND NOT tgisinternal
            ORDER BY tgname
            """,
        )
        rows = cur.fetchall()
    by_name = {name: status for name, status in rows}

    for expected in db.EXPECTED_APPEND_ONLY_TRIGGERS:
        assert expected in by_name, f"missing trigger: {expected}"
        assert by_name[expected] == "O", (
            f"trigger {expected} not in origin-enabled state (got {by_name[expected]!r})"
        )
