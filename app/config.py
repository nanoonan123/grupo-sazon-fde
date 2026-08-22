"""Application configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with safe local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Grupo Sazon Candidate Screening API"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    ambiguity_retry_limit: int = Field(default=2, ge=1)
