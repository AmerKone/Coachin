"""Schemas for training programs and their planned workouts."""

import uuid
from datetime import date

from pydantic import Field, model_validator

from app.models.enums import FitnessGoal, ProgramStatus
from app.schemas.common import CoachinSchema, ORMReadSchema, TimestampedReadSchema
from app.schemas.exercise import ExerciseSummary

# --- Planned exercise -----------------------------------------------------


class PlannedExerciseBase(CoachinSchema):
    exercise_id: uuid.UUID
    position: int = Field(ge=1)
    target_sets: int = Field(ge=1, le=20)
    target_reps_min: int = Field(ge=1, le=100)
    target_reps_max: int = Field(ge=1, le=100)
    target_weight_kg: float | None = Field(default=None, ge=0)
    target_rpe: float | None = Field(default=None, ge=1, le=10)
    rest_seconds: int | None = Field(default=None, ge=0, le=600)
    notes: str | None = None

    @model_validator(mode="after")
    def _reps_range(self) -> "PlannedExerciseBase":
        if self.target_reps_max < self.target_reps_min:
            raise ValueError("target_reps_max must be >= target_reps_min")
        return self


class PlannedExerciseCreate(PlannedExerciseBase):
    pass


class PlannedExerciseRead(ORMReadSchema, PlannedExerciseBase):
    exercise: ExerciseSummary


# --- Program workout ------------------------------------------------------


class ProgramWorkoutBase(CoachinSchema):
    week_number: int = Field(ge=1)
    day_of_week: int = Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    name: str = Field(max_length=120)
    focus: str | None = Field(default=None, max_length=120)


class ProgramWorkoutCreate(ProgramWorkoutBase):
    exercises: list[PlannedExerciseCreate] = Field(default_factory=list)


class ProgramWorkoutRead(ORMReadSchema, ProgramWorkoutBase):
    exercises: list[PlannedExerciseRead]


# --- Program --------------------------------------------------------------


class ProgramGenerateRequest(CoachinSchema):
    """Ask the coach to generate a new program from the user's profile.

    Optional fields override the stored profile for this generation only.
    """

    start_date: date | None = None
    duration_weeks: int = Field(default=4, ge=1, le=16)
    goal: FitnessGoal | None = None
    training_days_per_week: int | None = Field(default=None, ge=1, le=7)
    extra_instructions: str | None = Field(
        default=None, max_length=1000, description='e.g. "no barbell squats, add more core work"'
    )


class ProgramUpdate(CoachinSchema):
    name: str | None = Field(default=None, max_length=120)
    status: ProgramStatus | None = None
    notes: str | None = None


class ProgramSummary(TimestampedReadSchema):
    name: str
    goal: FitnessGoal
    status: ProgramStatus
    start_date: date
    duration_weeks: int


class ProgramRead(ProgramSummary):
    notes: str | None
    workouts: list[ProgramWorkoutRead]
