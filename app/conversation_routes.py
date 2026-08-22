"""HTTP routes for the shared persisted conversation service."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_models import CandidateMessageRequest, ConversationTurnResponse
from app.conversation_service import (
    process_persisted_turn,
    start_persisted_conversation,
)
from app.database import get_session

router = APIRouter(prefix="/api/conversations", tags=["Conversations"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/{conversation_id}/start",
    response_model=ConversationTurnResponse,
)
async def start_conversation(
    conversation_id: str,
    session: Session,
) -> ConversationTurnResponse:
    """Create the initial assistant message exactly once."""

    return await start_persisted_conversation(session, conversation_id)


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationTurnResponse,
)
async def create_candidate_message(
    conversation_id: str,
    payload: CandidateMessageRequest,
    request: Request,
    session: Session,
) -> ConversationTurnResponse:
    """Process a text turn through the shared persisted conversation service."""

    graph: CompiledStateGraph = request.app.state.screening_graph
    return await process_persisted_turn(
        session,
        graph,
        conversation_id,
        payload.text,
    )
