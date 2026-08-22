"""Tests for deterministic candidate eligibility rules."""

from datetime import date

from app.domain.models import (
    Availability,
    DisqualificationReason,
    DriverLicense,
    EligibilityContext,
    Language,
    Schedule,
    ScreeningData,
    ScreeningStatus,
)
from app.domain.rules import evaluate_eligibility


def complete_screening_data(**overrides: object) -> ScreeningData:
    """Build valid screening data and apply explicit test overrides."""

    values: dict[str, object] = {
        "full_name": "Alex Rivera",
        "language": Language.ES,
        "driver_license": DriverLicense.YES,
        "location_raw": "Zona Centro Demo",
        "location_country": "Spain",
        "location_city": "Madrid",
        "location_zone": "Zona Centro Demo",
        "availability": [Availability.FULL_TIME],
        "preferred_schedule": [Schedule.FLEXIBLE],
        "delivery_experience_years": 2,
        "delivery_platforms": ["Demo Delivery"],
        "start_date_raw": "2026-09-01",
        "start_date": date(2026, 9, 1),
    }
    values.update(overrides)
    return ScreeningData.model_validate(values)


def test_qualified_candidate() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(),
            service_area_supported=True,
        )
    )

    assert result.status is ScreeningStatus.QUALIFIED
    assert result.disqualification_reason is None


def test_no_driver_license() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(driver_license=DriverLicense.NO),
            service_area_supported=True,
        )
    )

    assert result.status is ScreeningStatus.DISQUALIFIED
    assert result.disqualification_reason is DisqualificationReason.NO_DRIVER_LICENSE


def test_outside_service_area() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(),
            service_area_supported=False,
        )
    )

    assert result.status is ScreeningStatus.DISQUALIFIED
    assert result.disqualification_reason is DisqualificationReason.OUTSIDE_SERVICE_AREA


def test_repeated_abuse() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(),
            service_area_supported=True,
            repeated_abuse_after_warning=True,
        )
    )

    assert result.status is ScreeningStatus.DISQUALIFIED
    assert (
        result.disqualification_reason
        is DisqualificationReason.REPEATED_ABUSE_AFTER_WARNING
    )


def test_missing_required_fields() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(full_name=None),
            service_area_supported=True,
        )
    )

    assert result.status is ScreeningStatus.IN_PROGRESS
    assert result.missing_fields == ["full_name"]


def test_unresolved_ambiguity_at_retry_limit_needs_review() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(
                driver_license=DriverLicense.UNCLEAR,
            ),
            service_area_supported=True,
            has_unresolved_ambiguity=True,
            ambiguity_retry_count=2,
            ambiguity_retry_limit=2,
        )
    )

    assert result.status is ScreeningStatus.NEEDS_REVIEW
    assert result.missing_fields == ["driver_license"]


def test_zero_years_of_experience_is_valid() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(
                delivery_experience_years=0,
                delivery_platforms=[],
            ),
            service_area_supported=True,
        )
    )

    assert result.status is ScreeningStatus.QUALIFIED


def test_positive_experience_requires_at_least_one_platform() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(delivery_platforms=[]),
            service_area_supported=True,
        )
    )

    assert result.status is ScreeningStatus.IN_PROGRESS
    assert result.missing_fields == ["delivery_experience_years"]


def test_language_is_not_an_eligibility_criterion() -> None:
    result = evaluate_eligibility(
        EligibilityContext(
            screening_data=complete_screening_data(language=None),
            service_area_supported=True,
        )
    )

    assert result.status is ScreeningStatus.QUALIFIED


def test_availability_and_schedule_accept_multiple_values() -> None:
    data = complete_screening_data(
        availability=[Availability.FULL_TIME, Availability.WEEKENDS],
        preferred_schedule=[Schedule.MORNING, Schedule.EVENING],
    )

    assert data.availability == [Availability.FULL_TIME, Availability.WEEKENDS]
    assert data.preferred_schedule == [Schedule.MORNING, Schedule.EVENING]
