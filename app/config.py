"""Application configuration loaded from environment variables."""

from pydantic import Field
from pydantic.types import SecretStr
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
    database_url: str = "sqlite+aiosqlite:///./data/grupo_sazon.db"
    ambiguity_retry_limit: int = Field(default=2, ge=1)
    service_areas_path: str = "data/service_areas.json"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)
    elevenlabs_agent_id: str | None = None
    elevenlabs_tool_secret: SecretStr | None = None
