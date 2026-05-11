"""B.3.7 tests for `/v1/account/export` 501 stub (per ADR-047).

Three layers covered:
  1. Auth gating: unauthenticated POST returns 401 (the
     `get_current_user` dependency handles this before the route).
  2. 501 body shape: authenticated POST returns 501 with the
     documented `error` + `schema_version` + `contents_when_implemented`
     surface.
  3. OpenAPI: the path + 501 response are documented in the schema.
"""

from __future__ import annotations

from typing import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_session
from app.main import app


def _make_user() -> User:
    return User(
        id=uuid4(),
        account_id=uuid4(),
        email_hash=b"\x00" * 32,
        email_encrypted=b"\x00" * 64,
        display_name="Alice",
        role="owner",
    )


@pytest.fixture
def mock_async_session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.rollback = AsyncMock()
    return s


@pytest.fixture
def client(mock_async_session: AsyncMock) -> Iterator[TestClient]:
    """TestClient with `get_session` overridden so route handlers that
    depend on it don't try to open a real DB connection."""

    async def _fake_get_session():
        yield mock_async_session

    app.dependency_overrides[get_session] = _fake_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def authenticated_client() -> Iterator[tuple[TestClient, User]]:
    """TestClient with `get_current_user` overridden to return a fixed
    User -- bypasses cookie validation so this test file focuses on
    route behavior, not auth (which is covered by test_auth_routes.py)."""
    user = _make_user()

    async def _fake_user() -> User:
        return user

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        yield TestClient(app), user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# --- Auth gating


def test_export_requires_authentication(client: TestClient) -> None:
    """Without a cookie, `get_current_user` raises 401 before the route
    handler runs."""
    r = client.post("/v1/account/export")
    assert r.status_code == 401


# --- 501 body shape


def test_export_returns_501_with_documented_envelope(
    authenticated_client: tuple[TestClient, User],
) -> None:
    client, _user = authenticated_client
    r = client.post("/v1/account/export")
    assert r.status_code == 501

    body = r.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "not_implemented"
    assert "not yet implemented" in err["message"]
    # request_id is set by the middleware on every request.
    assert err["request_id"] is not None


def test_export_response_includes_schema_version_and_contents(
    authenticated_client: tuple[TestClient, User],
) -> None:
    client, _user = authenticated_client
    r = client.post("/v1/account/export")
    body = r.json()

    assert body["schema_version"] == 1
    contents = body["contents_when_implemented"]
    # Per ADR-047: customer-owned tables only.
    assert set(contents.keys()) == {
        "account",
        "users",
        "businesses",
        "leads",
        "purchases",
        "opt_outs",
    }
    # Each value is a human-readable shape description.
    for key, description in contents.items():
        assert isinstance(description, str) and description, (
            f"contents key {key!r} has empty description"
        )


def test_export_contents_does_not_advertise_platform_owned_tables(
    authenticated_client: tuple[TestClient, User],
) -> None:
    """Per ADR-047: platform IP (vertical_*, signal_definition, prompts,
    audit_log, blocklist) is NOT exportable. The stub's documented
    contents must reflect that boundary so consumers don't form
    expectations the implementation can't satisfy."""
    client, _user = authenticated_client
    r = client.post("/v1/account/export")
    contents = r.json()["contents_when_implemented"]

    forbidden = {
        "vertical",
        "vertical_signal_weight",
        "vertical_copy",
        "vertical_template",
        "vertical_prompt_version",
        "signal_definition",
        "prompt_version",
        "audit_log",
        "blocklist",
    }
    leaked = forbidden & contents.keys()
    assert not leaked, f"export advertises platform-owned tables: {leaked}"


# --- OpenAPI


def test_export_route_appears_in_openapi(client: TestClient) -> None:
    r = client.get("/v1/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/v1/account/export" in paths
    # POST is the documented method.
    assert "post" in paths["/v1/account/export"]
    # 501 is the documented response status.
    responses = paths["/v1/account/export"]["post"]["responses"]
    assert "501" in responses
