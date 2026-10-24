"""Application configuration via environment variables.

Keeps all configuration out of source code. Values come from the
environment (or a loaded .env file). See `.env.example` for documentation.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Phase 1 settings. Phase 2 values (queues, notifications) intentionally absent."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+psycopg://jobsoo:jobsoo@localhost:5433/jobsoo_dev"

    # Adzuna job source
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = Field(default="ae", pattern=r"^[a-z]{2}$")
    adzuna_base_url: str = "https://api.adzuna.com/v1/api"
    adzuna_timeout_seconds: float = 15.0
    adzuna_max_retries: int = 2

    # AI
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    claude_max_tokens: int = 8_000
    requirements_cache_version: str = "1"

    # Uploads
    cv_upload_dir: Path = Path("./data/uploads")
    tailored_pdf_dir: Path = Path("./data/exports")
    max_cv_upload_mb: int = 10
    allowed_cv_extensions: set[str] = {".pdf", ".docx", ".md", ".txt"}

    # Misc
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            msg = f"log_level must be one of {sorted(allowed)}"
            raise ValueError(msg)
        return v.upper()

    @property
    def max_cv_upload_bytes(self) -> int:
        return self.max_cv_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests to reload env)."""
    get_settings.cache_clear()
