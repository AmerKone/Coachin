"""Aggregates all versioned API routers under `/api/v1`."""

from fastapi import APIRouter

from app.api.routes import (
    auth,
    chat,
    exercises,
    nutrition,
    programs,
    progress,
    safety,
    users,
    voice,
    workouts,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(exercises.router)
api_router.include_router(programs.router)
api_router.include_router(workouts.router)
api_router.include_router(nutrition.router)
api_router.include_router(progress.router)
api_router.include_router(chat.router)
api_router.include_router(voice.router)
api_router.include_router(safety.router)
