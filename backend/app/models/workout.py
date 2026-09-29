"""Logged workout models: session -> sets. Source data for progressive overload."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import EntrySource

if TYPE_CHECKING:
    from app.models.exercise import Exercise
    from app.models.program import ProgramWorkout
    from app.models.user import User


class WorkoutSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A workout the user actually performed (optionally tied to a planned workout)."""

    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint("session_rpe IS NULL OR session_rpe BETWEEN 1 AND 10", name="ck_session_rpe"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    program_workout_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("program_workouts.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_rpe: Mapped[float | None]
    """Overall perceived exertion for the session (1-10)."""
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[EntrySource] = mapped_column(
        pg_enum(EntrySource, "entry_source"), default=EntrySource.MANUAL
    )

    user: Mapped["User"] = relationship(back_populates="workout_sessions")
    program_workout: Mapped["ProgramWorkout | None"] = relationship(back_populates="sessions")
    sets: Mapped[list["ExerciseSet"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="[ExerciseSet.exercise_id, ExerciseSet.set_number]",
    )


class ExerciseSet(UUIDPrimaryKeyMixin, Base):
    """One performed set of an exercise within a session."""

    __tablename__ = "exercise_sets"
    __table_args__ = (
        CheckConstraint("reps >= 0", name="ck_set_reps"),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="ck_set_weight"),
        CheckConstraint("rpe IS NULL OR rpe BETWEEN 1 AND 10", name="ck_set_rpe"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    set_number: Mapped[int]
    reps: Mapped[int]
    weight_kg: Mapped[float | None]
    rpe: Mapped[float | None]
    is_warmup: Mapped[bool] = mapped_column(default=False)
    duration_seconds: Mapped[int | None]
    """For timed/cardio sets."""

    session: Mapped["WorkoutSession"] = relationship(back_populates="sets")
    exercise: Mapped["Exercise"] = relationship()
