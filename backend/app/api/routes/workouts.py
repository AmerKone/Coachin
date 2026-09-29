"""Workout logging, history, and progressive-overload recommendations."""

import uuid
from datetime import date

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import (
    ExerciseHistoryPoint,
    ExerciseSetCreate,
    OverloadRecommendation,
    Page,
    WorkoutSessionCreate,
    WorkoutSessionRead,
    WorkoutSessionUpdate,
)

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.post("", response_model=WorkoutSessionRead, status_code=status.HTTP_201_CREATED)
def log_session(payload: WorkoutSessionCreate, user: CurrentUser, db: DbSession) -> WorkoutSessionRead:
    """Log a completed (or in-progress) workout session with its sets."""
    raise NotImplementedError


@router.get("", response_model=Page[WorkoutSessionRead])
def list_sessions(
    user: CurrentUser,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[WorkoutSessionRead]:
    """List logged sessions, optionally within a date range."""
    raise NotImplementedError


@router.get("/{session_id}", response_model=WorkoutSessionRead)
def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WorkoutSessionRead:
    raise NotImplementedError


@router.patch("/{session_id}", response_model=WorkoutSessionRead)
def update_session(
    session_id: uuid.UUID, payload: WorkoutSessionUpdate, user: CurrentUser, db: DbSession
) -> WorkoutSessionRead:
    """Mark complete, set session RPE, or edit notes."""
    raise NotImplementedError


@router.post("/{session_id}/sets", response_model=WorkoutSessionRead)
def add_sets(
    session_id: uuid.UUID, sets: list[ExerciseSetCreate], user: CurrentUser, db: DbSession
) -> WorkoutSessionRead:
    """Append sets to a session (used for live logging during a workout)."""
    raise NotImplementedError


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    raise NotImplementedError


@router.get("/recommendations/next", response_model=list[OverloadRecommendation])
def next_session_targets(
    user: CurrentUser, db: DbSession, program_workout_id: uuid.UUID | None = None
) -> list[OverloadRecommendation]:
    """Progressive-overload targets for the next planned workout (or a given one)."""
    raise NotImplementedError


@router.get("/history/{exercise_id}", response_model=list[ExerciseHistoryPoint])
def exercise_history(
    exercise_id: uuid.UUID, user: CurrentUser, db: DbSession, weeks: int = Query(12, ge=1, le=104)
) -> list[ExerciseHistoryPoint]:
    """Per-session top set, estimated 1RM, and volume for one exercise."""
    raise NotImplementedError
