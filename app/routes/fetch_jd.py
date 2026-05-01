"""
POST /api/fetch-jd — fetch a job description from a URL.

Accepts a JSON body with a single 'url' field. Returns extracted JD text
plus metadata and any non-fatal warnings.

This route is intentionally thin: it delegates to the fetcher service and
translates fetcher exceptions into HTTP errors.
"""

from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas import ErrorDetail, FetchJDRequest, FetchJDResponse
from app.services import fetcher

router = APIRouter()


@router.post(
    "/fetch-jd",
    response_model=FetchJDResponse,
    responses={
        400: {"model": ErrorDetail, "description": "Invalid URL"},
        422: {"model": ErrorDetail, "description": "Site bot-blocked or extraction failed"},
        502: {"model": ErrorDetail, "description": "Network or upstream HTTP error"},
        504: {"model": ErrorDetail, "description": "Upstream timeout"},
    },
)
async def fetch_jd_endpoint(req: FetchJDRequest) -> FetchJDResponse:
    settings = get_settings()

    try:
        result = await fetcher.fetch_jd(
            req.url,
            timeout_seconds=settings.fetch_timeout_seconds,
        )
    except fetcher.InvalidURLError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e
    except fetcher.BotBlockedError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e
    except fetcher.FetchFailedError as e:
        # Distinguish timeouts from other network errors via the error code
        status_code = (
            status.HTTP_504_GATEWAY_TIMEOUT if e.code == "timeout" else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e

    return FetchJDResponse(
        text=result.text,
        metadata=result.metadata,
        warnings=result.warnings,
    )
