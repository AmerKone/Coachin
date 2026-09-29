"""Nutrition logging, LLM macro estimation, and target calculation."""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models import NutritionLog, UserProfile
from app.schemas import DailyNutritionSummary, MacroTotals, MealEstimateRequest


class NutritionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def estimate_macros(self, request: MealEstimateRequest) -> MacroTotals:
        """Ask the LLM (grounded with RAG nutrition data) for calories/macros of a described meal."""
        raise NotImplementedError

    def log_estimated_meal(self, user_id: uuid.UUID, request: MealEstimateRequest) -> NutritionLog:
        raise NotImplementedError

    def daily_summary(self, user_id: uuid.UUID, day: date) -> DailyNutritionSummary:
        raise NotImplementedError

    def compute_targets(self, profile: UserProfile) -> MacroTotals:
        """Mifflin-St Jeor BMR x activity factor, adjusted for goal; never below the safety floor."""
        raise NotImplementedError
