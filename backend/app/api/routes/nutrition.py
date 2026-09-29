"""Nutrition logging and daily summaries."""

import uuid
from datetime import date

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import (
    DailyNutritionSummary,
    MealEstimateRequest,
    NutritionLogCreate,
    NutritionLogRead,
    NutritionLogUpdate,
)

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@router.post("", response_model=NutritionLogRead, status_code=status.HTTP_201_CREATED)
def log_meal(payload: NutritionLogCreate, user: CurrentUser, db: DbSession) -> NutritionLogRead:
    """Log a meal with explicit macros."""
    raise NotImplementedError


@router.post("/estimate", response_model=NutritionLogRead, status_code=status.HTTP_201_CREATED)
def estimate_and_log_meal(
    payload: MealEstimateRequest, user: CurrentUser, db: DbSession
) -> NutritionLogRead:
    """Estimate macros from a free-text description with the LLM, then log it."""
    raise NotImplementedError


@router.get("/daily/{day}", response_model=DailyNutritionSummary)
def daily_summary(day: date, user: CurrentUser, db: DbSession) -> DailyNutritionSummary:
    """Totals vs. targets and all entries for one day."""
    raise NotImplementedError


@router.patch("/{log_id}", response_model=NutritionLogRead)
def update_log(
    log_id: uuid.UUID, payload: NutritionLogUpdate, user: CurrentUser, db: DbSession
) -> NutritionLogRead:
    raise NotImplementedError


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(log_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    raise NotImplementedError
