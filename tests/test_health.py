"""
Test for the /health endpoint.

Establishes the testing pattern: spin up the app via create_app(),
call it with FastAPI's TestClient (which uses httpx under the hood),
assert on the JSON shape and values.

We override ANTHROPIC_API_KEY via env so tests don't need a real key.
"""

import os

# set required env BEFORE importing the app — settings are loaded at import
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


def test_health_returns_200():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_response_shape():
    client = TestClient(create_app())
    response = client.get("/api/health")
    body = response.json()

    assert body["status"] == "ok"
    assert body["service"] == "resume-advisor-api"
    assert "version" in body
    assert "environment" in body
    assert "model" in body


def test_health_no_auth_required():
    """Health must not require auth — uptime monitors hit it unauthenticated."""
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
