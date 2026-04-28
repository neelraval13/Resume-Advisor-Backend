"""
Health endpoint.

Returns service identity. Used by:
  - uptime monitors (Fly.io health checks, UptimeRobot, etc.)
  - the frontend on first load to verify the API is reachable
  - humans hitting it manually to sanity-check a deployment

Intentionally lightweight — no external calls, no auth. If this endpoint
returns 200, the FastAPI process is up; that's all it claims.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    model: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        model=settings.anthropic_model,
    )
