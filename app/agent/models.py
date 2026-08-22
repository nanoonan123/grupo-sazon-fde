"""Structured interpretation and transient workflow contracts."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import (
    Availability,
    DisqualificationReason,
    DriverLicense,
    Language,
    Schedule,
    ScreeningStatus,
)


class CandidateIntent(StrEnum):
    """Candidate intent proposed by the interpretation provider."""

    SCREENING_ANSWER = "screening_answer"
    JOB_QUESTION = "job_question"
    OFF_TOPIC = "off_topic"
    DATA_DELETION = "data_deletion"
    STOP = "stop"


class ScreeningStage(StrEnum):
    """Deterministic stage derived from the next missing field."""

    CONSENT = "consent"
    LANGUAGE = "language"
    FULL_NAME = "full_name"
    DRIVER_LICENSE = "driver_license"
    SERVICE_AREA = "service_area"
    AVAILABILITY = "availability"
    PREFERRED_SCHEDULE = "preferred_schedule"
    DELIVERY_EXPERIENCE = "delivery_experience_years"
    START_DATE = "start_date"
    REVIEW = "review"
    COMPLETE = "complete"


class GraphRoute(StrEnum):
    """Conditional transitions leaving the decision node."""

    ASK_NEXT_QUESTION = "ask_next_question"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    NEEDS_REVIEW = "needs_review"
    DATA_DELETION = "data_deletion"
    STOPPED = "stopped"


class ScreeningUpdates(BaseModel):
    """Partial candidate fields proposed by the LLM for validation."""

    full_name: str | None = None
    driver_license: DriverLicense | None = None
    location_raw: str | None = None
    location_country: str | None = None
    location_city: str | None = None
    location_zone: str | None = None
    availability: list[Availability] | None = None
    preferred_schedule: list[Schedule] | None = None
    delivery_experience_years: float | None = None
    delivery_platforms: list[str] | None = None
    start_date_raw: str | None = None
    start_date: date | None = None


class MessageInterpretation(BaseModel):
    """Schema-constrained interpretation of one candidate message."""

    updates: ScreeningUpdates = Field(default_factory=ScreeningUpdates)
    detected_language: Language
    explicit_language_switch: Language | None = None
    consent: bool | None = None
    ambiguous: bool = False
    clarification_fields: list[str] = Field(default_factory=list)
    intent: CandidateIntent = CandidateIntent.SCREENING_ANSWER
    abusive_language: bool = False
    confirmed_outside_service_area: bool = False
    location_suggestion_confirmed: bool | None = None
    start_date_is_relative: bool = False
    start_date_confirmed: bool = False
    debug_explanation: str = ""


class SummaryOutput(BaseModel):
    """Short recruiter-facing summary generated for a terminal outcome."""

    summary: str


class ProviderMessage(BaseModel):
    """Minimal persisted history passed to an interpretation provider."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ProviderResult[OutputT: BaseModel]:
    """Structured provider output with operational metadata."""

    value: OutputT
    provider: str
    model: str
    latency_ms: int


@dataclass(frozen=True)
class WorkflowResult:
    """Validated graph result ready for one atomic persistence transaction."""

    screening_data: dict[str, object]
    pending_data: dict[str, object]
    clarification_counts: dict[str, int]
    abuse_count: int
    consent_granted: bool | None
    service_area_supported: bool | None
    status: ScreeningStatus
    stage: ScreeningStage
    route: GraphRoute
    missing_fields: list[str]
    disqualification_reason: DisqualificationReason | None
    response_text: str
    final_summary: str | None
    llm_provider: str | None
    llm_model: str | None
    llm_latency_ms: int | None
    recoverable_error_code: str | None
    debug_explanation: str | None
