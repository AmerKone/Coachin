"""Workout session logging: create, query, edit and delete sessions and their sets."""

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Exercise, ExerciseSet, ProgramWorkout, TrainingProgram, WorkoutSession
from app.schemas import ExerciseSetCreate, WorkoutSessionCreate, WorkoutSessionUpdate


class UnknownExerciseError(Exception):
    def __init__(self, exercise_ids: Iterable[uuid.UUID]) -> None:
        self.exercise_ids = sorted(str(i) for i in exercise_ids)
        super().__init__(f"Unknown exercise id(s): {', '.join(self.exercise_ids)}")


class ProgramWorkoutNotFoundError(Exception):
    """The referenced planned workout doesn't exist or belongs to another user."""


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


class WorkoutService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: uuid.UUID, payload: WorkoutSessionCreate) -> WorkoutSession:
        """Log a session with its sets.

        Raises:
            ProgramWorkoutNotFoundError: `program_workout_id` isn't one of the user's workouts.
            UnknownExerciseError: a set references an exercise that doesn't exist.
        """
        if payload.program_workout_id is not None:
            owned = self.db.scalar(
                select(ProgramWorkout.id)
                .join(TrainingProgram)
                .where(ProgramWorkout.id == payload.program_workout_id, TrainingProgram.user_id == user_id)
            )
            if owned is None:
                raise ProgramWorkoutNotFoundError
        self._check_exercises(payload.sets)

        session = WorkoutSession(
            user_id=user_id,
            **payload.model_dump(exclude={"sets"}),
            sets=[ExerciseSet(**s.model_dump()) for s in payload.sets],
        )
        self.db.add(session)
        self.db.commit()
        return self.get(user_id, session.id)  # type: ignore[return-value]

    def get(self, user_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession | None:
        return self.db.scalar(
            select(WorkoutSession)
            .where(WorkoutSession.id == session_id, WorkoutSession.user_id == user_id)
            .options(selectinload(WorkoutSession.sets).selectinload(ExerciseSet.exercise))
            .execution_options(populate_existing=True)
        )

    def list_sessions(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[WorkoutSession], int]:
        """Sessions newest first, optionally limited to `start`..`end` (inclusive, UTC dates)."""
        stmt = select(WorkoutSession).where(WorkoutSession.user_id == user_id)
        if start is not None:
            stmt = stmt.where(WorkoutSession.started_at >= _day_start(start))
        if end is not None:
            stmt = stmt.where(WorkoutSession.started_at < _day_start(end + timedelta(days=1)))
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = self.db.scalars(
            stmt.order_by(WorkoutSession.started_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(WorkoutSession.sets).selectinload(ExerciseSet.exercise))
        ).all()
        return list(items), total

    def update(self, session: WorkoutSession, changes: WorkoutSessionUpdate) -> WorkoutSession:
        for field, value in changes.model_dump(exclude_unset=True).items():
            setattr(session, field, value)
        self.db.commit()
        return self.get(session.user_id, session.id)  # type: ignore[return-value]

    def add_sets(self, session: WorkoutSession, sets: list[ExerciseSetCreate]) -> WorkoutSession:
        """Append sets (e.g. while logging live during a workout).

        Raises:
            UnknownExerciseError: a set references an exercise that doesn't exist.
        """
        self._check_exercises(sets)
        session.sets.extend(ExerciseSet(**s.model_dump()) for s in sets)
        self.db.commit()
        return self.get(session.user_id, session.id)  # type: ignore[return-value]

    def delete(self, session: WorkoutSession) -> None:
        self.db.delete(session)
        self.db.commit()

    def _check_exercises(self, sets: Iterable[ExerciseSetCreate]) -> None:
        wanted = {s.exercise_id for s in sets}
        if not wanted:
            return
        found = set(self.db.scalars(select(Exercise.id).where(Exercise.id.in_(wanted))))
        if missing := wanted - found:
            raise UnknownExerciseError(missing)
