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


class FetchWarning(StrEnum):
    """Non-fatal issues encountered during URL fetching."""

    LOW_CONTENT = "low_content"  # extracted text suspiciously short
    NO_TITLE_FOUND = "no_title_found"  # could not detect the page title
    POSSIBLE_PARTIAL = "possible_partial"  # JS-rendered content may be incomplete


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


# ─── fetch-jd endpoint ─────────────────────────────────────────────────────


class FetchJDRequest(BaseModel):
    """Request body for /api/fetch-jd."""

    url: str = Field(..., description="The JD page URL to fetch")


class FetchJDMetadata(BaseModel):
    """Information about a fetched URL."""

    source_url: str = Field(..., description="The URL that was fetched (after redirects)")
    source_domain: str = Field(..., description="Just the hostname, useful for UI display")
    title: str | None = Field(default=None, description="Detected page title")
    char_count: int


class FetchJDResponse(BaseModel):
    """Successful fetch — extracted JD text plus metadata plus any warnings."""

    text: str
    metadata: FetchJDMetadata
    warnings: list[FetchWarning] = []


# ─── analyze endpoint ──────────────────────────────────────────────────────


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GapType(StrEnum):
    PROJECT = "project"
    COURSE = "course"
    CERTIFICATION = "certification"
    COMMUNITY = "community"
    READING = "reading"
    OTHER = "other"


class Urgency(StrEnum):
    CRITICAL = "critical"
    HELPFUL = "helpful"
    OPTIONAL = "optional"


class FitAssessment(BaseModel):
    score: int = Field(..., ge=0, le=100, description="0-100 honest fit estimate")
    narrative: str


class Strength(BaseModel):
    strength: str
    current_location: str
    jd_match: str
    action: str


class LineEdit(BaseModel):
    section: str
    current_text: str
    suggested_text: str
    rationale: str
    priority: Priority


class StructuralSuggestion(BaseModel):
    change: str
    rationale: str


class SkillGapRecommendation(BaseModel):
    gap: str
    action: str
    type: GapType
    effort_estimate: str
    urgency: Urgency
    concrete_starter: str


class AnalyzeRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, description="The candidate's résumé as plain text")
    jd_text: str = Field(..., min_length=50, description="The job description as plain text")


class AnalyzeResponse(BaseModel):
    """The full structured tailoring advice — mirrors the system prompt's output shape."""

    fit_assessment: FitAssessment
    strengths_to_emphasize: list[Strength] = []
    line_edits: list[LineEdit] = []
    structural_suggestions: list[StructuralSuggestion] = []
    skill_gap_recommendations: list[SkillGapRecommendation] = []
    red_flags: list[str] = []
    full_rewrite_if_requested: str | None = Field(default=None)


# ─── analyze SSE events ────────────────────────────────────────────────────
# Each event sent over the SSE stream has a typed payload. The wire format is
# `event: <name>\ndata: <json>\n\n`; these models define the `data` shape.


class StartEvent(BaseModel):
    """First event sent — confirms stream opened and which model is running."""

    model: str
    started_at: str  # ISO 8601 timestamp


class TextEvent(BaseModel):
    """A chunk of raw text from Claude. Frontend uses these for progress UI."""

    chunk: str


class ResultEvent(BaseModel):
    """Successful validation — the full structured AnalyzeResponse."""

    result: AnalyzeResponse


class ParseErrorEvent(BaseModel):
    """Claude finished, but the response could not be parsed/validated.

    `raw_text` is the full concatenated text Claude produced, so the frontend
    can show the user what happened and offer a retry button.
    """

    error: str = "malformed_response"
    message: str
    raw_text: str


class ErrorEvent(BaseModel):
    """Claude itself errored (timeout, API failure, rate limit)."""

    error: str
    message: str
    detail: str | None = None


class DoneEvent(BaseModel):
    """Final event — stream is closing. Always sent, even after errors."""

    completed_at: str
    duration_ms: int
