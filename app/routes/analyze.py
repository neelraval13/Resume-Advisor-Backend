"""
POST /api/analyze — run a tailoring analysis with SSE streaming.

Returns a Server-Sent Events stream. Each event has a name and a JSON payload.
Event sequence:
    start → many text → (result | parse_error | error) → done

Frontend consumes via EventSource or fetch + ReadableStream.
See app/schemas.py for the exact event payload shapes.
"""

from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.schemas import (
    AnalyzeRequest,
    DoneEvent,
    ErrorEvent,
    ParseErrorEvent,
    ResultEvent,
    StartEvent,
    TextEvent,
)
from app.services import analyzer

router = APIRouter()


# Map our event class to the SSE event name (the bit after `event:` on the wire)
_EVENT_NAMES: dict[type[BaseModel], str] = {
    StartEvent: "start",
    TextEvent: "text",
    ResultEvent: "result",
    ParseErrorEvent: "parse_error",
    ErrorEvent: "error",
    DoneEvent: "done",
}


def _format_sse(event: BaseModel) -> str:
    """
    Format a Pydantic event as an SSE wire-format frame.

    Wire format:
        event: <name>\n
        data: <json>\n
        \n          (blank line terminates the frame)
    """
    name = _EVENT_NAMES[type(event)]
    payload = event.model_dump_json()
    return f"event: {name}\ndata: {payload}\n\n"


async def _sse_generator(req: AnalyzeRequest) -> AsyncGenerator[str, None]:
    """Wrap analyzer.analyze_stream() — formats each event as SSE wire format."""
    async for event in analyzer.analyze_stream(req.resume_text, req.jd_text):
        yield _format_sse(event)


@router.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest) -> StreamingResponse:
    return StreamingResponse(
        _sse_generator(req),
        media_type="text/event-stream",
        headers={
            # Prevent any intermediate proxy from buffering the stream
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable nginx-style proxy buffering if anything ever sits in front of us
            "X-Accel-Buffering": "no",
        },
    )
