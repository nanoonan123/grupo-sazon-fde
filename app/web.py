"""Server-rendered demo pages for candidates and recruiter evaluators."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import ScreeningStage
from app.api_models import AtsApplicationRequest
from app.database import (
    CandidateApplication,
    Conversation,
    Message,
    ScreeningRecord,
    get_session,
    new_uuid,
)
from app.domain.models import Language, ScreeningData, ScreeningStatus
from app.domain.rules import SCREENING_CRITERIA_COUNT, missing_required_fields
from app.routes import process_ats_application

router = APIRouter(include_in_schema=False)
Session = Annotated[AsyncSession, Depends(get_session)]
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


async def _candidate_records(
    session: AsyncSession,
    conversation_id: str,
) -> tuple[
    CandidateApplication,
    Conversation,
    ScreeningRecord | None,
    list[Message],
]:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    application = await session.get(CandidateApplication, conversation.application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    record = await session.scalar(
        select(ScreeningRecord).where(
            ScreeningRecord.application_id == application.id
        )
    )
    messages = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence_number.asc())
            )
        ).all()
    )
    return application, conversation, record, messages


def _candidate_progress(
    record: ScreeningRecord | None,
) -> tuple[int, str, str, str | None]:
    if record is None:
        return (
            0,
            ScreeningStage.FULL_NAME.value,
            ScreeningStatus.IN_PROGRESS.value,
            None,
        )
    data = ScreeningData.model_validate(record.data)
    missing = missing_required_fields(data, record.service_area_supported)
    outcome = record.outcome
    if outcome == ScreeningStatus.INCOMPLETE.value:
        outcome = "stopped"
    return (
        max(0, SCREENING_CRITERIA_COUNT - len(missing)),
        record.stage,
        record.status,
        outcome,
    )


@router.get(
    "/screen/{conversation_id}",
    response_class=HTMLResponse,
    name="candidate_screen",
)
async def candidate_screen(
    request: Request,
    conversation_id: str,
    session: Session,
) -> HTMLResponse:
    """Render a candidate-safe chat shell with persisted ordered history."""

    application, _, record, messages = await _candidate_records(
        session,
        conversation_id,
    )
    collected, stage, conversation_status, outcome = _candidate_progress(record)
    selected_language = (
        ScreeningData.model_validate(record.data).language if record else None
    )
    latest_assistant = next(
        (
            message.content
            for message in reversed(messages)
            if message.role == "assistant"
        ),
        "",
    )
    return templates.TemplateResponse(
        request=request,
        name="candidate_chat.html",
        context={
            "conversation_id": conversation_id,
            "messages": messages,
            "ui_language": (
                selected_language.value
                if selected_language
                else application.preferred_language or Language.ES.value
            ),
            "collected": collected,
            "total": SCREENING_CRITERIA_COUNT,
            "stage": stage,
            "conversation_status": conversation_status,
            "outcome": outcome,
            "terminal": conversation_status != ScreeningStatus.IN_PROGRESS.value,
            "voice_enabled": bool(request.app.state.elevenlabs_agent_id),
            "voice_agent_id": request.app.state.elevenlabs_agent_id,
            "voice_first_message": latest_assistant,
        },
    )




def _demo_defaults() -> dict[str, str]:
    """Return recognizable editable values for the local demonstration."""

    return {
        "external_application_id": "LI-GS-DEMO-0001",
        "phone_number": "+34600123456",
        "phone_country": "+34",
        "source": "linkedin",
        "preferred_language": Language.ES.value,
    }


@router.get("/demo", response_class=HTMLResponse, name="demo_launcher")
async def demo_launcher(request: Request) -> HTMLResponse:
    """Render the local simulated-ATS launcher."""

    return templates.TemplateResponse(
        request=request,
        name="demo.html",
        context={
            "form": _demo_defaults(),
        },
    )


@router.post("/demo")
async def create_demo_application(
    request: Request,
    session: Session,
    external_application_id: Annotated[str, Form(min_length=1, max_length=255)],
    phone_number: Annotated[str, Form(min_length=1, max_length=50)],
    source: Annotated[str, Form(min_length=1, max_length=100)],
    preferred_language: Annotated[str | None, Form()] = Language.ES.value,
) -> RedirectResponse:
    """Create a demo application through the shared ATS intake operation."""

    try:
        language = Language(preferred_language) if preferred_language else None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported preferred language.",
        ) from error
    payload = AtsApplicationRequest(
        external_application_id=external_application_id,
        phone_number=phone_number,
        source=source,
        preferred_language=language,
    )
    result = await process_ats_application(
        payload,
        Response(status_code=status.HTTP_201_CREATED),
        session,
        new_uuid(),
    )
    candidate_url = str(
        request.url_for("candidate_screen", conversation_id=result.conversation_id)
    )
    return RedirectResponse(url=candidate_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/recruiter", response_class=HTMLResponse, name="recruiter_dashboard")
async def recruiter_dashboard(request: Request) -> HTMLResponse:
    """Render the read-only demo operations dashboard."""

    return templates.TemplateResponse(
        request=request,
        name="recruiter.html",
        context={},
    )
