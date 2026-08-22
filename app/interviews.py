"""Qualified-candidate interview booking with deterministic demo slots."""

from datetime import UTC, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_models import (
    InterviewBookingRead,
    InterviewBookingRequest,
    InterviewSlotRead,
    InterviewSlotsResponse,
)
from app.conversation_service import load_conversation
from app.database import (
    CandidateApplication,
    InterviewBooking,
    ScreeningRecord,
    get_session,
    new_uuid,
    utc_now,
)
from app.domain.models import ScreeningData, ScreeningStatus

router = APIRouter(prefix="/api/conversations", tags=["Conversations"])
Session = Annotated[AsyncSession, Depends(get_session)]
COUNTRY_TIMEZONES = {
    "ES": "Europe/Madrid",
    "MX": "America/Mexico_City",
}
SLOT_WEEKDAYS = {2, 3}  # Wednesday and Thursday


def _timezone_for_country(country_code: str | None) -> str:
    timezone = COUNTRY_TIMEZONES.get((country_code or "").upper())
    if timezone is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interview booking is unavailable for this service area.",
        )
    return timezone


def _slot_read(slot: datetime, timezone: str) -> InterviewSlotRead:
    local = slot.astimezone(ZoneInfo(timezone))
    return InterviewSlotRead(
        starts_at_utc=slot.astimezone(UTC),
        local_date=local.date().isoformat(),
        local_time=local.strftime("%H:%M"),
        timezone=timezone,
    )


def available_slot_starts(
    country_code: str,
    *,
    now: datetime | None = None,
) -> list[datetime]:
    """Generate the next four weeks of 30-minute local Wednesday/Thursday slots."""

    timezone = _timezone_for_country(country_code)
    current = (now or utc_now()).astimezone(UTC)
    zone = ZoneInfo(timezone)
    local_now = current.astimezone(zone)
    starts: list[datetime] = []
    for day_offset in range(29):
        date = local_now.date() + timedelta(days=day_offset)
        if date.weekday() not in SLOT_WEEKDAYS:
            continue
        for hour in range(10, 14):
            for minute in (0, 30):
                local_start = datetime.combine(
                    date,
                    time(hour, minute),
                    tzinfo=zone,
                )
                start = local_start.astimezone(UTC)
                if start > current:
                    starts.append(start)
    return starts


async def _qualified_booking_context(
    session: AsyncSession,
    conversation_id: str,
) -> tuple[CandidateApplication, str, str]:
    conversation = await load_conversation(session, conversation_id)
    application = await session.get(CandidateApplication, conversation.application_id)
    record = await session.scalar(
        select(ScreeningRecord).where(ScreeningRecord.application_id == application.id)
    )
    if record is None or record.status != ScreeningStatus.QUALIFIED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only qualified candidates can book an interview.",
        )
    country = ScreeningData.model_validate(record.data).location_country
    return application, country or "", _timezone_for_country(country)


def _booking_read(booking: InterviewBooking) -> InterviewBookingRead:
    return InterviewBookingRead(
        booking_id=booking.id,
        **_slot_read(booking.slot_starts_at_utc, booking.timezone).model_dump(),
    )


@router.get(
    "/{conversation_id}/interview-slots",
    response_model=InterviewSlotsResponse,
)
async def get_interview_slots(
    conversation_id: str,
    session: Session,
) -> InterviewSlotsResponse:
    """Return only unreserved deterministic slots for a qualified candidate."""

    application, country, timezone = await _qualified_booking_context(
        session,
        conversation_id,
    )
    booking = await session.scalar(
        select(InterviewBooking).where(
            InterviewBooking.conversation_id == conversation_id
        )
    )
    if booking is not None:
        return InterviewSlotsResponse(slots=[], booking=_booking_read(booking))
    reserved = set(
        (
            await session.scalars(
                select(InterviewBooking.slot_starts_at_utc).where(
                    InterviewBooking.country_code == country.upper()
                )
            )
        ).all()
    )
    slots = [
        _slot_read(slot, timezone)
        for slot in available_slot_starts(country)
        if slot not in reserved
    ]
    del application
    return InterviewSlotsResponse(slots=slots)


@router.post(
    "/{conversation_id}/interview-booking",
    response_model=InterviewBookingRead,
)
async def create_interview_booking(
    conversation_id: str,
    payload: InterviewBookingRequest,
    session: Session,
) -> InterviewBookingRead:
    """Persist a capacity-one selected slot, idempotently for the same candidate."""

    application, country, timezone = await _qualified_booking_context(
        session,
        conversation_id,
    )
    selected = payload.slot_starts_at_utc.astimezone(UTC)
    existing = await session.scalar(
        select(InterviewBooking).where(
            InterviewBooking.conversation_id == conversation_id
        )
    )
    if existing is not None:
        if existing.slot_starts_at_utc == selected:
            return _booking_read(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation already has an interview booking.",
        )
    if selected not in available_slot_starts(country):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected interview slot is not available.",
        )
    booking = InterviewBooking(
        id=new_uuid(),
        application_id=application.id,
        conversation_id=conversation_id,
        country_code=country.upper(),
        slot_starts_at_utc=selected,
        timezone=timezone,
        created_at=utc_now(),
    )
    session.add(booking)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        existing = await session.scalar(
            select(InterviewBooking).where(
                InterviewBooking.conversation_id == conversation_id
            )
        )
        if existing is not None and existing.slot_starts_at_utc == selected:
            return _booking_read(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected interview slot has just been reserved.",
        ) from error
    return _booking_read(booking)
