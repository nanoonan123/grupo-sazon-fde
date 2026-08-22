"""HTTP request and response contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import Language, ScreeningStatus


class AtsApplicationRequest(BaseModel):
    """Validated payload accepted from the simulated ATS."""

    model_config = ConfigDict(extra="forbid")

    external_application_id: str = Field(min_length=1, max_length=255)
    phone_number: str = Field(min_length=1, max_length=50)
    source: str = Field(min_length=1, max_length=100)
    preferred_language: Language | None = None

    @field_validator("external_application_id", "phone_number", "source")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        """Normalize surrounding whitespace and reject blank values."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class AtsApplicationResult(BaseModel):
    """Stable result returned for an ATS intake event."""

    application_id: str
    conversation_id: str
    status: ScreeningStatus
    created_at: datetime


class ApplicationRead(BaseModel):
    """Public representation of a persisted candidate application."""

    application_id: str
    conversation_id: str
    external_application_id: str
    phone_number: str
    source: str
    preferred_language: Language | None
    status: ScreeningStatus
    created_at: datetime
    updated_at: datetime


class ConversationRead(BaseModel):
    """Public representation of a persisted conversation."""

    conversation_id: str
    application_id: str
    status: ScreeningStatus
    created_at: datetime
    updated_at: datetime
