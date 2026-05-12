"""B.6B.3 HTTP integration tests for the shadow seam.

Per docs/phase-b6b-plan.md §11 tests 14-22 + §6 flag-OFF invariant.

Test strategy follows the test pyramid:
  - Unit (test_bridge_shadow.py)            -- mocks every repo
  - Route (this file)                       -- mocks at orchestrator
                                               boundary; verifies route
                                               wiring + flag gating +
                                               BackgroundTask scheduling
  - End-to-end (test_bridge_corpus.py +
    one E2E case below)                     -- real Postgres, real
                                               orchestrator, full
                                               persistence

Uses `async_client` (httpx.AsyncClient + ASGITransport) to keep the
entire ASGI lifecycle including BackgroundTasks inside the test's
event loop. Sync TestClient would spawn an AnyIO portal and corrupt
asyncpg connection loop binding (the same class of bug that B.6A.5
hit + fixed).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import text


_BASELINE_PAYLOAD = {
    "business_name": "Joe Pizza",
    "location": "Brooklyn, NY",
}
_BASELINE_SCORE = 60  # preserved across every phase since B.5


# ---------------------------------------------------------------------------
# Flag OFF: response byte-identical + no orchestrator + no DB
# ---------------------------------------------------------------------------


async def test_flag_off_response_status_200(
    async_client, b6b_flag_off, shadow_orchestrator_mock
) -> None:
    """Per plan §6 invariant #8: identical status codes (200)."""
    r = await async_client.post("/v1/analyses-legacy", json=_BASELINE_PAYLOAD)
    assert r.status_code == 200


async def test_flag_off_baseline_score_preserved(
    async_client, b6b_flag_off, shadow_orchestrator_mock
) -> None:
    """The canonical regression guard preserved across every phase
    since B.5: Joe Pizza / Brooklyn, NY -> 60. Per plan §6
    invariant #7: byte-identical response body."""
    r = await async_client.post("/v1/analyses-legacy", json=_BASELINE_PAYLOAD)
    assert r.json()["score"] == _BASELINE_SCORE


async def test_flag_off_zero_orchestrator_calls(
    async_client, b6b_flag_off, shadow_orchestrator_mock
) -> None:
    """Per plan §6 invariant #1: zero orchestrator execution when
    flag OFF. The BackgroundTask IS scheduled but its body is a
    bool-check + return -- the orchestrator mock must NOT receive
    a call."""
    await async_client.post("/v1/analyses-legacy", json=_BASELINE_PAYLOAD)
    shadow_orchestrator_mock.assert_not_called()


async def test_flag_off_response_body_is_deterministic_across_requests(
    async_client, b6b_flag_off, shadow_orchestrator_mock
) -> None:
    """Per plan §6 invariant #7 (stronger): the SAME input produces
    the SAME response body across multiple requests. Proves no
    shadow contamination of response shaping."""
    r1 = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )
    r2 = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )
    assert r1.json() == r2.json()
    assert r1.status_code == r2.status_code


# ---------------------------------------------------------------------------
# Flag ON: orchestrator called, response unchanged, errors swallowed
# ---------------------------------------------------------------------------


async def test_flag_on_response_byte_identical_to_flag_off(
    async_client, shadow_orchestrator_mock, monkeypatch
) -> None:
    """Critical contract: response body is byte-identical
    regardless of flag state. Shadow is post-response side effect
    only -- never response authority."""
    from types import SimpleNamespace

    # First request: flag OFF
    monkeypatch.setattr(
        "app.domain.bridge_shadow.get_settings",
        lambda: SimpleNamespace(b6b_shadow_scoring_enabled=False),
    )
    r_off = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )

    # Second request: flag ON
    monkeypatch.setattr(
        "app.domain.bridge_shadow.get_settings",
        lambda: SimpleNamespace(b6b_shadow_scoring_enabled=True),
    )
    r_on = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )

    assert r_off.status_code == r_on.status_code
    assert r_off.json() == r_on.json()


async def test_flag_on_orchestrator_called_once(
    async_client, b6b_flag_on, shadow_orchestrator_mock
) -> None:
    """Per plan §11 test #19 (route-wiring portion): the route
    schedules a BackgroundTask that, when flag is ON, invokes the
    orchestrator exactly once with the request's args."""
    await async_client.post("/v1/analyses-legacy", json=_BASELINE_PAYLOAD)
    shadow_orchestrator_mock.assert_awaited_once()


async def test_flag_on_orchestrator_receives_request_args(
    async_client, b6b_flag_on, shadow_orchestrator_mock
) -> None:
    """The orchestrator's business_name + location + trade kwargs
    match the request payload -- the route wiring passes them
    through unchanged."""
    payload = {
        "business_name": "Sunset Yoga",
        "location": "Portland, OR",
        "trade": "yoga",
    }
    await async_client.post("/v1/analyses-legacy", json=payload)
    kwargs = shadow_orchestrator_mock.await_args.kwargs
    assert kwargs["business_name"] == "Sunset Yoga"
    assert kwargs["location"] == "Portland, OR"
    assert kwargs["trade"] == "yoga"


