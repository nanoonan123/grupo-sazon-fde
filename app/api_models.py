"""HTTP request and response contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.models import ScreeningStage
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


class CandidateMessageRequest(BaseModel):
    """Validated candidate message accepted for one screening turn."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def strip_nonempty_message(cls, value: str) -> str:
        """Normalize whitespace around a candidate message."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class MessageRead(BaseModel):
    """Candidate-safe representation of one persisted message."""

    message_id: str
    role: str
    content: str
    created_at: datetime


class ScreeningProgress(BaseModel):
    """Deterministic progress through required screening information."""

    current_stage: ScreeningStage
    collected_fields: int
    total_fields: int


class ConversationTurnResponse(BaseModel):
    """Candidate-safe result of starting or advancing a conversation."""

    assistant_message: MessageRead
    conversation_status: ScreeningStatus
    progress: ScreeningProgress
    missing_fields: list[str]
    outcome: ScreeningStatus | None = None
    disqualification_reason: str | None = None
    selected_language: Language | None = None


class VoiceTurnRequest(BaseModel):
    """Validated candidate transcript received from the ElevenLabs tool."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    external_turn_id: str = Field(min_length=1, max_length=255)

    @field_validator("text")
    @classmethod
    def reject_blank_voice_transcript(cls, value: str) -> str:
        """Reject a blank transcript without altering the provider's exact text."""

        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("external_turn_id")
    @classmethod
    def strip_external_turn_id(cls, value: str) -> str:
        """Normalize the provider identifier used as an idempotency key."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class VoiceTurnResponse(BaseModel):
    """Concise response intended for direct ElevenLabs tool consumption."""

    assistant_message: str
    status: ScreeningStatus
    stage: ScreeningStage
    terminal: bool
    outcome: ScreeningStatus | None = None


class InterviewSlotRead(BaseModel):
    """A candidate-local presentation of one available recruiter-contact slot."""

    starts_at_utc: datetime
    local_date: str
    local_time: str
    timezone: str


class InterviewBookingRequest(BaseModel):
    """The UTC slot chosen by a qualified candidate."""

    slot_starts_at_utc: datetime


class InterviewBookingRead(InterviewSlotRead):
    """The persisted booking returned to candidate clients."""

    booking_id: str


class InterviewSlotsResponse(BaseModel):
    """Available slots or the candidate's existing booking."""

    slots: list[InterviewSlotRead]
    booking: InterviewBookingRead | None = None
