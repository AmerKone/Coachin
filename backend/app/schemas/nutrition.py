"""Schemas for nutrition logging, meal estimation, targets and daily summaries."""

from datetime import date, datetime

from pydantic import Field

from app.models.enums import EntrySource, MealType
from app.schemas.common import CoachinSchema, TimestampedReadSchema


class NutritionLogBase(CoachinSchema):
    eaten_at: datetime
    meal_type: MealType
    description: str = Field(min_length=1, max_length=2000)
    calories: float = Field(default=0, ge=0, le=10000)
    protein_g: float = Field(default=0, ge=0, le=1000)
    carbs_g: float = Field(default=0, ge=0, le=2000)
    fat_g: float = Field(default=0, ge=0, le=1000)
    is_estimated: bool = True
    source: EntrySource = EntrySource.MANUAL


class NutritionLogCreate(NutritionLogBase):
    pass


class NutritionLogUpdate(CoachinSchema):
    eaten_at: datetime | None = None
    meal_type: MealType | None = None
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    calories: float | None = Field(default=None, ge=0, le=10000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    carbs_g: float | None = Field(default=None, ge=0, le=2000)
    fat_g: float | None = Field(default=None, ge=0, le=1000)


class NutritionLogRead(TimestampedReadSchema, NutritionLogBase):
    pass


class MealEstimateRequest(CoachinSchema):
    """Free-text meal description to be turned into macro estimates by the LLM."""

    description: str = Field(min_length=1, max_length=2000)
    meal_type: MealType | None = None
    eaten_at: datetime | None = None


class MacroTotals(CoachinSchema):
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MealItem(CoachinSchema):
    """One food in an estimated meal."""

    food: str
    portion: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MealEstimate(CoachinSchema):
    """LLM estimate of a described meal. Not saved: the user reviews it, then logs it."""

    description: str
    meal_type: MealType
    items: list[MealItem]
    totals: MacroTotals
    assumptions: str
    """Portion sizes or preparation the estimate assumed, shown so the user can correct them."""


class NutritionTargets(CoachinSchema):
    """Daily targets: `effective` is what summaries use (profile values win over suggestions)."""

    effective: MacroTotals | None
    suggested: MacroTotals | None
    """Computed from the profile; None when height, weight or age is missing."""
    explanation: str
    missing_profile_fields: list[str]


class DailyNutritionSummary(CoachinSchema):
    day: date
    timezone: str
    totals: MacroTotals
    targets: MacroTotals | None
    """From the profile or computed suggestions; `None` if neither is available."""
    entries: list[NutritionLogRead]
