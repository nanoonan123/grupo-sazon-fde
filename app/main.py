"""FastAPI application entry point."""

from fastapi import FastAPI

from app.config import Settings

settings = Settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report whether the API process is available."""

    return {"status": "ok"}
