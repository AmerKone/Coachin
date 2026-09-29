"""Nutrition logging, meal estimation, targets and daily summaries."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.models import NutritionLog
from app.schemas import (
    DailyNutritionSummary,
    MealEstimate,
    MealEstimateRequest,
    NutritionLogCreate,
    NutritionLogRead,
    NutritionLogUpdate,
    NutritionTargets,
)
from app.services.nutrition_service import InvalidTimezoneError, MealEstimationError, NutritionService

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


def get_nutrition_service(db: DbSession) -> NutritionService:
    return NutritionService(db)


Nutrition = Annotated[NutritionService, Depends(get_nutrition_service)]


def _get_owned(nutrition: NutritionService, user_id: uuid.UUID, log_id: uuid.UUID) -> NutritionLog:
    entry = nutrition.get(user_id, log_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nutrition entry not found")
    return entry


@router.post("", response_model=NutritionLogRead, status_code=status.HTTP_201_CREATED)
def log_meal(payload: NutritionLogCreate, user: CurrentUser, nutrition: Nutrition) -> NutritionLog:
    """Log a meal with explicit (or reviewed estimated) macros."""
    return nutrition.log(user.id, payload)


@router.post("/estimate", response_model=MealEstimate)
def estimate_meal(payload: MealEstimateRequest, user: CurrentUser, nutrition: Nutrition) -> MealEstimate:
    """Estimate calories and macros for a described meal, item by item. Nothing is saved:
    review the estimate, then log it with `POST /nutrition`."""
    try:
        return nutrition.estimate(payload)
    except MealEstimationError as exc:
        code = status.HTTP_502_BAD_GATEWAY if exc.upstream else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=str(exc)) from None


@router.get("/targets", response_model=NutritionTargets)
def get_targets(user: CurrentUser, nutrition: Nutrition) -> NutritionTargets:
    """Daily calorie/macro targets: suggestions computed from the profile, overridden by any
    targets saved in the profile."""
    return nutrition.targets(user.profile)


@router.get("/daily/{day}", response_model=DailyNutritionSummary)
def daily_summary(
    day: date,
    user: CurrentUser,
    nutrition: Nutrition,
    tz: str = Query("UTC", max_length=64, description="IANA timezone defining the day, e.g. Africa/Algiers"),
) -> DailyNutritionSummary:
    """Totals vs. targets and all entries for one calendar day in the user's timezone."""
    try:
        return nutrition.daily_summary(user.id, user.profile, day, tz)
    except InvalidTimezoneError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None


@router.patch("/{log_id}", response_model=NutritionLogRead)
def update_log(
    log_id: uuid.UUID, payload: NutritionLogUpdate, user: CurrentUser, nutrition: Nutrition
) -> NutritionLog:
    return nutrition.update(_get_owned(nutrition, user.id, log_id), payload)


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(log_id: uuid.UUID, user: CurrentUser, nutrition: Nutrition) -> None:
    nutrition.delete(_get_owned(nutrition, user.id, log_id))
