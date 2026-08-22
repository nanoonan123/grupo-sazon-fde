"""Structured contracts for candidate screening."""

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Language(str, Enum):
    """Supported conversation languages."""

    ES = "es"
    EN = "en"


class DriverLicense(str, Enum):
    """Candidate driver-license response."""

    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


class Availability(str, Enum):
    """Supported availability options."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    WEEKENDS = "weekends"


class Schedule(str, Enum):
    """Supported preferred schedules."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    FLEXIBLE = "flexible"


class ScreeningStatus(str, Enum):
    """Possible screening lifecycle outcomes."""

    IN_PROGRESS = "in_progress"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    NEEDS_REVIEW = "needs_review"
    INCOMPLETE = "incomplete"
    DELETED = "deleted"


class DisqualificationReason(str, Enum):
    """Allowed deterministic disqualification reasons."""

    NO_DRIVER_LICENSE = "no_driver_license"
    OUTSIDE_SERVICE_AREA = "outside_service_area"
    REPEATED_ABUSE_AFTER_WARNING = "repeated_abuse_after_warning"


class ScreeningData(BaseModel):
    """Candidate data that may be partial while screening is underway."""

    full_name: str | None = None
    language: Language | None = None
    driver_license: DriverLicense | None = None
    location_raw: str | None = None
    location_country: str | None = None
    location_city: str | None = None
    location_zone: str | None = None
    availability: list[Availability] = Field(default_factory=list)
    preferred_schedule: list[Schedule] = Field(default_factory=list)
    delivery_experience_years: float | None = Field(default=None, ge=0)
    delivery_platforms: list[str] = Field(default_factory=list)
    start_date_raw: str | None = None
    start_date: date | None = None


class EligibilityContext(BaseModel):
    """Deterministic inputs needed to evaluate a screening."""

    screening_data: ScreeningData
    service_area_supported: bool | None = None
    repeated_abuse_after_warning: bool = False
    has_unresolved_ambiguity: bool = False
    ambiguity_retry_count: int = Field(default=0, ge=0)
    ambiguity_retry_limit: int = Field(default=2, ge=1)


class EvaluationResult(BaseModel):
    """Outcome of deterministic eligibility evaluation."""

    status: ScreeningStatus
    disqualification_reason: DisqualificationReason | None = None
    missing_fields: list[str] = Field(default_factory=list)
