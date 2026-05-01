"""
URL fetching service.

Fetches a job description page from an arbitrary URL and returns clean,
LLM-ready text plus metadata. Built on httpx (async) + trafilatura
(readable-content extraction).

Design notes:
- The route always passes through this service. URL validation, bot detection,
  and content extraction are all handled here so the route stays thin.
- We use a real-browser User-Agent because many sites (Workday, Greenhouse)
  reject anything that smells like a bot.
- We do NOT support JavaScript rendering in V1. Sites that gate content behind
  JS (some Indeed pages, LinkedIn) will trip our bot-block detector and the
  user gets a clear "paste manually" error.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura

from app.schemas import FetchJDMetadata, FetchWarning

# ─── thresholds (tunable) ──────────────────────────────────────────────────

# Below this many chars in the extracted body, we assume bot-blocking or
# JS-only content. Real JDs are typically 1500-8000 chars.
MIN_EXTRACTED_CHARS = 200

# A "low content" warning fires below this. Genuine but unusually terse JDs
# can hit this — we don't reject, just flag.
LOW_CONTENT_THRESHOLD = 400

# A real browser UA. Many ATS platforms reject the default httpx UA.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Phrases that strongly suggest a login wall instead of real content.
LOGIN_WALL_MARKERS = (
    "sign in to view",
    "log in to continue",
    "join linkedin to",
    "create a free account",
    "please enable javascript",
    "you need to enable javascript",
)


# ─── exceptions ────────────────────────────────────────────────────────────


class FetcherError(Exception):
    """Base class for fetcher failures. Routes catch this and return 4xx."""

    def __init__(self, code: str, message: str, detail: str | None = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


class InvalidURLError(FetcherError):
    pass


class FetchFailedError(FetcherError):
    """Network failure, DNS error, timeout, non-2xx response."""

    pass


class BotBlockedError(FetcherError):
    """Site returned content but it looks like a login wall or anti-bot page."""

    pass


# ─── result container ──────────────────────────────────────────────────────


@dataclass
class FetchResult:
    """Internal struct returned by fetch_jd. Routes convert to FetchJDResponse."""

    text: str
    metadata: FetchJDMetadata
    warnings: list[FetchWarning]


# ─── url validation ────────────────────────────────────────────────────────


def validate_url(url: str) -> str:
    """
    Sanity-check a URL string. Returns the cleaned URL.
    Raises InvalidURLError on bad input.
    """
    url = url.strip()

    if not url:
        raise InvalidURLError(
            code="empty_url",
            message="URL is required.",
        )

    # Reject anything that's not http(s) — no file://, ftp://, javascript:, etc.
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError(
            code="invalid_scheme",
            message="Only http:// and https:// URLs are supported.",
            detail=f"Got scheme: '{parsed.scheme or '(none)'}'",
        )

    if not parsed.netloc:
        raise InvalidURLError(
            code="invalid_url",
            message="URL is malformed.",
            detail=f"Could not extract a hostname from: {url}",
        )

    return url


# ─── bot-block detection ───────────────────────────────────────────────────


def looks_bot_blocked(text: str) -> bool:
    """Returns True if the extracted text looks like a login wall or bot page."""
    if len(text) < MIN_EXTRACTED_CHARS:
        return True
    lower = text.lower()
    return any(marker in lower for marker in LOGIN_WALL_MARKERS)


# ─── public entry point ────────────────────────────────────────────────────


async def fetch_jd(url: str, *, timeout_seconds: int = 15) -> FetchResult:
    """
    Fetch a JD page and return clean text plus metadata.

    Raises FetcherError subclasses on failure. Returns FetchResult on success
    (which may include non-fatal warnings).

    The `timeout_seconds` keyword arg is injected from settings by the route.
    """
    cleaned_url = validate_url(url)
    warnings: list[FetchWarning] = []

    # ─── fetch ─────────────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(cleaned_url)
    except httpx.TimeoutException as e:
        raise FetchFailedError(
            code="timeout",
            message=f"The site took longer than {timeout_seconds}s to respond.",
            detail="Try again, or paste the JD text manually.",
        ) from e
    except httpx.HTTPError as e:
        raise FetchFailedError(
            code="network_error",
            message="Could not reach the URL.",
            detail=str(e),
        ) from e

    if response.status_code >= 400:
        raise FetchFailedError(
            code=f"http_{response.status_code}",
            message=f"The site returned HTTP {response.status_code}.",
            detail=(
                "Some sites block automated requests. "
                "If this is a real job posting, paste the text manually."
            ),
        )

    # ─── extract ───────────────────────────────────────────────────────────
    raw_html = response.text
    extracted = trafilatura.extract(
        raw_html,
        favor_recall=True,  # err on the side of including content
        include_comments=False,  # strip discussion/comments sections
        include_tables=True,  # JD perks/benefits often live in tables
        no_fallback=False,  # let trafilatura use its fallback heuristics
    )

    if not extracted or not extracted.strip():
        raise BotBlockedError(
            code="no_content_extracted",
            message="Could not extract content from this page.",
            detail=(
                "The site may require login or render content via JavaScript. "
                "Paste the JD text manually instead."
            ),
        )

    text = extracted.strip()

    # ─── bot-block check ───────────────────────────────────────────────────
    if looks_bot_blocked(text):
        raise BotBlockedError(
            code="bot_blocked",
            message="The site appears to have blocked the request or requires login.",
            detail=(
                "Common culprits: LinkedIn, some Indeed pages, sites with anti-bot protection. "
                "Paste the JD text manually instead."
            ),
        )

    # ─── content warnings ──────────────────────────────────────────────────
    if len(text) < LOW_CONTENT_THRESHOLD:
        warnings.append(FetchWarning.LOW_CONTENT)

    # ─── extract title ─────────────────────────────────────────────────────
    title = trafilatura.extract_metadata(raw_html)
    page_title = title.title if title and title.title else None
    if not page_title:
        warnings.append(FetchWarning.NO_TITLE_FOUND)

    # ─── metadata ──────────────────────────────────────────────────────────
    final_url = str(response.url)
    parsed_final = urlparse(final_url)

    metadata = FetchJDMetadata(
        source_url=final_url,
        source_domain=parsed_final.netloc,
        title=page_title,
        char_count=len(text),
    )

    return FetchResult(text=text, metadata=metadata, warnings=warnings)
