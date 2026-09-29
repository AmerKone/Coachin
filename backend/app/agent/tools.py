"""Tools the coaching agent can call (OpenAI function-calling format) and their handlers.

Handlers receive a `ToolContext` and the parsed arguments, perform the action (committing
their own changes), and return a small JSON-serialisable dict that the model reads back.
Invalid input raises `ToolError`, which is returned to the model as `{"error": ...}` so it
can ask the user for clarification instead of failing the turn.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BodyMetric, ExerciseSet, ProgramWorkout, User, WorkoutSession
from app.models.enums import EntrySource, MealType
from app.schemas import MealEstimateRequest
from app.services.exercise_service import find_exercise
from app.services.nutrition_service import MealEstimationError, NutritionService
from app.services.overload_service import OverloadService
from app.services.program_service import ProgramService

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ToolError(Exception):
    """Invalid tool input; the message is shown to the model."""


@dataclass
class ToolContext:
    db: Session
    user: User
    tz_name: str
    nutrition: NutritionService

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def now(self) -> datetime:
        return datetime.now(self.tz)


ToolHandler = Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


def _fn(name: str, description: str, properties: dict[str, Any] | None = None,
        required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _fn("get_todays_workout",
        "Get today's planned workout from the user's active program, with progressive-overload targets "
        "(sets, reps, suggested weight). On rest days, returns the next planned workout."),
    _fn("log_workout_set",
        "Record one set the user just performed in today's workout session. Call once per set.",
        {"exercise_name": {"type": "string", "description": "Exercise name, e.g. 'Barbell Back Squat'"},
         "reps": {"type": "integer", "description": "Repetitions (or seconds for timed holds)"},
         "weight_kg": {"type": ["number", "null"], "description": "Load in kg; null for bodyweight"},
         "rpe": {"type": ["number", "null"], "description": "Effort 1-10 if the user said it"}},
        ["exercise_name", "reps"]),
    _fn("log_meal",
        "Estimate calories and macros for a meal the user ate and save it to today's nutrition log.",
        {"description": {"type": "string", "description": "What the user ate, with any portions they gave"},
         "meal_type": {"type": ["string", "null"], "enum": ["breakfast", "lunch", "dinner", "snack", None]}},
        ["description"]),
    _fn("get_nutrition_summary", "Get today's calories and macros eaten so far versus the user's targets."),
    _fn("log_body_weight", "Record the user's current body weight.",
        {"weight_kg": {"type": "number", "description": "Body weight in kilograms"}}, ["weight_kg"]),
    _fn("swap_exercise",
        "Replace an exercise in all upcoming (not yet logged) workouts of the active program, e.g. when "
        "it causes discomfort or equipment is unavailable. The replacement must suit the user's equipment.",
        {"current_exercise": {"type": "string"}, "replacement_exercise": {"type": "string"},
         "reason": {"type": "string"}},
        ["current_exercise", "replacement_exercise", "reason"]),
]


def _resolve_exercise(ctx: ToolContext, name: str):
    exercise, candidates = find_exercise(ctx.db, name)
    if exercise is None:
        hint = f" Did you mean one of: {', '.join(candidates)}?" if candidates else ""
        raise ToolError(f"No exercise called '{name}' in the library.{hint}")
    return exercise


def _local_day_start(ctx: ToolContext) -> datetime:
    return datetime.combine(ctx.now().date(), time.min, tzinfo=ctx.tz)


def _today_planned(ctx: ToolContext) -> tuple[Any, ProgramWorkout | None]:
    program = ProgramService(ctx.db).get_active(ctx.user.id)
    if program is None:
        return None, None
    today = ctx.now().date()
    week = ProgramService.current_week_number(program, today)
    workout = next((w for w in program.workouts
                    if w.week_number == week and w.day_of_week == today.weekday()), None)
    if today < program.start_date:
        workout = None
    return program, workout


def get_todays_workout(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    program, workout = _today_planned(ctx)
    if program is None:
        return {"status": "no_active_program",
                "message": "The user has no active program; they can generate one on the Program page."}
    overload = OverloadService(ctx.db)

    def describe(w: ProgramWorkout) -> dict[str, Any]:
        targets = overload.targets_for_workout(ctx.user.id, w)
        return {
            "name": w.name, "day": DAY_NAMES[w.day_of_week], "week": w.week_number,
            "already_logged": targets.already_logged,
            "exercises": [{
                "exercise": t.exercise.name, "sets": t.target_sets,
                "reps": f"{t.recommended_reps_min}-{t.recommended_reps_max}",
                "suggested_weight_kg": t.recommended_weight_kg, "target_rpe": t.target_rpe,
                "coach_note": t.notes, "why": t.rationale,
            } for t in targets.exercises],
        }

    if workout is not None:
        return {"status": "training_day", "program": program.name, "workout": describe(workout)}
    upcoming = overload.next_workout(program, ctx.now().date())
    return {"status": "rest_day", "program": program.name,
            "next_workout": describe(upcoming) if upcoming else None}


def log_workout_set(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    reps = args.get("reps")
    if not isinstance(reps, int) or not 0 < reps <= 500:
        raise ToolError("reps must be a whole number between 1 and 500.")
    weight, rpe = args.get("weight_kg"), args.get("rpe")
    if weight is not None and not 0 <= float(weight) <= 1000:
        raise ToolError("weight_kg must be between 0 and 1000.")
    if rpe is not None and not 1 <= float(rpe) <= 10:
        raise ToolError("rpe must be between 1 and 10.")
    exercise = _resolve_exercise(ctx, str(args.get("exercise_name", "")))

    session = ctx.db.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == ctx.user.id, WorkoutSession.started_at >= _local_day_start(ctx))
        .order_by(WorkoutSession.started_at.desc())
        .limit(1)
    )
    if session is None:
        _, planned = _today_planned(ctx)
        session = WorkoutSession(user_id=ctx.user.id, started_at=ctx.now(), source=EntrySource.AGENT,
                                 program_workout_id=planned.id if planned else None)
        ctx.db.add(session)
        ctx.db.flush()

    previous = ctx.db.scalar(
        select(func.count()).select_from(ExerciseSet)
        .where(ExerciseSet.session_id == session.id, ExerciseSet.exercise_id == exercise.id)
    ) or 0
    ctx.db.add(ExerciseSet(session_id=session.id, exercise_id=exercise.id, set_number=previous + 1, reps=reps,
                           weight_kg=float(weight) if weight else None, rpe=float(rpe) if rpe is not None else None))
    session.completed_at = ctx.now()
    ctx.db.commit()
    return {"logged": {"exercise": exercise.name, "set_number": previous + 1, "reps": reps,
                       "weight_kg": weight, "rpe": rpe}}


def log_meal(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    description = str(args.get("description", "")).strip()
    if not description:
        raise ToolError("Describe what the user ate.")
    meal_type = args.get("meal_type")
    try:
        entry = ctx.nutrition.log_estimated_meal(ctx.user.id, MealEstimateRequest(
            description=description[:2000], meal_type=MealType(meal_type) if meal_type else None,
            eaten_at=ctx.now()))
    except MealEstimationError as exc:
        raise ToolError(str(exc)) from exc
    day = ctx.nutrition.daily_summary(ctx.user.id, ctx.user.profile, ctx.now().date(), ctx.tz_name)
    return {
        "logged": {"description": entry.description, "meal_type": entry.meal_type, "calories": entry.calories,
                   "protein_g": entry.protein_g, "carbs_g": entry.carbs_g, "fat_g": entry.fat_g,
                   "note": "Estimated; the user can adjust it on the Nutrition page."},
        "today_totals": day.totals.model_dump(),
        "targets": day.targets.model_dump() if day.targets else None,
    }


def get_nutrition_summary(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    day = ctx.nutrition.daily_summary(ctx.user.id, ctx.user.profile, ctx.now().date(), ctx.tz_name)
    return {
        "date": day.day.isoformat(), "eaten": day.totals.model_dump(),
        "targets": day.targets.model_dump() if day.targets else None,
        "meals": [{"meal_type": e.meal_type, "description": e.description, "calories": e.calories}
                  for e in day.entries],
    }


def log_body_weight(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        weight = float(args.get("weight_kg"))
    except (TypeError, ValueError):
        raise ToolError("weight_kg must be a number.") from None
    if not 20 < weight < 400:
        raise ToolError("That weight looks wrong; it must be between 20 and 400 kg.")
    previous = ctx.user.profile.weight_kg if ctx.user.profile else None
    ctx.db.add(BodyMetric(user_id=ctx.user.id, recorded_at=ctx.now(), weight_kg=weight))
    if ctx.user.profile is not None:
        ctx.user.profile.weight_kg = weight
    ctx.db.commit()
    return {"logged_weight_kg": weight, "previous_profile_weight_kg": previous}


def swap_exercise(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    program = ProgramService(ctx.db).get_active(ctx.user.id)
    if program is None:
        raise ToolError("The user has no active program.")
    current = _resolve_exercise(ctx, str(args.get("current_exercise", "")))
    replacement = _resolve_exercise(ctx, str(args.get("replacement_exercise", "")))
    owned = set(ctx.user.profile.available_equipment if ctx.user.profile else [])
    if missing := set(replacement.equipment) - owned:
        raise ToolError(f"{replacement.name} needs equipment the user doesn't have: {', '.join(sorted(missing))}.")

    logged = set(ctx.db.scalars(select(WorkoutSession.program_workout_id).where(
        WorkoutSession.user_id == ctx.user.id, WorkoutSession.program_workout_id.is_not(None))))
    changed = 0
    for workout in program.workouts:
        if workout.id in logged:
            continue
        for planned in workout.exercises:
            if planned.exercise_id == current.id:
                planned.exercise_id = replacement.id
                planned.notes = f"Swapped from {current.name}: {str(args.get('reason', ''))[:200]}"
                changed += 1
    if not changed:
        raise ToolError(f"{current.name} isn't in any upcoming workout of the active program.")
    ctx.db.commit()
    return {"replaced": current.name, "with": replacement.name, "planned_exercises_updated": changed,
            "caution": replacement.contraindications}


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_todays_workout": get_todays_workout,
    "log_workout_set": log_workout_set,
    "log_meal": log_meal,
    "get_nutrition_summary": get_nutrition_summary,
    "log_body_weight": log_body_weight,
    "swap_exercise": swap_exercise,
}

# Human-readable labels for actions that change data, shown in the chat UI.
ACTION_LABELS = {
    "log_workout_set": "logged_set",
    "log_meal": "logged_meal",
    "log_body_weight": "logged_weight",
    "swap_exercise": "updated_program",
}
