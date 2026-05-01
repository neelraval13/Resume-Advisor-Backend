"""
API key authentication.

A FastAPI dependency that checks the `X-API-Key` header against the configured
shared secret. If `settings.api_key` is None (typical in dev), all requests pass.

Usage in a route:
    from app.middleware.auth import require_api_key
    @router.post("/parse", dependencies=[Depends(require_api_key)])
    async def parse_endpoint(...):
        ...
"""

from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import get_settings
from app.schemas import ErrorDetail


async def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """
    Validate the X-API-Key header against the configured api_key setting.
    Raises 401 if missing or wrong. No-op if api_key isn't configured.
    """
    settings = get_settings()

    # Auth disabled (typical in dev). Let everything through.
    if settings.api_key is None:
        return

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(
                error="missing_api_key",
                message="The X-API-Key header is required.",
            ).model_dump(),
        )

    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(
                error="invalid_api_key",
                message="The provided X-API-Key is invalid.",
            ).model_dump(),
        )
