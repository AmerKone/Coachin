"""Workout logging, history, and progressive-overload recommendations."""

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.models import WorkoutSession
from app.schemas import (
    ExerciseHistoryPoint,
    ExerciseSetCreate,
    Page,
    WorkoutSessionCreate,
    WorkoutSessionRead,
    WorkoutSessionUpdate,
    WorkoutTargets,
)
from app.services.overload_service import OverloadService
from app.services.program_service import ProgramService
from app.services.workout_service import ProgramWorkoutNotFoundError, UnknownExerciseError, WorkoutService

router = APIRouter(prefix="/workouts", tags=["workouts"])


def _unknown_exercise(exc: UnknownExerciseError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _get_owned(db: DbSession, user_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession:
    session = WorkoutService(db).get(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workout session not found")
    return session


@router.post("", response_model=WorkoutSessionRead, status_code=status.HTTP_201_CREATED)
def log_session(payload: WorkoutSessionCreate, user: CurrentUser, db: DbSession) -> WorkoutSession:
    """Log a completed (or in-progress) workout session with its sets."""
    try:
        return WorkoutService(db).create(user.id, payload)
    except ProgramWorkoutNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned workout not found") from None
    except UnknownExerciseError as exc:
        raise _unknown_exercise(exc) from None


@router.get("", response_model=Page[WorkoutSessionRead])
def list_sessions(
    user: CurrentUser,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[WorkoutSessionRead]:
    """List logged sessions newest first, optionally within a date range (inclusive)."""
    items, total = WorkoutService(db).list_sessions(user.id, start, end, limit, offset)
    return Page[WorkoutSessionRead](
        items=[WorkoutSessionRead.model_validate(s) for s in items], total=total, limit=limit, offset=offset
    )


@router.get("/recommendations/next", response_model=WorkoutTargets)
def next_session_targets(
    user: CurrentUser, db: DbSession, program_workout_id: uuid.UUID | None = None
) -> WorkoutTargets:
    """Progressive-overload targets for a planned workout.

    Defaults to the next unlogged workout of the active program (today's, or the next one).
    """
    overload = OverloadService(db)
    if program_workout_id is not None:
        workout = overload.get_program_workout(user.id, program_workout_id)
        if workout is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planned workout not found")
    else:
        program = ProgramService(db).get_active(user.id)
        if program is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program")
        workout = overload.next_workout(program)
        if workout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No remaining workouts in the active program"
            )
    return overload.targets_for_workout(user.id, workout)


@router.get("/history/{exercise_id}", response_model=list[ExerciseHistoryPoint])
def exercise_history(
    exercise_id: uuid.UUID, user: CurrentUser, db: DbSession, weeks: int = Query(12, ge=1, le=104)
) -> list[ExerciseHistoryPoint]:
    """Per-session top set, estimated 1RM, and volume for one exercise, oldest first."""
    return OverloadService(db).history(user.id, exercise_id, weeks)


@router.get("/{session_id}", response_model=WorkoutSessionRead)
def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WorkoutSession:
    return _get_owned(db, user.id, session_id)


@router.patch("/{session_id}", response_model=WorkoutSessionRead)
def update_session(
    session_id: uuid.UUID, payload: WorkoutSessionUpdate, user: CurrentUser, db: DbSession
) -> WorkoutSession:
    """Mark complete, set session RPE, or edit notes."""
    return WorkoutService(db).update(_get_owned(db, user.id, session_id), payload)


@router.post("/{session_id}/sets", response_model=WorkoutSessionRead)
def add_sets(
    session_id: uuid.UUID, sets: list[ExerciseSetCreate], user: CurrentUser, db: DbSession
) -> WorkoutSession:
    """Append sets to a session (used for live logging during a workout)."""
    session = _get_owned(db, user.id, session_id)
    try:
        return WorkoutService(db).add_sets(session, sets)
    except UnknownExerciseError as exc:
        raise _unknown_exercise(exc) from None


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    WorkoutService(db).delete(_get_owned(db, user.id, session_id))
