"""
Pydantic models — the shared type contracts for our API.

These define the shapes of request and response bodies. FastAPI uses them for:
  - automatic JSON validation on incoming requests
  - automatic JSON serialization on outgoing responses
  - the OpenAPI schema (which generates /docs and powers our typed frontend client)

Single source of truth. Change a field here, and the API + docs + (eventually)
frontend types all stay in sync.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

# ─── parse endpoint ────────────────────────────────────────────────────────


class FileKind(StrEnum):
    """The kinds of files we know how to parse."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    TEX = "tex"


class ParseWarning(StrEnum):
    """Non-fatal issues the caller should know about."""

    LOW_TEXT_DENSITY = "low_text_density"  # parsed but suspiciously little text
    PARTIAL_EXTRACTION = "partial_extraction"  # some pages failed
    ENCRYPTED_BUT_READABLE = "encrypted_but_readable"  # PDF was encrypted with empty password


class ParseMetadata(BaseModel):
    """Information about what was parsed, separate from the text itself."""

    kind: FileKind
    filename: str
    size_bytes: int
    page_count: int | None = Field(None, description="Pages for PDFs/DOCX, None for plain text")
    char_count: int


class ParseResponse(BaseModel):
    """Successful parse — text plus metadata plus any warnings."""

    text: str
    metadata: ParseMetadata
    warnings: list[ParseWarning] = []


class ErrorDetail(BaseModel):
    """Standard error shape for non-2xx responses."""

    error: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable explanation")
    detail: str | None = Field(
        default=None, description="Additional context, e.g. parser library error"
    )
