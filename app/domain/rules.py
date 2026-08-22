"""Deterministic candidate eligibility rules."""

from app.domain.models import (
    DisqualificationReason,
    DriverLicense,
    EligibilityContext,
    EvaluationResult,
    ScreeningData,
    ScreeningStatus,
)


def missing_required_fields(
    data: ScreeningData,
    service_area_supported: bool | None,
) -> list[str]:
    """Return required fields that do not yet have valid structured values."""

    missing: list[str] = []
    if not data.full_name or not data.full_name.strip():
        missing.append("full_name")
    if data.driver_license in (None, DriverLicense.UNCLEAR):
        missing.append("driver_license")
    if (
        not data.location_city
        or not data.location_zone
        or service_area_supported is None
    ):
        missing.append("service_area")
    if not data.availability:
        missing.append("availability")
    if not data.preferred_schedule:
        missing.append("preferred_schedule")
    if data.delivery_experience_years is None or (
        data.delivery_experience_years > 0 and not data.delivery_platforms
    ):
        missing.append("delivery_experience_years")
    if data.start_date is None:
        missing.append("start_date")
    return missing


def _missing_required_fields(
    data: ScreeningData,
    service_area_supported: bool | None,
) -> list[str]:
    """Preserve the original private helper for existing callers."""

    return missing_required_fields(data, service_area_supported)


def _disqualified(reason: DisqualificationReason) -> EvaluationResult:
    """Build a disqualified result with exactly one reason code."""

    return EvaluationResult(
        status=ScreeningStatus.DISQUALIFIED,
        disqualification_reason=reason,
    )


def evaluate_eligibility(context: EligibilityContext) -> EvaluationResult:
    """Evaluate eligibility without probabilistic or external dependencies."""

    data = context.screening_data

    if data.driver_license is DriverLicense.NO:
        return _disqualified(DisqualificationReason.NO_DRIVER_LICENSE)
    if context.service_area_supported is False:
        return _disqualified(DisqualificationReason.OUTSIDE_SERVICE_AREA)
    if context.repeated_abuse_after_warning:
        return _disqualified(DisqualificationReason.REPEATED_ABUSE_AFTER_WARNING)

    missing_fields = missing_required_fields(
        data,
        context.service_area_supported,
    )
    retry_limit_reached = (
        context.has_unresolved_ambiguity
        and context.ambiguity_retry_count >= context.ambiguity_retry_limit
    )
    if retry_limit_reached:
        return EvaluationResult(
            status=ScreeningStatus.NEEDS_REVIEW,
            missing_fields=missing_fields,
        )
    if missing_fields or context.has_unresolved_ambiguity:
        return EvaluationResult(
            status=ScreeningStatus.IN_PROGRESS,
            missing_fields=missing_fields,
        )
    return EvaluationResult(status=ScreeningStatus.QUALIFIED)
