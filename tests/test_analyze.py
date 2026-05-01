"""
Tests for /api/analyze (SSE streaming).

Strategy: mock anthropic.AsyncAnthropic so tests don't burn tokens.
Streaming tests assert on the EVENT SEQUENCE — start, text..., result|error, done.

We use TestClient's streaming-aware iter_lines to consume the SSE response.
"""

import json
import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")

import pytest  # noqa: E402
from anthropic import APIError, APITimeoutError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


# ─── helpers ───────────────────────────────────────────────────────────────


def long_text(prefix: str) -> str:
    """Pad text so it passes our min_length=50 input validation."""
    return prefix + " padding " * 20 + " end."


def make_valid_payload() -> dict:
    """Minimal valid AnalyzeResponse-shaped dict."""
    return {
        "fit_assessment": {
            "score": 72,
            "narrative": "Strong technical match. Some leadership gaps.",
        },
        "strengths_to_emphasize": [
            {
                "strength": "Built scalable backend systems",
                "current_location": "Experience > Senior Engineer",
                "jd_match": "Backend system design",
                "action": "Move to top of experience section",
            }
        ],
        "line_edits": [
            {
                "section": "Summary",
                "current_text": "Software engineer.",
                "suggested_text": "Backend-focused software engineer.",
                "rationale": "JD emphasizes backend.",
                "priority": "high",
            }
        ],
        "structural_suggestions": [],
        "skill_gap_recommendations": [
            {
                "gap": "Kubernetes",
                "action": "Deploy a project on managed K8s",
                "type": "project",
                "effort_estimate": "2 weekends",
                "urgency": "helpful",
                "concrete_starter": "Sign up for Linode K8s free tier",
            }
        ],
        "red_flags": [],
        "full_rewrite_if_requested": None,
    }


def make_async_text_stream(chunks: list[str]):
    """
    Build a fake `stream.text_stream` async iterator that yields the given chunks.
    """

    async def _gen() -> AsyncIterator[str]:
        for c in chunks:
            yield c

    return _gen()


def make_streaming_context_manager(chunks: list[str]):
    """
    Build an object that mimics `client.messages.stream(...)`.
    It's an async context manager whose enter-value has a `text_stream` attribute.
    """
    stream_obj = MagicMock()
    stream_obj.text_stream = make_async_text_stream(chunks)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=stream_obj)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def parse_sse_stream(response_text: str) -> list[tuple[str, dict]]:
    """
    Parse the SSE response body into a list of (event_name, parsed_data_dict).
    """
    events = []
    current_event = None
    for line in response_text.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: ") :].strip()
        elif line.startswith("data: "):
            payload = line[len("data: ") :].strip()
            if current_event and payload:
                events.append((current_event, json.loads(payload)))
        elif line == "":
            current_event = None
    return events


# ─── happy path ────────────────────────────────────────────────────────────


@patch("app.services.analyzer.AsyncAnthropic")
def test_analyze_stream_happy_path(mock_anthropic_class, client):
    """Full payload arrives in chunks, validates, returns ResultEvent."""
    payload = make_valid_payload()
    full_json = json.dumps(payload)
    chunks = [full_json[i : i + 50] for i in range(0, len(full_json), 50)]  # ~50-char chunks

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = make_streaming_context_manager(chunks)
    mock_anthropic_class.return_value = mock_client

    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": long_text("Senior role.")},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = parse_sse_stream(r.text)
    event_names = [name for name, _ in events]

    # Expected sequence
    assert event_names[0] == "start"
    assert event_names[-1] == "done"
    assert "result" in event_names
    assert "error" not in event_names
    assert "parse_error" not in event_names

    # Multiple text events
    text_events = [data for name, data in events if name == "text"]
    assert len(text_events) == len(chunks)
    assert "".join(e["chunk"] for e in text_events) == full_json

    # Result event has the validated payload
    result_event = next(data for name, data in events if name == "result")
    assert result_event["result"]["fit_assessment"]["score"] == 72
    assert result_event["result"]["line_edits"][0]["priority"] == "high"


@patch("app.services.analyzer.AsyncAnthropic")
def test_analyze_stream_with_fenced_json(mock_anthropic_class, client):
    """Claude wraps output in ```json ... ``` — should still validate."""
    payload = make_valid_payload()
    fenced = f"```json\n{json.dumps(payload)}\n```"
    chunks = [fenced]

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = make_streaming_context_manager(chunks)
    mock_anthropic_class.return_value = mock_client

    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": long_text("Senior role.")},
    )
    events = parse_sse_stream(r.text)
    event_names = [name for name, _ in events]
    assert "result" in event_names
    assert "parse_error" not in event_names


# ─── parse error path ──────────────────────────────────────────────────────


@patch("app.services.analyzer.AsyncAnthropic")
def test_analyze_stream_malformed_json(mock_anthropic_class, client):
    """Stream completes but text isn't valid JSON → parse_error event."""
    chunks = ["This is not JSON at all, just prose."]

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = make_streaming_context_manager(chunks)
    mock_anthropic_class.return_value = mock_client

    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": long_text("Senior role.")},
    )
    events = parse_sse_stream(r.text)
    event_names = [name for name, _ in events]

    assert "parse_error" in event_names
    assert "result" not in event_names
    assert event_names[-1] == "done"

    parse_err = next(data for name, data in events if name == "parse_error")
    assert parse_err["error"] == "malformed_response"
    assert "raw_text" in parse_err
    assert "not JSON" in parse_err["raw_text"]


@patch("app.services.analyzer.AsyncAnthropic")
def test_analyze_stream_validation_failure(mock_anthropic_class, client):
    """JSON parses but score=150 fails Pydantic validation → parse_error event."""
    bad = make_valid_payload()
    bad["fit_assessment"]["score"] = 150
    chunks = [json.dumps(bad)]

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = make_streaming_context_manager(chunks)
    mock_anthropic_class.return_value = mock_client

    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": long_text("Senior role.")},
    )
    events = parse_sse_stream(r.text)
    assert any(name == "parse_error" for name, _ in events)


# ─── claude api errors ─────────────────────────────────────────────────────


@patch("app.services.analyzer.AsyncAnthropic")
def test_analyze_stream_claude_timeout(mock_anthropic_class, client):
    """APITimeoutError during stream → error event, then done."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=APITimeoutError(request=MagicMock()))
    cm.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = cm
    mock_anthropic_class.return_value = mock_client

    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": long_text("Senior role.")},
    )
    events = parse_sse_stream(r.text)
    event_names = [name for name, _ in events]
    assert "error" in event_names
    assert event_names[-1] == "done"

    err_event = next(data for name, data in events if name == "error")
    assert err_event["error"] == "claude_timeout"


@patch("app.services.analyzer.AsyncAnthropic")
def test_analyze_stream_claude_api_error(mock_anthropic_class, client):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(
        side_effect=APIError(message="rate limit", request=MagicMock(), body=None)
    )
    cm.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = cm
    mock_anthropic_class.return_value = mock_client

    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": long_text("Senior role.")},
    )
    events = parse_sse_stream(r.text)
    err_event = next(data for name, data in events if name == "error")
    assert err_event["error"] == "claude_api_error"


# ─── input validation ──────────────────────────────────────────────────────


def test_analyze_rejects_short_resume(client):
    r = client.post(
        "/api/analyze",
        json={"resume_text": "tiny", "jd_text": long_text("Senior role.")},
    )
    assert r.status_code == 422


def test_analyze_rejects_short_jd(client):
    r = client.post(
        "/api/analyze",
        json={"resume_text": long_text("Engineer."), "jd_text": "tiny"},
    )
    assert r.status_code == 422
