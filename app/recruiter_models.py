"""Read-only recruiter API contracts."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.models import ScreeningData, ScreeningStatus


class RecruiterApplicationItem(BaseModel):
    """Operational list representation of one candidate application."""

    application_id: str
    external_application_id: str
    conversation_id: str
    phone_number: str
    source: str
    name: str | None
    location: str | None
    progress_collected: int
    progress_total: int
    current_stage: str
    status: ScreeningStatus
    outcome: str | None
    interview_starts_at_utc: datetime | None = None
    interview_timezone: str | None = None
    updated_at: datetime


class RecruiterApplicationList(BaseModel):
    """Stable paginated application list."""

    items: list[RecruiterApplicationItem]
    total: int
    page: int
    page_size: int


class RecruiterTranscriptMessage(BaseModel):
    """Ordered message content safe for the recruiter detail surface."""

    role: str
    content: str
    created_at: datetime


class RecruiterProviderMetadata(BaseModel):
    """Operational model metadata without hidden reasoning."""

    provider: str | None = None
    model: str | None = None
    last_latency_ms: int | None = None
    p50_latency_ms: float = 0
    recoverable_error_count: int = 0
    latest_recoverable_error_code: str | None = None


class RecruiterApplicationDetail(BaseModel):
    """Complete read-only operational view of one application."""

    application: RecruiterApplicationItem
    screening_data: ScreeningData
    deterministic_reason: str | None = None
    candidate_summary: str | None = None
    final_summary: str | None = None
    escalation_fields: list[str] = Field(default_factory=list)
    clarification_counts: dict[str, int] = Field(default_factory=dict)
    transcript: list[RecruiterTranscriptMessage] = Field(default_factory=list)
    provider: RecruiterProviderMetadata


class RecruiterMetrics(BaseModel):
    """Database-backed demo screening metrics."""

    total_applications: int = 0
    screening_started: int = 0
    screening_completed: int = 0
    qualified: int = 0
    disqualified: int = 0
    needs_review: int = 0
    stopped: int = 0
    deleted: int = 0
    completion_rate: float = 0
    qualification_rate: float = 0
    interview_booking_rate: float = 0
    drop_off_by_current_stage: dict[str, int] = Field(default_factory=dict)
    average_completed_screening_duration_seconds: float = 0
    average_conversation_turns: float = 0
    llm_recoverable_error_count: int = 0
    p50_provider_latency_ms: float = 0
