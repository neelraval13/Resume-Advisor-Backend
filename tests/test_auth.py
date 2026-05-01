"""
Tests for the X-API-Key authentication dependency.

Strategy: tests run with api_key unset by default (dev mode → no auth).
For auth-enforcement tests, we patch get_settings to return a Settings
instance with api_key set, then verify protection works.
"""

import os
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def test_health_open_when_auth_disabled():
    """With no api_key configured, /health is reachable."""
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_open_when_auth_enabled():
    """Even with auth on, /health stays unauthenticated (uptime checks need it)."""
    settings = Settings.model_validate(
        {
            "anthropic_api_key": "sk-ant-test",
            "api_key": "test-secret-key",
        }
    )
    with patch("app.middleware.auth.get_settings", return_value=settings):
        client = TestClient(create_app())
        r = client.get("/api/health")
        assert r.status_code == 200  # no header, still works


def test_protected_route_requires_key_when_configured():
    """With auth enabled, protected routes 401 without a key."""
    settings = Settings.model_validate(
        {
            "anthropic_api_key": "sk-ant-test",
            "api_key": "test-secret-key",
        }
    )
    with patch("app.middleware.auth.get_settings", return_value=settings):
        client = TestClient(create_app())
        r = client.post(
            "/api/parse",
            files={"file": ("a.txt", b"hello world this is some content", "text/plain")},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "missing_api_key"


def test_protected_route_rejects_wrong_key():
    settings = Settings.model_validate(
        {
            "anthropic_api_key": "sk-ant-test",
            "api_key": "test-secret-key",
        }
    )
    with patch("app.middleware.auth.get_settings", return_value=settings):
        client = TestClient(create_app())
        r = client.post(
            "/api/parse",
            files={"file": ("a.txt", b"hello world this is some content", "text/plain")},
            headers={"X-API-Key": "wrong-key"},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "invalid_api_key"


def test_protected_route_passes_with_correct_key():
    settings = Settings.model_validate(
        {
            "anthropic_api_key": "sk-ant-test",
            "api_key": "test-secret-key",
        }
    )
    with patch("app.middleware.auth.get_settings", return_value=settings):
        client = TestClient(create_app())
        r = client.post(
            "/api/parse",
            files={"file": ("a.txt", b"hello world this is some content", "text/plain")},
            headers={"X-API-Key": "test-secret-key"},
        )
        # 200 if parsed cleanly, or other valid response — but NOT 401
        assert r.status_code != 401


def test_protected_route_open_when_auth_disabled():
    """When api_key is None (dev default), routes are reachable without a header."""
    client = TestClient(create_app())
    r = client.post(
        "/api/parse",
        files={"file": ("a.txt", b"hello world this is some content", "text/plain")},
    )
    assert r.status_code != 401
