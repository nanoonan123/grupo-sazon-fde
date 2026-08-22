"""FastAPI application entry point and lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.database import Database
from app.routes import router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize the schema and dispose database resources on shutdown."""

    database: Database = application.state.database
    await database.initialize()
    try:
        yield
    finally:
        await database.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application instance with its own database resources."""

    resolved_settings = settings or Settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    application.state.database = Database(resolved_settings.database_url)
    application.include_router(router)
    application.add_api_route("/health", health, methods=["GET"])
    return application


async def health() -> dict[str, str]:
    """Report whether the API process is available."""

    return {"status": "ok"}


app = create_app()