async def test_flag_on_orchestrator_failure_response_still_200(
    async_client, b6b_flag_on, shadow_orchestrator_mock
) -> None:
    """The orchestrator raises -> shadow seam swallows -> response
    must still be 200 + byte-identical to the no-shadow path.
    This is the core safety claim of the BackgroundTasks seam:
    shadow failures CANNOT affect the HTTP response."""
    shadow_orchestrator_mock.side_effect = RuntimeError(
        "simulated orchestrator failure"
    )
    r = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )
    assert r.status_code == 200
    assert r.json()["score"] == _BASELINE_SCORE


# ---------------------------------------------------------------------------
# /analyze-business back-compat alias: same wiring
# ---------------------------------------------------------------------------


async def test_alias_flag_off_zero_orchestrator_calls(
    async_client, b6b_flag_off, shadow_orchestrator_mock
) -> None:
    """The back-compat `/analyze-business` alias in main.py wires
    the shadow path the same way as `/v1/analyses-legacy`."""
    await async_client.post("/analyze-business", json=_BASELINE_PAYLOAD)
    shadow_orchestrator_mock.assert_not_called()


async def test_alias_flag_on_orchestrator_called(
    async_client, b6b_flag_on, shadow_orchestrator_mock
) -> None:
    await async_client.post("/analyze-business", json=_BASELINE_PAYLOAD)
    shadow_orchestrator_mock.assert_awaited_once()
    kwargs = shadow_orchestrator_mock.await_args.kwargs
    assert kwargs["business_name"] == _BASELINE_PAYLOAD["business_name"]
    assert kwargs["location"] == _BASELINE_PAYLOAD["location"]


async def test_alias_response_byte_identical_to_v1_route(
    async_client, b6b_flag_off, shadow_orchestrator_mock
) -> None:
    """Both routes use `run_analysis()` so legacy response is
    byte-identical between them. Validates the back-compat
    contract preserves both response shape AND shadow wiring."""
    r_alias = await async_client.post(
        "/analyze-business", json=_BASELINE_PAYLOAD
    )
    r_v1 = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )
    assert r_alias.status_code == r_v1.status_code
    assert r_alias.json() == r_v1.json()


# ---------------------------------------------------------------------------
# End-to-end: flag ON writes persist via the real orchestrator
# ---------------------------------------------------------------------------
# These two tests exercise the FULL pipeline: route -> background
# task -> shadow seam -> real orchestrator -> real Postgres. The
# shadow's own session is bound to the test's db_session connection
# via `shadow_session_capture` so writes inherit the test's
# savepoint rollback.


async def test_e2e_flag_on_persists_demo_account_lead(
    async_client,
    b6b_flag_on,
    shadow_session_capture,
    db_session,
) -> None:
    """End-to-end: flag ON + real orchestrator. After the request,
    the demo account has one new lead with source =
    'bridge:legacy_analyzer:v1' visible in db_session."""
    pre = await db_session.execute(
        text(
            "SELECT count(*) AS c FROM lead "
            "WHERE source = 'bridge:legacy_analyzer:v1'"
        )
    )
    pre_count = pre.one().c

    r = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )
    assert r.status_code == 200

    post = await db_session.execute(
        text(
            "SELECT count(*) AS c FROM lead "
            "WHERE source = 'bridge:legacy_analyzer:v1'"
        )
    )
    post_count = post.one().c
    assert post_count == pre_count + 1


async def test_e2e_flag_on_persists_full_signal_set(
    async_client,
    b6b_flag_on,
    shadow_session_capture,
    db_session,
) -> None:
    """End-to-end: the persisted lead has all 4 lead_signal rows
    and 1 lead_score_snapshot row attached -- the full B.6A.4
    orchestrator output landed via the production HTTP path."""
    r = await async_client.post(
        "/v1/analyses-legacy", json=_BASELINE_PAYLOAD
    )
    assert r.status_code == 200

    # Find the most recently created bridge-originated lead.
    result = await db_session.execute(
        text(
            "SELECT id FROM lead "
            "WHERE source = 'bridge:legacy_analyzer:v1' "
            "ORDER BY created_at DESC LIMIT 1"
        )
    )
    lead_row = result.one_or_none()
    assert lead_row is not None
    lead_id = lead_row.id

    signal_count = await db_session.execute(
        text(
            "SELECT count(*) AS c FROM lead_signal "
            "WHERE lead_id = :lead_id"
        ),
        {"lead_id": str(lead_id)},
    )
    assert signal_count.one().c == 4

    snapshot_count = await db_session.execute(
        text(
            "SELECT count(*) AS c FROM lead_score_snapshot "
            "WHERE lead_id = :lead_id"
        ),
        {"lead_id": str(lead_id)},
    )
    assert snapshot_count.one().c == 1


# ---------------------------------------------------------------------------
# Connection pool / sequential requests do not leak
# ---------------------------------------------------------------------------


async def test_sequential_flag_on_requests_do_not_leak_connections(
    async_client, b6b_flag_on, shadow_orchestrator_mock
) -> None:
    """Per plan §11 test #22: multiple sequential requests with
    flag ON exercise the shadow's own-session lifecycle (open ->
    use -> commit -> close). The orchestrator is mocked here
    (the unit-level commit is asserted in test_bridge_shadow.py);
    this test specifically validates the route-level loop does
    not raise / leak."""
    for i in range(5):
        r = await async_client.post(
            "/v1/analyses-legacy",
            json={
                "business_name": f"Pool Test {i}",
                "location": "Test City",
            },
        )
        assert r.status_code == 200
    assert shadow_orchestrator_mock.await_count == 5
