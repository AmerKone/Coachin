"""Exercise library lookup."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.models import Exercise
from app.models.enums import Equipment, ExerciseCategory, MuscleGroup
from app.schemas import ExerciseRead, Page
from app.services.exercise_service import search_exercises

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.get("", response_model=Page[ExerciseRead])
def list_exercises(
    db: DbSession,
    user: CurrentUser,
    q: str | None = Query(None, max_length=100, description="Case-insensitive name search"),
    muscle: MuscleGroup | None = Query(None, description="Primary muscle group"),
    category: ExerciseCategory | None = None,
    equipment: list[Equipment] | None = Query(
        None, description="Equipment available; only exercises doable with it are returned"
    ),
    no_equipment: bool = Query(False, description="Only exercises that need no equipment"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ExerciseRead]:
    """Search/filter the exercise library."""
    items, total = search_exercises(
        db,
        q=q,
        muscle=muscle,
        category=category,
        equipment=equipment,
        no_equipment=no_equipment,
        limit=limit,
        offset=offset,
    )
    return Page[ExerciseRead](
        items=[ExerciseRead.model_validate(e) for e in items], total=total, limit=limit, offset=offset
    )


@router.get("/{exercise_id}", response_model=ExerciseRead)
def get_exercise(exercise_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Exercise:
    """Return one exercise with instructions and contraindications."""
    exercise = db.get(Exercise, exercise_id)
    if exercise is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
    return exercise
