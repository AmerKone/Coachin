"""FastAPI application entrypoint.

Run with: `uvicorn app.main:app --reload --app-dir backend`
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.config import get_settings


def create_app() -> FastAPI:
    """Application factory: configures middleware and mounts all routers."""
    settings = get_settings()

    app = FastAPI(
        title="Coachin API",
        version="0.1.0",
        description="Voice-first AI fitness coaching backend.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
