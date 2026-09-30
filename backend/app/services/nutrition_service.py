"""Nutrition logging, LLM meal estimation, daily targets and summaries."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.prompts import MEAL_ESTIMATION_SYSTEM_PROMPT, MEAL_ESTIMATION_USER_PROMPT, NO_REFERENCE_MATERIAL
from app.models import NutritionLog, UserProfile
from app.models.enums import EntrySource, FitnessGoal, MealType, Sex
from app.rag.retriever import KnowledgeRetriever
from app.schemas import (
    DailyNutritionSummary,
    MacroTotals,
    MealEstimate,
    MealEstimateRequest,
    MealItem,
    NutritionLogCreate,
    NutritionLogRead,
    NutritionLogUpdate,
    NutritionTargets,
)
from app.services import llm_client
from app.services.llm_client import LLMError, StructuredLLM
from app.services.safety_service import has_eating_disorder_history

KCAL_PER_G = {"protein": 4, "carbs": 4, "fat": 9}
MIN_CALORIES = {Sex.FEMALE: 1200}
DEFAULT_MIN_CALORIES = 1500  # men and unspecified: the higher, safer floor
PROTEIN_G_PER_KG = {
    FitnessGoal.FAT_LOSS: 2.0,
    FitnessGoal.MUSCLE_GAIN: 1.8,
    FitnessGoal.STRENGTH: 1.8,
    FitnessGoal.ENDURANCE: 1.6,
    FitnessGoal.GENERAL_FITNESS: 1.6,
}


class MealEstimationError(Exception):
    """The meal couldn't be estimated. `upstream` is True when the LLM itself failed."""

    def __init__(self, message: str, upstream: bool = False) -> None:
        super().__init__(message)
        self.upstream = upstream


class InvalidTimezoneError(ValueError):
    pass


# --- LLM output schema ----------------------------------------------------


