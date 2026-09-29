"""Training program models: program -> planned workouts -> planned exercises."""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import FitnessGoal, ProgramStatus

if TYPE_CHECKING:
    from app.models.exercise import Exercise
    from app.models.user import User
    from app.models.workout import WorkoutSession


class TrainingProgram(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A multi-week training program generated for a user."""

    __tablename__ = "training_programs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    goal: Mapped[FitnessGoal] = mapped_column(pg_enum(FitnessGoal, "fitness_goal"))
    status: Mapped[ProgramStatus] = mapped_column(
        pg_enum(ProgramStatus, "program_status"), default=ProgramStatus.DRAFT
    )
    start_date: Mapped[date] = mapped_column(Date)
    duration_weeks: Mapped[int] = mapped_column(default=4)
    notes: Mapped[str | None] = mapped_column(Text)
    """Coach rationale for the program, shown to the user."""

    user: Mapped["User"] = relationship(back_populates="programs")
    workouts: Mapped[list["ProgramWorkout"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="[ProgramWorkout.week_number, ProgramWorkout.day_of_week]",
    )


class ProgramWorkout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single planned training day within a program week."""

    __tablename__ = "program_workouts"
    __table_args__ = (
        UniqueConstraint("program_id", "week_number", "day_of_week", name="uq_program_workout_slot"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_program_workout_dow"),
        CheckConstraint("week_number >= 1", name="ck_program_workout_week"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_programs.id", ondelete="CASCADE"), index=True
    )
    week_number: Mapped[int]
    day_of_week: Mapped[int]
    """0 = Monday ... 6 = Sunday."""
    name: Mapped[str] = mapped_column(String(120))
    focus: Mapped[str | None] = mapped_column(String(120))
    """e.g. "Upper body push", "Lower body strength"."""

    program: Mapped["TrainingProgram"] = relationship(back_populates="workouts")
    exercises: Mapped[list["PlannedExercise"]] = relationship(
        back_populates="workout", cascade="all, delete-orphan", order_by="PlannedExercise.position"
    )
    sessions: Mapped[list["WorkoutSession"]] = relationship(back_populates="program_workout")


class PlannedExercise(UUIDPrimaryKeyMixin, Base):
    """An exercise prescription (sets x reps @ load) inside a planned workout."""

    __tablename__ = "planned_exercises"
    __table_args__ = (
        CheckConstraint("target_sets > 0", name="ck_planned_sets"),
        CheckConstraint("target_reps_min > 0 AND target_reps_max >= target_reps_min", name="ck_planned_reps"),
        CheckConstraint("target_rpe IS NULL OR target_rpe BETWEEN 1 AND 10", name="ck_planned_rpe"),
    )

    workout_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("program_workouts.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    position: Mapped[int]
    """1-based order of the exercise within the workout."""
    target_sets: Mapped[int]
    target_reps_min: Mapped[int]
    target_reps_max: Mapped[int]
    target_weight_kg: Mapped[float | None]
    target_rpe: Mapped[float | None]
    rest_seconds: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)

    workout: Mapped["ProgramWorkout"] = relationship(back_populates="exercises")
    exercise: Mapped["Exercise"] = relationship()
