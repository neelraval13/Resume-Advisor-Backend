"""
FastAPI application entry point.

Run locally:
    uv run uvicorn app.main:app --reload --port 8000

Visit:
    http://localhost:8000/api/health  →  health check
    http://localhost:8000/docs        →  auto-generated swagger UI
    http://localhost:8000/redoc       →  alternate API docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import fetch_jd, health, parse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup/shutdown hook. Currently just loads settings (which validates env).
    Future: initialize an httpx.AsyncClient pool for the fetcher service here.
    """
    settings = get_settings()
    print(f"[startup] {settings.app_name} v{settings.app_version} ({settings.environment})")
    print(f"[startup] model: {settings.anthropic_model}")
    print(f"[startup] cors origins: {settings.cors_origin_list}")
    yield
    print("[shutdown] goodbye")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Résumé Advisor API",
        description=(
            "Backend for the Odyssey Therapeia Résumé Advisor — "
            "analyzes a résumé against a JD and returns structured, "
            "honest tailoring suggestions."
        ),
        version=settings.app_version,
        lifespan=lifespan,
    )

    # CORS — in dev, allows the Vite dev server. In prod, lock to deployed frontend domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # routes
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(parse.router, prefix="/api", tags=["parse"])
    app.include_router(fetch_jd.router, prefix="/api", tags=["fetch-jd"])
    # future: analyze routers wire in here

    return app


app = create_app()
