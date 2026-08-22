"""Read-only recruiter endpoints and database-backed demo analytics."""

from collections import Counter
from statistics import median
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import (
    CandidateApplication,
    Conversation,
    InterviewBooking,
    Message,
    ScreeningRecord,
    get_session,
)
from app.domain.models import ScreeningData, ScreeningStatus
from app.domain.rules import SCREENING_CRITERIA_COUNT, missing_required_fields
from app.recruiter_models import (
    RecruiterApplicationDetail,
    RecruiterApplicationItem,
    RecruiterApplicationList,
    RecruiterMetrics,
    RecruiterProviderMetadata,
    RecruiterTranscriptMessage,
)

router = APIRouter(prefix="/api/recruiter", tags=["Recruiter"])
Session = Annotated[AsyncSession, Depends(get_session)]
OutcomeFilter = Literal[
    "qualified",
    "disqualified",
    "needs_review",
    "stopped",
    "incomplete",
    "deleted",
]

MISSING_FIELD_STAGES = {
    "full_name": "full_name",
    "driver_license": "driver_license",
    "service_area": "service_area",
    "availability": "availability",
    "preferred_schedule": "preferred_schedule",
    "delivery_experience_years": "delivery_experience_years",
    "start_date": "start_date",
}
DECISION_STATUSES = {
    ScreeningStatus.QUALIFIED,
    ScreeningStatus.DISQUALIFIED,
    ScreeningStatus.NEEDS_REVIEW,
}


def _screening_data(record: ScreeningRecord | None) -> ScreeningData:
    """Return validated authoritative data or an empty in-progress record."""

    if record is None:
        return ScreeningData()
    return ScreeningData.model_validate(record.data)


def _missing_fields(record: ScreeningRecord | None) -> list[str]:
    data = _screening_data(record)
    supported = record.service_area_supported if record is not None else None
    return missing_required_fields(data, supported)


def _derived_missing_stage(missing_fields: list[str]) -> str:
    """Return the first incomplete screening criterion in workflow order."""

    if not missing_fields:
        return "complete"
    return MISSING_FIELD_STAGES.get(missing_fields[0], "review")


def _current_stage(
    record: ScreeningRecord | None,
    missing_fields: list[str],
) -> str:
    if record is None:
        return "not_started"
    if record.status == ScreeningStatus.INCOMPLETE.value:
        return _derived_missing_stage(missing_fields)
    return record.stage


def _display_outcome(record: ScreeningRecord | None) -> str | None:
    if record is None or record.outcome is None:
        return None
    if record.outcome == ScreeningStatus.INCOMPLETE.value:
        return "stopped"
    return record.outcome


def _location(data: ScreeningData) -> str | None:
    parts = [data.location_city, data.location_zone, data.location_country]
    location = ", ".join(part for part in parts if part)
    return location or None


def _application_item(
    application: CandidateApplication,
    conversation: Conversation,
    record: ScreeningRecord | None,
    booking: InterviewBooking | None = None,
) -> RecruiterApplicationItem:
    data = _screening_data(record)
    missing = _missing_fields(record)
    return RecruiterApplicationItem(
        application_id=application.id,
        external_application_id=application.external_application_id,
        conversation_id=conversation.id,
        phone_number=application.phone_number,
        source=application.source,
        name=data.full_name,
        location=_location(data),
        progress_collected=max(0, SCREENING_CRITERIA_COUNT - len(missing)),
        progress_total=SCREENING_CRITERIA_COUNT,
        current_stage=_current_stage(record, missing),
        status=ScreeningStatus(application.status),
        outcome=_display_outcome(record),
        interview_starts_at_utc=(booking.slot_starts_at_utc if booking else None),
        interview_timezone=booking.timezone if booking else None,
        updated_at=application.updated_at,
    )


