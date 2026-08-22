"""FastAPI application entry point and lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.agent.provider import OpenAIScreeningProvider, ScreeningLLMProvider
from app.agent.workflow import build_screening_graph
from app.config import Settings
from app.conversation_routes import router as conversation_router
from app.database import Database
from app.recruiter import router as recruiter_router
from app.routes import router
from app.service_areas import ServiceAreaCatalog
from app.trace import router as trace_router
from app.voice import router as voice_router
from app.web import router as web_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize the schema and dispose database resources on shutdown."""

    database: Database = application.state.database
    await database.initialize()
    try:
        yield
    finally:
        await database.dispose()


def create_app(
    settings: Settings | None = None,
    screening_provider: ScreeningLLMProvider | None = None,
) -> FastAPI:
    """Build an application instance with its own database resources."""

    resolved_settings = settings or Settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "ATS", "description": "Simulated ATS intake and resources."},
            {
                "name": "Conversations",
                "description": "Candidate screening conversation turns.",
            },
            {
                "name": "Voice",
                "description": "Authenticated ElevenLabs conversation adapter.",
            },
            {"name": "Operations", "description": "Service health checks."},
            {
                "name": "Recruiter",
                "description": "Read-only applications and measured demo metrics.",
            },
            {
                "name": "Developer",
                "description": "Development-only privacy-safe execution trace.",
            },
        ],
    )
    application.state.database = Database(resolved_settings.database_url)
    api_key = (
        resolved_settings.openai_api_key.get_secret_value()
        if resolved_settings.openai_api_key
        else None
    )
    provider = screening_provider or OpenAIScreeningProvider(
        api_key=api_key,
        model=resolved_settings.openai_model,
        timeout_seconds=resolved_settings.openai_timeout_seconds,
    )
    catalog = ServiceAreaCatalog.from_file(resolved_settings.service_areas_path)
    application.state.screening_graph = build_screening_graph(
        provider,
        catalog,
        resolved_settings.ambiguity_retry_limit,
    )
    application.state.elevenlabs_agent_id = (
        (resolved_settings.elevenlabs_agent_id or "").strip() or None
    )
    application.state.elevenlabs_tool_secret = (
        resolved_settings.elevenlabs_tool_secret.get_secret_value().strip() or None
        if resolved_settings.elevenlabs_tool_secret
        else None
    )
    application.include_router(router)
    application.include_router(conversation_router)
    application.include_router(voice_router)
    application.include_router(recruiter_router)
    application.include_router(web_router)
    trace_enabled = resolved_settings.app_environment.casefold() != "production"
    application.state.trace_enabled = trace_enabled
    if trace_enabled:
        application.include_router(trace_router)
    application.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )
    application.add_api_route(
        "/health",
        health,
        methods=["GET"],
        tags=["Operations"],
    )
    return application


async def health() -> dict[str, str]:
    """Report whether the API process is available."""

    return {"status": "ok"}


app = create_app()
