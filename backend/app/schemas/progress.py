"""Schemas for body metrics, progress overviews (chart data) and monthly reports."""

import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from app.schemas.common import CoachinSchema, TimestampedReadSchema

# --- Body metrics ---------------------------------------------------------


class BodyMetricBase(CoachinSchema):
    recorded_at: datetime
    weight_kg: float | None = Field(default=None, gt=20, lt=400)
    body_fat_pct: float | None = Field(default=None, ge=2, le=70)
    waist_cm: float | None = Field(default=None, gt=30, lt=300)
    resting_heart_rate: int | None = Field(default=None, ge=25, le=220)
    notes: str | None = None


class BodyMetricCreate(BodyMetricBase):
    pass


class BodyMetricRead(TimestampedReadSchema, BodyMetricBase):
    pass


# --- Progress overview (computed, chart-ready) ----------------------------


class WeightPoint(CoachinSchema):
    day: date
    weight_kg: float


class CaloriePoint(CoachinSchema):
    day: date
    calories: float
    protein_g: float


class VolumePoint(CoachinSchema):
    week_start: date
    """Monday of the week."""
    sessions: int
    sets: int
    volume_kg: float


class StrengthPoint(CoachinSchema):
    day: date
    estimated_1rm_kg: float


class ExerciseProgress(CoachinSchema):
    exercise_id: uuid.UUID
    name: str
    points: list[StrengthPoint]
    start_1rm_kg: float
    end_1rm_kg: float
    change_pct: float


class TrainingStats(CoachinSchema):
    sessions_completed: int
    workouts_planned: int
    """Planned workouts of the active/completed program that fall in the period."""
    adherence_pct: float | None
    total_sets: int
    total_volume_kg: float


class NutritionStats(CoachinSchema):
    days_logged: int
    avg_calories: float | None
    avg_protein_g: float | None
    calorie_target: float | None
    protein_target_g: float | None
    days_on_calorie_target: int
    """Logged days within ±10% of the calorie target."""
    days_hit_protein: int


class BodyStats(CoachinSchema):
    start_weight_kg: float | None
    end_weight_kg: float | None
    change_kg: float | None
    weekly_change_pct: float | None
    """Average weekly change as % of starting weight (negative = losing)."""


class ProgressOverview(CoachinSchema):
    period_start: date
    period_end: date
    timezone: str
    training: TrainingStats
    nutrition: NutritionStats
    body: BodyStats
    weight_series: list[WeightPoint]
    calorie_series: list[CaloriePoint]
    volume_series: list[VolumePoint]
    strength: list[ExerciseProgress]
    safety_events: int
    flags: list[str]
    """Things worth a careful mention, e.g. "rapid_weight_loss", "low_protein"."""


# --- Reports --------------------------------------------------------------


def _check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone: {value!r}") from None
    return value


class ProgressReportGenerateRequest(CoachinSchema):
    """Generate a report for a period; defaults to the previous calendar month."""

    period_start: date | None = None
    period_end: date | None = None
    timezone: str = Field(default="UTC", max_length=64)

    _tz = field_validator("timezone")(_check_timezone)

    @model_validator(mode="after")
    def _period_order(self) -> "ProgressReportGenerateRequest":
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        if self.period_start and self.period_end and (self.period_end - self.period_start).days > 92:
            raise ValueError("A report can cover at most about three months")
        return self


class ProgressReportSummary(TimestampedReadSchema):
    period_start: date
    period_end: date


class ProgressReportRead(ProgressReportSummary):
    metrics: dict[str, Any]
    """Snapshot of the `ProgressOverview` the report was written from."""
    summary: str
    recommendations: str | None
    """One recommendation per line."""
