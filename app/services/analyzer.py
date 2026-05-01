"""
Resume analyzer service.

Streams a tailoring analysis from Claude over SSE. The async generator
`analyze_stream()` yields typed events:

    StartEvent → many TextEvent → ResultEvent | ParseErrorEvent | ErrorEvent → DoneEvent

The route layer iterates this generator and formats each event as SSE wire
format. All real logic — Claude SDK calls, JSON parsing, Pydantic validation —
lives here.

Design notes:
- Prompt lives in app/prompts/advisor.md, loaded once at module import.
- We do NOT retry on malformed JSON. The user resubmits if it fails.
- Streaming is real (Claude SDK's streaming API), not buffered-and-chunked.
- All Claude API errors are wrapped in our own AnalyzerError hierarchy.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

from anthropic import APIError, APITimeoutError, AsyncAnthropic
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import (
    AnalyzeResponse,
    DoneEvent,
    ErrorEvent,
    ParseErrorEvent,
    ResultEvent,
    StartEvent,
    TextEvent,
)

# ─── prompt loading ────────────────────────────────────────────────────────


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "advisor.md"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


# ─── helpers ───────────────────────────────────────────────────────────────


def _strip_fences(text: str) -> str:
    """Strip ```json...``` fences if Claude wrapped its output."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3].rstrip()
    return text.strip()


def _extract_json_object(text: str) -> str:
    """Find the outermost JSON object in `text`."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in response")
    return text[start : end + 1]


def _parse_and_validate(raw_text: str) -> AnalyzeResponse:
    """Parse Claude's text output and validate against AnalyzeResponse."""
    cleaned = _strip_fences(raw_text)
    json_text = _extract_json_object(cleaned)
    parsed = json.loads(json_text)
    return AnalyzeResponse.model_validate(parsed)


def _build_user_message(resume_text: str, jd_text: str) -> str:
    return f"ORIGINAL RESUME:\n\n{resume_text}\n\n---\n\nJOB DESCRIPTION:\n\n{jd_text}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ─── the streaming generator ───────────────────────────────────────────────


# Type alias for everything this generator can yield
AnalyzeEvent = StartEvent | TextEvent | ResultEvent | ParseErrorEvent | ErrorEvent | DoneEvent


async def analyze_stream(
    resume_text: str,
    jd_text: str,
) -> AsyncGenerator[AnalyzeEvent, None]:
    """
    Run a tailoring analysis with streaming.

    Yields typed events in order:
        1. StartEvent
        2. Many TextEvent (Claude's output streaming live)
        3. Exactly one of: ResultEvent, ParseErrorEvent, ErrorEvent
        4. DoneEvent (always sent, even on error, so frontend knows to close)
    """
    settings = get_settings()
    started_monotonic = time.monotonic()

    yield StartEvent(model=settings.anthropic_model, started_at=_now_iso())

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_message = _build_user_message(resume_text, jd_text)
    full_text_buffer: list[str] = []

    try:
        async with client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            async for chunk in stream.text_stream:
                full_text_buffer.append(chunk)
                yield TextEvent(chunk=chunk)
    except APITimeoutError as e:
        yield ErrorEvent(
            error="claude_timeout",
            message="Claude took too long to respond. Please try again.",
            detail=str(e),
        )
        yield DoneEvent(
            completed_at=_now_iso(),
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
        )
        return
    except APIError as e:
        yield ErrorEvent(
            error="claude_api_error",
            message="The Claude API returned an error.",
            detail=str(e),
        )
        yield DoneEvent(
            completed_at=_now_iso(),
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
        )
        return

    # Stream completed cleanly. Now parse + validate the buffered text.
    full_text = "".join(full_text_buffer)
    try:
        result = _parse_and_validate(full_text)
        yield ResultEvent(result=result)
    except (ValueError, json.JSONDecodeError, ValidationError):
        yield ParseErrorEvent(
            message=(
                "Claude's response could not be parsed as the required JSON schema. "
                "This is unusual — please try again."
            ),
            raw_text=full_text,
        )

    yield DoneEvent(
        completed_at=_now_iso(),
        duration_ms=int((time.monotonic() - started_monotonic) * 1000),
    )
