"""Exercise library lookup."""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.models.enums import ExerciseCategory, MuscleGroup
from app.schemas import ExerciseRead, Page

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.get("", response_model=Page[ExerciseRead])
def list_exercises(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    muscle: MuscleGroup | None = None,
    category: ExerciseCategory | None = None,
    equipment: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ExerciseRead]:
    """Search/filter the exercise library."""
    raise NotImplementedError


@router.get("/{exercise_id}", response_model=ExerciseRead)
def get_exercise(exercise_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ExerciseRead:
    """Return one exercise with instructions and contraindications."""
    raise NotImplementedError