class _EstimatedItem(BaseModel):
    food: str
    portion: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class EstimatedMeal(BaseModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    items: list[_EstimatedItem]
    assumptions: str


# --- Pure helpers ---------------------------------------------------------


def macro_calories(protein_g: float, carbs_g: float, fat_g: float) -> float:
    return protein_g * KCAL_PER_G["protein"] + carbs_g * KCAL_PER_G["carbs"] + fat_g * KCAL_PER_G["fat"]


def clean_item(item: _EstimatedItem) -> MealItem:
    """Clamp negatives and, if calories disagree with the macros by more than 25% (and 50 kcal),
    trust the macros: they are what the model estimates most reliably."""
    protein, carbs, fat = (max(0.0, v) for v in (item.protein_g, item.carbs_g, item.fat_g))
    calories = max(0.0, item.calories)
    from_macros = macro_calories(protein, carbs, fat)
    if abs(calories - from_macros) > max(50.0, 0.25 * max(calories, from_macros)):
        calories = from_macros
    return MealItem(
        food=item.food.strip(), portion=item.portion.strip(), calories=round(calories),
        protein_g=round(protein, 1), carbs_g=round(carbs, 1), fat_g=round(fat, 1),
    )


def sum_items(items: list[MealItem]) -> MacroTotals:
    return MacroTotals(
        calories=round(sum(i.calories for i in items)),
        protein_g=round(sum(i.protein_g for i in items), 1),
        carbs_g=round(sum(i.carbs_g for i in items), 1),
        fat_g=round(sum(i.fat_g for i in items), 1),
    )


def age_on(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def activity_factor(training_days: int) -> float:
    if training_days <= 2:
        return 1.375
    if training_days <= 5:
        return 1.55
    return 1.725


def suggest_targets(profile: UserProfile, today: date | None = None) -> tuple[MacroTotals | None, str, list[str]]:
    """Daily targets from the profile (knowledge-base method), with an explanation.

    Mifflin-St Jeor BMR x activity factor, then: fat loss -20% (max 500 kcal), muscle gain
    +10%, otherwise maintenance. No deficit for under-18s or BMI < 18.5; never below the
    safety floor (1200 kcal women, 1500 otherwise). Protein by goal in g/kg (using the weight
    at BMI 25 when BMI > 30), fat 25% of calories (min 0.5 g/kg), carbs the remainder.
    """
    today = today or date.today()
    missing = [name for name, value in (("weight_kg", profile.weight_kg), ("height_cm", profile.height_cm),
                                        ("date_of_birth", profile.date_of_birth)) if not value]
    if missing:
        return None, "Add your " + ", ".join(m.replace("_", " ") for m in missing) + " to get suggested targets.", missing

    weight, height = profile.weight_kg, profile.height_cm
    age = age_on(profile.date_of_birth, today)
    base = 10 * weight + 6.25 * height - 5 * age
    sex_offset = {Sex.MALE: 5, Sex.FEMALE: -161}.get(profile.sex, -78)  # unspecified: midpoint
    bmr = base + sex_offset
    factor = activity_factor(profile.training_days_per_week)
    tdee = bmr * factor

    bmi = weight / (height / 100) ** 2
    goal = profile.primary_goal
    notes = [f"Estimated maintenance ≈ {tdee:.0f} kcal (BMR {bmr:.0f} × activity {factor})."]
    if goal == FitnessGoal.FAT_LOSS:
        if has_eating_disorder_history(profile):
            calories = tdee
            notes.append("No calorie deficit is suggested because your profile mentions an eating "
                         "disorder; please plan weight goals with a doctor or dietitian.")
        elif age < 18 or bmi < 18.5:
            calories = tdee
            notes.append("No calorie deficit is suggested for under-18s or a BMI under 18.5; "
                         "talk to a doctor or dietitian about weight goals.")
        else:
            calories = tdee - min(500, 0.2 * tdee)
            notes.append("Fat loss: a moderate deficit (about 0.5-1% of body weight per week).")
    elif goal == FitnessGoal.MUSCLE_GAIN:
        calories = tdee * 1.10
        notes.append("Muscle gain: a small surplus of about 10%.")
    else:
        calories = tdee
        notes.append("Maintenance calories for your goal.")

    floor = MIN_CALORIES.get(profile.sex, DEFAULT_MIN_CALORIES)
    if calories < floor:
        calories = floor
        notes.append(f"Raised to the {floor} kcal safety minimum.")
    calories = round(calories / 10) * 10

    protein_basis = 25 * (height / 100) ** 2 if bmi > 30 else weight
    protein = round(PROTEIN_G_PER_KG[goal] * protein_basis)
    fat = round(max(0.25 * calories / 9, 0.5 * weight))
    carbs = max(0, round((calories - protein * 4 - fat * 9) / 4))
    notes.append(f"Protein {PROTEIN_G_PER_KG[goal]} g/kg"
                 + (" of a healthy-weight reference" if bmi > 30 else "") + "; fat about 25% of calories.")
    return MacroTotals(calories=calories, protein_g=protein, carbs_g=carbs, fat_g=fat), " ".join(notes), []


def day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """UTC start/end of a calendar day in the given IANA timezone."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidTimezoneError(f"Unknown timezone: {tz_name!r}") from exc
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


# --- Service --------------------------------------------------------------


class NutritionService:
    def __init__(
        self, db: Session, llm: StructuredLLM | None = None, retriever: KnowledgeRetriever | None = None
    ) -> None:
        self.db = db
        self.llm = llm or llm_client.complete_structured
        self.retriever = retriever or KnowledgeRetriever(k=5)

    def estimate(self, request: MealEstimateRequest) -> MealEstimate:
        """Estimate a described meal (not saved).

        Raises:
            MealEstimationError: LLM failure, or nothing in the text was recognised as food.
        """
        docs = self.retriever.retrieve(f"Nutrition values for: {request.description}", topics=["nutrition"])
        messages = [
            {"role": "system", "content": MEAL_ESTIMATION_SYSTEM_PROMPT},
            {"role": "user", "content": MEAL_ESTIMATION_USER_PROMPT.format(
                description=request.description,
                meal_type=request.meal_type or "not specified",
                eaten_at=request.eaten_at.isoformat(timespec="minutes") if request.eaten_at else "not specified",
                reference_material=KnowledgeRetriever.format_context(docs) or NO_REFERENCE_MATERIAL,
            )},
        ]
        try:
            raw = self.llm(messages, EstimatedMeal)
        except LLMError as exc:
            raise MealEstimationError(str(exc), upstream=True) from exc

        items = [clean_item(i) for i in raw.items]
        if not items:
            raise MealEstimationError("Couldn't recognise any food or drink in that description.")
        return MealEstimate(
            description=request.description,
            meal_type=request.meal_type or MealType(raw.meal_type),
            items=items,
            totals=sum_items(items),
            assumptions=raw.assumptions,
        )

    def log(self, user_id: uuid.UUID, payload: NutritionLogCreate) -> NutritionLog:
        entry = NutritionLog(user_id=user_id, **payload.model_dump())
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def log_estimated_meal(self, user_id: uuid.UUID, request: MealEstimateRequest,
                           source: EntrySource = EntrySource.AGENT) -> NutritionLog:
        """Estimate and save in one step (used by the coach agent's `log_meal` tool)."""
        estimate = self.estimate(request)
        return self.log(user_id, NutritionLogCreate(
            eaten_at=request.eaten_at or datetime.now(UTC),
            meal_type=estimate.meal_type,
            description=request.description,
            **estimate.totals.model_dump(),
            is_estimated=True,
            source=source,
        ))

    def get(self, user_id: uuid.UUID, log_id: uuid.UUID) -> NutritionLog | None:
        return self.db.scalar(select(NutritionLog).where(NutritionLog.id == log_id, NutritionLog.user_id == user_id))

    def update(self, entry: NutritionLog, changes: NutritionLogUpdate) -> NutritionLog:
        for field, value in changes.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(entry, field, value)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def delete(self, entry: NutritionLog) -> None:
        self.db.delete(entry)
        self.db.commit()

    def targets(self, profile: UserProfile | None) -> NutritionTargets:
        """Suggested targets from the profile, with any explicit profile targets taking priority."""
        if profile is None:
            return NutritionTargets(effective=None, suggested=None, missing_profile_fields=["profile"],
                                    explanation="Complete your profile to get nutrition targets.")
        suggested, explanation, missing = suggest_targets(profile)
        explicit = {
            "calories": profile.daily_calorie_target, "protein_g": profile.daily_protein_target_g,
            "carbs_g": profile.daily_carbs_target_g, "fat_g": profile.daily_fat_target_g,
        }
        if suggested is None and not any(v is not None for v in explicit.values()):
            effective = None
        else:
            base = suggested.model_dump() if suggested else {k: 0.0 for k in explicit}
            effective = MacroTotals(**{k: (v if v is not None else base[k]) for k, v in explicit.items()})
            if any(v is not None for v in explicit.values()):
                explanation = "Using the targets saved in your profile" + (
                    " (suggestions fill any you left blank). " if suggested else ". ") + explanation
        return NutritionTargets(effective=effective, suggested=suggested, explanation=explanation,
                                missing_profile_fields=missing)

    def daily_summary(self, user_id: uuid.UUID, profile: UserProfile | None, day: date,
                      tz_name: str = "UTC") -> DailyNutritionSummary:
        start, end = day_bounds(day, tz_name)
        entries = list(self.db.scalars(
            select(NutritionLog)
            .where(NutritionLog.user_id == user_id, NutritionLog.eaten_at >= start, NutritionLog.eaten_at < end)
            .order_by(NutritionLog.eaten_at)
        ))
        totals = MacroTotals(
            calories=round(sum(e.calories for e in entries)),
            protein_g=round(sum(e.protein_g for e in entries), 1),
            carbs_g=round(sum(e.carbs_g for e in entries), 1),
            fat_g=round(sum(e.fat_g for e in entries), 1),
        )
        return DailyNutritionSummary(
            day=day, timezone=tz_name, totals=totals, targets=self.targets(profile).effective,
            entries=[NutritionLogRead.model_validate(e) for e in entries],
        )
