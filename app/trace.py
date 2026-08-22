"""Development-only, privacy-safe LangGraph execution trace surfaces."""

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Conversation, Message, get_session

router = APIRouter(tags=["Developer"])
Session = Annotated[AsyncSession, Depends(get_session)]
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

GRAPH_STRUCTURE = [
    {
        "node": "interpret_message",
        "kind": "LLM",
        "description": "Understands language and proposes structured extraction.",
    },
    {
        "node": "validate_and_merge",
        "kind": "Deterministic Python",
        "description": "Validates proposals and merges only accepted state.",
    },
    {
        "node": "determine_next_action",
        "kind": "Deterministic domain rules",
        "description": "Chooses stage, route, and outcome.",
    },
    {
        "node": "compose_response",
        "kind": "Controlled response",
        "description": "Selects candidate-safe copy for the chosen route.",
    },
    {
        "node": "generate_summary",
        "kind": "LLM with deterministic fallback",
        "description": "Runs only for terminal routes.",
    },
]


async def _trace_payload(
    session: AsyncSession,
    conversation_id: str,
) -> dict[str, Any]:
    """Return static structure and the latest real post-turn node updates."""

    if await session.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    message = await session.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "assistant",
            Message.debug_explanation.is_not(None),
        )
        .order_by(Message.sequence_number.desc())
        .limit(1)
    )
    latest_turn: dict[str, Any] | None = None
    if message is not None and message.debug_explanation:
        try:
            parsed = json.loads(message.debug_explanation)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("executed_nodes"), list):
            latest_turn = parsed
    return {
        "mode": "post_turn",
        "graph": GRAPH_STRUCTURE,
        "latest_turn": latest_turn,
        "privacy": (
            "No transcript, phone number, name, structured screening data, or "
            "model explanation is exposed by this trace."
        ),
    }


@router.get("/api/debug/conversations/{conversation_id}/trace")
async def technical_trace_api(
    conversation_id: str,
    session: Session,
) -> dict[str, Any]:
    """Expose a development-only post-turn trace without candidate PII."""

    return await _trace_payload(session, conversation_id)


@router.get(
    "/debug/conversations/{conversation_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
    name="technical_trace",
)
async def technical_trace_page(
    request: Request,
    conversation_id: str,
    session: Session,
) -> HTMLResponse:
    """Render the static graph and latest post-turn execution path."""

    trace = await _trace_payload(session, conversation_id)
    return templates.TemplateResponse(
        request=request,
        name="trace.html",
        context={"conversation_id": conversation_id, "trace": trace},
    )
