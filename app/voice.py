"""Minimal authenticated ElevenLabs transport for the shared conversation service."""

from hashlib import sha256
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_models import VoiceTurnRequest, VoiceTurnResponse
from app.conversation_service import (
    TERMINAL_STATUSES,
    load_conversation,
    process_persisted_turn,
    start_persisted_conversation,
)
from app.database import VoiceTurnReceipt, get_session, new_uuid, utc_now

router = APIRouter(prefix="/api/voice", tags=["Voice"])
Session = Annotated[AsyncSession, Depends(get_session)]
VoiceSecretHeader = Annotated[
    str | None,
    Header(alias="X-Voice-Tool-Secret"),
]


def _authenticate_tool(request: Request, supplied_secret: str | None) -> None:
    """Authenticate the server-side webhook tool without exposing its secret."""

    configured_secret: str | None = request.app.state.elevenlabs_tool_secret
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice tool authentication is not configured.",
        )
    if supplied_secret is None or not compare_digest(
        supplied_secret.encode("utf-8"),
        configured_secret.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid voice tool credentials.",
        )


def _transcript_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


async def _load_receipt(
    session: AsyncSession,
    conversation_id: str,
    external_turn_id: str,
) -> VoiceTurnReceipt | None:
    return await session.scalar(
        select(VoiceTurnReceipt).where(
            VoiceTurnReceipt.conversation_id == conversation_id,
            VoiceTurnReceipt.external_turn_id == external_turn_id,
        )
    )


def _replay_receipt(
    receipt: VoiceTurnReceipt,
    transcript_hash: str,
) -> VoiceTurnResponse:
    if receipt.transcript_hash != transcript_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="external_turn_id was already used for a different transcript.",
        )
    if receipt.response_payload is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This external voice turn is already being processed.",
        )
    return VoiceTurnResponse.model_validate(receipt.response_payload)


@router.post(
    "/conversations/{conversation_id}/turn",
    response_model=VoiceTurnResponse,
)
async def create_voice_turn(
    conversation_id: str,
    payload: VoiceTurnRequest,
    request: Request,
    session: Session,
    x_voice_tool_secret: VoiceSecretHeader = None,
) -> VoiceTurnResponse:
    """Process one idempotent ElevenLabs transcript through the shared workflow."""

    _authenticate_tool(request, x_voice_tool_secret)
    await load_conversation(session, conversation_id)
    transcript_hash = _transcript_hash(payload.text)
    existing = await _load_receipt(
        session,
        conversation_id,
        payload.external_turn_id,
    )
    if existing is not None:
        return _replay_receipt(existing, transcript_hash)

    receipt = VoiceTurnReceipt(
        id=new_uuid(),
        conversation_id=conversation_id,
        external_turn_id=payload.external_turn_id,
        transcript_hash=transcript_hash,
        response_payload=None,
        created_at=utc_now(),
    )
    session.add(receipt)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _load_receipt(
            session,
            conversation_id,
            payload.external_turn_id,
        )
        if existing is None:
            raise
        return _replay_receipt(existing, transcript_hash)

    await start_persisted_conversation(session, conversation_id)
    graph: CompiledStateGraph = request.app.state.screening_graph
    turn = await process_persisted_turn(
        session,
        graph,
        conversation_id,
        payload.text,
    )
    response = VoiceTurnResponse(
        assistant_message=turn.assistant_message.content,
        status=turn.conversation_status,
        stage=turn.progress.current_stage,
        terminal=turn.conversation_status in TERMINAL_STATUSES,
        outcome=turn.outcome,
    )
    receipt.response_payload = response.model_dump(mode="json")
    await session.commit()
    return response
