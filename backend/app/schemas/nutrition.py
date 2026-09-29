"""Schemas for nutrition logging and daily summaries."""

from datetime import date, datetime

from pydantic import Field

from app.models.enums import EntrySource, MealType
from app.schemas.common import CoachinSchema, TimestampedReadSchema


class NutritionLogBase(CoachinSchema):
    eaten_at: datetime
    meal_type: MealType
    description: str = Field(min_length=1, max_length=2000)
    calories: float = Field(default=0, ge=0)
    protein_g: float = Field(default=0, ge=0)
    carbs_g: float = Field(default=0, ge=0)
    fat_g: float = Field(default=0, ge=0)
    is_estimated: bool = True
    source: EntrySource = EntrySource.MANUAL


class NutritionLogCreate(NutritionLogBase):
    pass


class NutritionLogUpdate(CoachinSchema):
    eaten_at: datetime | None = None
    meal_type: MealType | None = None
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)


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


class DailyNutritionSummary(CoachinSchema):
    day: date
    totals: MacroTotals
    targets: MacroTotals | None
    """From the user's profile; `None` if no targets set."""
    entries: list[NutritionLogRead]
