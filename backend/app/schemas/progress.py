"""Schemas for body metrics and monthly progress reports."""

from datetime import date, datetime
from typing import Any

from pydantic import Field, model_validator

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


# --- Progress reports -----------------------------------------------------


class ProgressReportGenerateRequest(CoachinSchema):
    """Generate a report for a period; defaults to the previous calendar month."""

    period_start: date | None = None
    period_end: date | None = None

    @model_validator(mode="after")
    def _period_order(self) -> "ProgressReportGenerateRequest":
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class ProgressReportSummary(TimestampedReadSchema):
    period_start: date
    period_end: date


class ProgressReportRead(ProgressReportSummary):
    metrics: dict[str, Any]
    summary: str
    recommendations: str | None
