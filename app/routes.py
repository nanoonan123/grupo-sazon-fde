"""HTTP routes for simulated ATS intake and persisted resources."""

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_models import (
    ApplicationRead,
    AtsApplicationRequest,
    AtsApplicationResult,
    ConversationRead,
)
from app.database import (
    CandidateApplication,
    Conversation,
    InboundEvent,
    get_session,
    new_uuid,
    utc_now,
)
from app.domain.models import ScreeningStatus

router = APIRouter(prefix="/api")
Session = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=255),
]


def _payload_hash(payload: AtsApplicationRequest) -> str:
    """Hash a canonical representation of the validated request payload."""

    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _conversation_for_application(
    session: AsyncSession,
    application_id: str,
) -> Conversation | None:
    """Load the single conversation belonging to an application."""

    return await session.scalar(
        select(Conversation).where(Conversation.application_id == application_id)
    )


async def _existing_intake_result(
    session: AsyncSession,
    event: InboundEvent,
    payload_hash: str,
) -> AtsApplicationResult:
    """Resolve a stored idempotency receipt or reject conflicting reuse."""

    if event.payload_hash != payload_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with a different payload.",
        )

    application = await session.get(CandidateApplication, event.application_id)
    conversation = await _conversation_for_application(session, event.application_id)
    if application is None or conversation is None:
        raise RuntimeError("Inbound event references incomplete persisted state")
    return AtsApplicationResult(
        application_id=application.id,
        conversation_id=conversation.id,
        status=application.status,
        created_at=application.created_at,
    )


@router.post(
    "/ats/applications",
    response_model=AtsApplicationResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_ats_application(
    payload: AtsApplicationRequest,
    response: Response,
    session: Session,
    idempotency_key: IdempotencyKey,
) -> AtsApplicationResult:
    """Persist a simulated ATS application exactly once per idempotency key."""

    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be blank.",
        )

    digest = _payload_hash(payload)
    existing_event = await session.scalar(
        select(InboundEvent).where(
            InboundEvent.idempotency_key == normalized_key
        )
    )
    if existing_event is not None:
        response.status_code = status.HTTP_200_OK
        return await _existing_intake_result(session, existing_event, digest)

    application_id = new_uuid()
    conversation_id = new_uuid()
    created_at = utc_now()
    initial_status = ScreeningStatus.IN_PROGRESS.value
    application = CandidateApplication(
        id=application_id,
        external_application_id=payload.external_application_id,
        phone_number=payload.phone_number,
        source=payload.source,
        preferred_language=(
            payload.preferred_language.value if payload.preferred_language else None
        ),
        status=initial_status,
        created_at=created_at,
        updated_at=created_at,
    )
    conversation = Conversation(
        id=conversation_id,
        application_id=application_id,
        status=initial_status,
        created_at=created_at,
        updated_at=created_at,
    )
    event = InboundEvent(
        id=new_uuid(),
        idempotency_key=normalized_key,
        payload_hash=digest,
        payload=payload.model_dump(mode="json"),
        application_id=application_id,
        created_at=created_at,
    )
    session.add_all((application, conversation, event))

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        concurrent_event = await session.scalar(
            select(InboundEvent).where(
                InboundEvent.idempotency_key == normalized_key
            )
        )
        if concurrent_event is None:
            raise
        response.status_code = status.HTTP_200_OK
        return await _existing_intake_result(session, concurrent_event, digest)

    return AtsApplicationResult(
        application_id=application.id,
        conversation_id=conversation.id,
        status=application.status,
        created_at=application.created_at,
    )


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationRead,
)
async def get_application(
    application_id: str,
    session: Session,
) -> ApplicationRead:
    """Return one persisted application and its conversation identifier."""

    application = await session.get(CandidateApplication, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    conversation = await _conversation_for_application(session, application_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ApplicationRead(
        application_id=application.id,
        conversation_id=conversation.id,
        external_application_id=application.external_application_id,
        phone_number=application.phone_number,
        source=application.source,
        preferred_language=application.preferred_language,
        status=application.status,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
)
async def get_conversation(
    conversation_id: str,
    session: Session,
) -> ConversationRead:
    """Return one persisted conversation."""

    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ConversationRead(
        conversation_id=conversation.id,
        application_id=conversation.application_id,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )
