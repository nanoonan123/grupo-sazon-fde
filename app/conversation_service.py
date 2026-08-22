"""Shared persisted application service for every conversation transport."""

import json
from typing import cast

from fastapi import HTTPException, status
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import GraphRoute, ProviderMessage, ScreeningStage
from app.agent.workflow import ScreeningGraphState, to_workflow_result
from app.api_models import ConversationTurnResponse, MessageRead, ScreeningProgress
from app.database import (
    CandidateApplication,
    Conversation,
    Message,
    ScreeningRecord,
    new_uuid,
    utc_now,
)
from app.domain.models import (
    DisqualificationReason,
    Language,
    ScreeningData,
    ScreeningStatus,
)
from app.domain.rules import SCREENING_CRITERIA_COUNT, missing_required_fields

REQUIRED_FIELD_COUNT = SCREENING_CRITERIA_COUNT
TERMINAL_STATUSES = {
    ScreeningStatus.QUALIFIED,
    ScreeningStatus.DISQUALIFIED,
    ScreeningStatus.NEEDS_REVIEW,
    ScreeningStatus.INCOMPLETE,
    ScreeningStatus.DELETED,
}


async def load_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> Conversation:
    """Load a conversation or return a stable not-found response."""

    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return conversation


async def _load_application(
    session: AsyncSession,
    conversation: Conversation,
) -> CandidateApplication:
    application = await session.get(CandidateApplication, conversation.application_id)
    if application is None:
        raise RuntimeError("Conversation is missing its application")
    return application


async def _load_record(
    session: AsyncSession,
    application_id: str,
) -> ScreeningRecord | None:
    return await session.scalar(
        select(ScreeningRecord).where(
            ScreeningRecord.application_id == application_id
        )
    )


async def _initial_message(
    session: AsyncSession,
    conversation_id: str,
) -> Message | None:
    return await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.message_type == "initial",
        )
    )


def _missing_fields(record: ScreeningRecord) -> list[str]:
    return missing_required_fields(
        ScreeningData.model_validate(record.data),
        record.service_area_supported,
    )


def _turn_response(
    message: Message,
    record: ScreeningRecord,
    missing_fields: list[str],
) -> ConversationTurnResponse:
    outcome = ScreeningStatus(record.outcome) if record.outcome else None
    return ConversationTurnResponse(
        assistant_message=MessageRead(
            message_id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        ),
        conversation_status=ScreeningStatus(record.status),
        progress=ScreeningProgress(
            current_stage=ScreeningStage(record.stage),
            collected_fields=max(0, REQUIRED_FIELD_COUNT - len(missing_fields)),
            total_fields=REQUIRED_FIELD_COUNT,
        ),
        missing_fields=missing_fields,
        outcome=outcome,
        disqualification_reason=record.disqualification_reason,
        selected_language=ScreeningData.model_validate(record.data).language,
    )


def _initial_data(application: CandidateApplication) -> ScreeningData:
    language = (
        Language(application.preferred_language)
        if application.preferred_language is not None
        else None
    )
    return ScreeningData(language=language)


def _initial_text(language: Language | None) -> str:
    if language is not Language.EN:
        return (
            "Hola 👋 Hemos recibido tu candidatura para el puesto de repartidor/a "
            "en Grupo Sazón. El screening dura unos 3 minutos. Para continuar, "
            "¿cuál es tu nombre completo?"
        )
    return (
        "Hi 👋 We received your application for the delivery driver role at Grupo "
        "Sazón. The screening takes about 3 minutes. To continue, what is your "
        "full name?"
    )


def _new_record(
    application: CandidateApplication,
    data: ScreeningData,
) -> ScreeningRecord:
    now = utc_now()
    return ScreeningRecord(
        id=new_uuid(),
        application_id=application.id,
        status=ScreeningStatus.IN_PROGRESS.value,
        stage=ScreeningStage.FULL_NAME.value,
        data=data.model_dump(mode="json"),
        pending_data={},
        clarification_counts={},
        abuse_count=0,
        service_area_supported=None,
        created_at=now,
        updated_at=now,
    )


async def start_persisted_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> ConversationTurnResponse:
    """Create the shared initial assistant message exactly once."""

    conversation = await load_conversation(session, conversation_id)
    application = await _load_application(session, conversation)
    existing = await _initial_message(session, conversation_id)
    record = await _load_record(session, application.id)
    if existing is not None and record is not None:
        return _turn_response(existing, record, _missing_fields(record))

    data = _initial_data(application)
    record = record or _new_record(application, data)
    now = utc_now()
    initial = Message(
        id=new_uuid(),
        conversation_id=conversation.id,
        sequence_number=0,
        role="assistant",
        content=_initial_text(data.language),
        message_type="initial",
        created_at=now,
    )
    session.add_all((record, initial))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _initial_message(session, conversation_id)
        record = await _load_record(session, application.id)
        if existing is None or record is None:
            raise
        return _turn_response(existing, record, _missing_fields(record))
    return _turn_response(initial, record, _missing_fields(record))


async def _next_sequence(session: AsyncSession, conversation_id: str) -> int:
    maximum = await session.scalar(
        select(func.max(Message.sequence_number)).where(
            Message.conversation_id == conversation_id
        )
    )
    return (maximum if maximum is not None else -1) + 1


async def _provider_history(
    session: AsyncSession,
    conversation_id: str,
) -> list[ProviderMessage]:
    messages = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_number)
        )
    ).all()
    return [
        ProviderMessage(role=cast(str, message.role), content=message.content)
        for message in messages
    ]


def _graph_state(
    record: ScreeningRecord,
    history: list[ProviderMessage],
) -> ScreeningGraphState:
    return ScreeningGraphState(
        history=history,
        screening_data=ScreeningData.model_validate(record.data),
        pending_data=dict(record.pending_data),
        clarification_counts={
            key: int(value) for key, value in record.clarification_counts.items()
        },
        abuse_count=record.abuse_count,
        consent_granted=(
            record.pending_data.get("consent_granted")
            if isinstance(record.pending_data.get("consent_granted"), bool)
            else None
        ),
        service_area_supported=record.service_area_supported,
        status=ScreeningStatus(record.status),
        stage=ScreeningStage(record.stage),
        interpretation=None,
        turn_clarification_fields=[],
        turn_resolved_fields=[],
        route=GraphRoute.ASK_NEXT_QUESTION,
        missing_fields=[],
        disqualification_reason=(
            DisqualificationReason(record.disqualification_reason)
            if record.disqualification_reason
            else None
        ),
        response_text="",
        final_summary=record.final_summary,
        provider_name=None,
        provider_model=None,
        provider_latency_ms=None,
        provider_error_code=None,
        debug_explanation=None,
        current_date=utc_now().date(),
    )


async def process_persisted_turn(
    session: AsyncSession,
    graph: CompiledStateGraph,
    conversation_id: str,
    text: str,
) -> ConversationTurnResponse:
    """Persist and process one candidate turn through the authoritative graph."""

    conversation = await load_conversation(session, conversation_id)
    application = await _load_application(session, conversation)
    record = await _load_record(session, application.id)
    initial = await _initial_message(session, conversation_id)
    if record is None or initial is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Start the conversation before sending messages.",
        )
    if ScreeningStatus(record.status) in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The conversation is already closed.",
        )

    user_sequence = await _next_sequence(session, conversation_id)
    user_message = Message(
        id=new_uuid(),
        conversation_id=conversation_id,
        sequence_number=user_sequence,
        role="user",
        content=text,
        message_type="turn",
        created_at=utc_now(),
    )
    session.add(user_message)
    await session.commit()

    history = await _provider_history(session, conversation_id)
    transient_state = _graph_state(record, history)
    completed_state = cast(ScreeningGraphState, dict(transient_state))
    executed_nodes: list[str] = []
    async for event in graph.astream(transient_state, stream_mode="updates"):
        for node_name, node_updates in event.items():
            if node_name.startswith("__") or not isinstance(node_updates, dict):
                continue
            executed_nodes.append(node_name)
            completed_state.update(node_updates)
    result = to_workflow_result(completed_state)

    record.data = result.screening_data
    record.pending_data = result.pending_data
    record.clarification_counts = result.clarification_counts
    record.abuse_count = result.abuse_count
    record.service_area_supported = result.service_area_supported
    record.status = result.status.value
    record.stage = result.stage.value
    record.outcome = (
        result.status.value if result.status in TERMINAL_STATUSES else None
    )
    record.disqualification_reason = (
        result.disqualification_reason.value
        if result.disqualification_reason
        else None
    )
    record.final_summary = result.final_summary
    record.llm_provider = result.llm_provider
    record.llm_model = result.llm_model
    record.llm_latency_ms = result.llm_latency_ms
    record.recoverable_error_code = result.recoverable_error_code
    record.updated_at = utc_now()
    conversation.status = result.status.value
    conversation.updated_at = record.updated_at
    application.status = result.status.value
    application.updated_at = record.updated_at

    assistant = Message(
        id=new_uuid(),
        conversation_id=conversation_id,
        sequence_number=user_sequence + 1,
        role="assistant",
        content=result.response_text,
        message_type="error" if result.recoverable_error_code else "turn",
        llm_provider=result.llm_provider,
        llm_model=result.llm_model,
        llm_latency_ms=result.llm_latency_ms,
        recoverable_error_code=result.recoverable_error_code,
        debug_explanation=json.dumps(
            {
                "executed_nodes": executed_nodes,
                "route": result.route.value,
                "stage": result.stage.value,
                "terminal": result.status in TERMINAL_STATUSES,
                "status": result.status.value,
                "provider": result.llm_provider,
                "model": result.llm_model,
                "provider_latency_ms": result.llm_latency_ms,
                "recoverable_error_code": result.recoverable_error_code,
            },
            ensure_ascii=False,
        ),
        created_at=utc_now(),
    )
    session.add(assistant)
    await session.commit()
    return _turn_response(assistant, record, result.missing_fields)
