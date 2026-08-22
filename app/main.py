"""FastAPI application entry point and lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.provider import OpenAIScreeningProvider, ScreeningLLMProvider
from app.agent.workflow import build_screening_graph
from app.config import Settings
from app.conversation_routes import router as conversation_router
from app.database import Database
from app.routes import router
from app.service_areas import ServiceAreaCatalog


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
            {"name": "Operations", "description": "Service health checks."},
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
    application.include_router(router)
    application.include_router(conversation_router)
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
