"""Schemas for logged workouts and progressive-overload recommendations."""

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import EntrySource
from app.schemas.common import CoachinSchema, ORMReadSchema, TimestampedReadSchema
from app.schemas.exercise import ExerciseSummary

# --- Sets -----------------------------------------------------------------


class ExerciseSetBase(CoachinSchema):
    exercise_id: uuid.UUID
    set_number: int = Field(ge=1)
    reps: int = Field(ge=0, le=500)
    weight_kg: float | None = Field(default=None, ge=0)
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool = False
    duration_seconds: int | None = Field(default=None, ge=0)


class ExerciseSetCreate(ExerciseSetBase):
    pass


class ExerciseSetRead(ORMReadSchema, ExerciseSetBase):
    exercise: ExerciseSummary


# --- Sessions -------------------------------------------------------------


class WorkoutSessionCreate(CoachinSchema):
    program_workout_id: uuid.UUID | None = None
    started_at: datetime
    completed_at: datetime | None = None
    session_rpe: float | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    source: EntrySource = EntrySource.MANUAL
    sets: list[ExerciseSetCreate] = Field(default_factory=list)


class WorkoutSessionUpdate(CoachinSchema):
    completed_at: datetime | None = None
    session_rpe: float | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class WorkoutSessionRead(TimestampedReadSchema):
    program_workout_id: uuid.UUID | None
    started_at: datetime
    completed_at: datetime | None
    session_rpe: float | None
    notes: str | None
    source: EntrySource
    sets: list[ExerciseSetRead]


# --- Progressive overload -------------------------------------------------


class OverloadRecommendation(CoachinSchema):
    """Next-session target for one exercise, derived from recent performance."""

    exercise: ExerciseSummary
    last_weight_kg: float | None
    last_reps: list[int]
    recommended_weight_kg: float | None
    recommended_reps_min: int
    recommended_reps_max: int
    rationale: str
    """Human-readable explanation, e.g. "Hit top of rep range at RPE 7 on all sets: +2.5 kg"."""


class ExerciseHistoryPoint(CoachinSchema):
    """One data point for an exercise progress chart."""

    performed_at: datetime
    top_set_weight_kg: float | None
    top_set_reps: int
    estimated_1rm_kg: float | None
    total_volume_kg: float