async def _application_rows(
    session: AsyncSession,
) -> list[
    tuple[
        CandidateApplication,
        Conversation,
        ScreeningRecord | None,
        InterviewBooking | None,
    ]
]:
    result = await session.execute(
        select(CandidateApplication, Conversation, ScreeningRecord, InterviewBooking)
        .join(Conversation, Conversation.application_id == CandidateApplication.id)
        .outerjoin(
            ScreeningRecord,
            ScreeningRecord.application_id == CandidateApplication.id,
        )
        .outerjoin(
            InterviewBooking,
            InterviewBooking.application_id == CandidateApplication.id,
        )
        .order_by(
            CandidateApplication.updated_at.desc(),
            CandidateApplication.id.asc(),
        )
    )
    return list(result.tuples())


@router.get("/applications", response_model=RecruiterApplicationList)
async def list_recruiter_applications(
    session: Session,
    application_status: Annotated[
        ScreeningStatus | None,
        Query(alias="status"),
    ] = None,
    outcome: Annotated[OutcomeFilter | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=255)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> RecruiterApplicationList:
    """List applications using stable filters, search, sorting, and pagination."""

    items = [
        _application_item(application, conversation, record, booking)
        for application, conversation, record, booking in await _application_rows(
            session
        )
    ]
    if application_status is not None:
        items = [item for item in items if item.status is application_status]
    if outcome is not None:
        requested_outcome = "stopped" if outcome == "incomplete" else outcome
        items = [item for item in items if item.outcome == requested_outcome]
    normalized_search = (search or "").strip().casefold()
    if normalized_search:
        items = [
            item
            for item in items
            if any(
                normalized_search in (value or "").casefold()
                for value in (
                    item.name,
                    item.application_id,
                    item.external_application_id,
                    item.phone_number,
                )
            )
        ]
    total = len(items)
    offset = (page - 1) * page_size
    return RecruiterApplicationList(
        items=items[offset : offset + page_size],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _application_detail_row(
    session: AsyncSession,
    application_id: str,
) -> tuple[
    CandidateApplication,
    Conversation,
    ScreeningRecord | None,
    InterviewBooking | None,
]:
    row = (
        await session.execute(
            select(
                CandidateApplication,
                Conversation,
                ScreeningRecord,
                InterviewBooking,
            )
            .join(
                Conversation,
                Conversation.application_id == CandidateApplication.id,
            )
            .outerjoin(
                ScreeningRecord,
                ScreeningRecord.application_id == CandidateApplication.id,
            )
            .outerjoin(
                InterviewBooking,
                InterviewBooking.application_id == CandidateApplication.id,
            )
            .where(CandidateApplication.id == application_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return row[0], row[1], row[2], row[3]


@router.get(
    "/applications/{application_id}",
    response_model=RecruiterApplicationDetail,
)
async def get_recruiter_application(
    application_id: str,
    session: Session,
) -> RecruiterApplicationDetail:
    """Return structured data, transcript, outcome, and operational metadata."""

    application, conversation, record, booking = await _application_detail_row(
        session,
        application_id,
    )
    messages = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.sequence_number.asc())
            )
        ).all()
    )
    latencies = [
        message.llm_latency_ms
        for message in messages
        if message.llm_latency_ms is not None
    ]
    error_messages = [
        message
        for message in messages
        if message.recoverable_error_code is not None
    ]
    data = _screening_data(record)
    missing = _missing_fields(record)
    escalation_fields: list[str] = []
    if (
        record is not None
        and record.status == ScreeningStatus.NEEDS_REVIEW.value
    ):
        escalation_fields = missing or [
            key
            for key, value in record.clarification_counts.items()
            if int(value) > 0
        ]
    candidate_summary = next(
        (
            message.content
            for message in reversed(messages)
            if message.role == "assistant"
        ),
        None,
    )
    return RecruiterApplicationDetail(
        application=_application_item(application, conversation, record, booking),
        screening_data=data,
        deterministic_reason=(record.disqualification_reason if record else None),
        candidate_summary=candidate_summary,
        final_summary=record.final_summary if record else None,
        escalation_fields=escalation_fields,
        clarification_counts=(
            {key: int(value) for key, value in record.clarification_counts.items()}
            if record
            else {}
        ),
        transcript=[
            RecruiterTranscriptMessage(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
            )
            for message in messages
        ],
        provider=RecruiterProviderMetadata(
            provider=record.llm_provider if record else None,
            model=record.llm_model if record else None,
            last_latency_ms=record.llm_latency_ms if record else None,
            p50_latency_ms=float(median(latencies)) if latencies else 0,
            recoverable_error_count=len(error_messages),
            latest_recoverable_error_code=(
                error_messages[-1].recoverable_error_code
                if error_messages
                else None
            ),
        ),
    )


@router.get("/metrics", response_model=RecruiterMetrics)
async def get_recruiter_metrics(session: Session) -> RecruiterMetrics:
    """Calculate operational metrics exclusively from persisted records."""

    rows = await _application_rows(session)
    records = [record for _, _, record, _ in rows if record is not None]
    bookings = [booking for _, _, _, booking in rows if booking is not None]
    messages = list((await session.scalars(select(Message))).all())
    record_statuses = [ScreeningStatus(record.status) for record in records]
    screening_started = len(records)
    screening_completed = sum(
        record_status in DECISION_STATUSES for record_status in record_statuses
    )
    qualified = record_statuses.count(ScreeningStatus.QUALIFIED)
    disqualified = record_statuses.count(ScreeningStatus.DISQUALIFIED)
    needs_review = record_statuses.count(ScreeningStatus.NEEDS_REVIEW)
    stopped = record_statuses.count(ScreeningStatus.INCOMPLETE)
    deleted = record_statuses.count(ScreeningStatus.DELETED)

    drop_offs: Counter[str] = Counter()
    for record in records:
        record_status = ScreeningStatus(record.status)
        if record_status not in {
            ScreeningStatus.IN_PROGRESS,
            ScreeningStatus.INCOMPLETE,
        }:
            continue
        missing = _missing_fields(record)
        stage = record.stage
        if record_status is ScreeningStatus.INCOMPLETE and stage == "complete":
            stage = _derived_missing_stage(missing)
        drop_offs[stage] += 1

    completed_durations = [
        (record.updated_at - record.created_at).total_seconds()
        for record in records
        if ScreeningStatus(record.status) in DECISION_STATUSES
        and record.updated_at >= record.created_at
    ]
    user_turns = sum(message.role == "user" for message in messages)
    provider_latencies = [
        message.llm_latency_ms
        for message in messages
        if message.llm_latency_ms is not None
    ]
    recoverable_errors = sum(
        message.recoverable_error_code is not None for message in messages
    )
    return RecruiterMetrics(
        total_applications=len(rows),
        screening_started=screening_started,
        screening_completed=screening_completed,
        qualified=qualified,
        disqualified=disqualified,
        needs_review=needs_review,
        stopped=stopped,
        deleted=deleted,
        completion_rate=(
            round(screening_completed / screening_started, 4)
            if screening_started
            else 0
        ),
        qualification_rate=(
            round(qualified / screening_completed, 4)
            if screening_completed
            else 0
        ),
        interview_booking_rate=(
            round(len(bookings) / qualified, 4) if qualified else 0
        ),
        drop_off_by_current_stage=dict(sorted(drop_offs.items())),
        average_completed_screening_duration_seconds=(
            round(sum(completed_durations) / len(completed_durations), 2)
            if completed_durations
            else 0
        ),
        average_conversation_turns=(
            round(user_turns / screening_started, 2) if screening_started else 0
        ),
        llm_recoverable_error_count=recoverable_errors,
        p50_provider_latency_ms=(
            float(median(provider_latencies)) if provider_latencies else 0
        ),
    )
