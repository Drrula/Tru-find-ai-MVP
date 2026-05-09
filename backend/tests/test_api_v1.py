"""A.5 smoke tests for the versioned API surface (`/v1/*`).

Per ADR-017 (path-based versioning) and the A.5 task in docs/phase-a-plan.md.
Verifies:
  - /v1/health returns 200 with the request_id middleware behavior intact.
  - /v1/analyses-legacy returns the deterministic score for the canonical input.
  - /analyze-business back-compat alias still returns the same response.
  - Legacy alias is excluded from the OpenAPI schema.
  - OpenAPI is exposed at /v1/openapi.json.
  - Old unversioned /health is gone (404).
"""

from __future__ import annotations

from uuid import UUID

import pytest


pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _client() -> TestClient:
    return TestClient(app)


def test_v1_health_returns_ok_with_request_id() -> None:
    r = _client().get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    UUID(rid)  # validates UUID-ness


def test_unversioned_health_is_gone() -> None:
    """Old `/health` removed in A.5; clients must use `/v1/health`."""
    r = _client().get("/health")
    assert r.status_code == 404


def test_v1_analyses_legacy_deterministic_score() -> None:
    r = _client().post(
        "/v1/analyses-legacy",
        json={"business_name": "Joe Pizza", "location": "Brooklyn, NY"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 60
    assert sorted(body.keys()) == [
        "category_scores",
        "competitors",
        "gaps",
        "score",
        "summary",
        "trade",
    ]


def test_analyze_business_alias_still_works() -> None:
    """Back-compat alias preserved per ADR-005 through at least Phase B."""
    r = _client().post(
        "/analyze-business",
        json={"business_name": "Joe Pizza", "location": "Brooklyn, NY"},
    )
    assert r.status_code == 200
    assert r.json()["score"] == 60


def test_alias_and_v1_return_identical_response() -> None:
    payload = {"business_name": "Joe Pizza", "location": "Brooklyn, NY"}
    a = _client().post("/analyze-business", json=payload).json()
    b = _client().post("/v1/analyses-legacy", json=payload).json()
    assert a == b


def test_openapi_lives_at_v1_path() -> None:
    r = _client().get("/v1/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    paths = schema.get("paths", {})
    assert "/v1/health" in paths
    assert "/v1/analyses-legacy" in paths


def test_legacy_alias_excluded_from_openapi() -> None:
    """`/analyze-business` is functional but hidden from OpenAPI to nudge migration."""
    r = _client().get("/v1/openapi.json")
    schema = r.json()
    assert "/analyze-business" not in schema.get("paths", {})


def test_unversioned_openapi_is_gone() -> None:
    """Old `/openapi.json` no longer served; OpenAPI moved to `/v1/openapi.json`."""
    r = _client().get("/openapi.json")
    assert r.status_code == 404
