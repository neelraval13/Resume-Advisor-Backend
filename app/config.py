"""
Application config.

Reads from environment variables (or a .env file in dev). All settings are
validated at startup — if ANTHROPIC_API_KEY is missing or malformed, the app
fails fast instead of crashing on the first analyze request.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── service identity ──────────────────────────────────────────────────
    app_name: str = "resume-advisor-api"
    app_version: str = "0.1.0"
    environment: str = Field(
        default="development", description="development | staging | production"
    )

    # ─── anthropic ─────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(..., description="Required. Set via env var, never commit.")
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 8000

    # ─── cors ──────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ─── limits ────────────────────────────────────────────────────────────
    max_upload_size_mb: int = 10
    request_timeout_seconds: int = 60
    fetch_timeout_seconds: int = 15


@lru_cache
def get_settings() -> Settings:
    """Cached so we only parse env once per process."""
    return Settings.model_validate({})
