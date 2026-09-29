"""Personalized training program generation and lifecycle.

Generation flow:
1. Select candidate exercises the user can do with their equipment.
2. Ask the LLM for a one-week template (structured output). The schema restricts exercise
   names to the candidate list, so the model cannot invent or pick unavailable exercises.
3. Validate the template (day count, unique days, sane sets/reps); on problems, ask the
   model to fix them once.
4. Expand the template over `duration_weeks` with gradual RPE progression and a final
   deload week, and save it as a DRAFT program.
"""

import json
import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, create_model
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.agent.prompts import PROGRAM_FIX_PROMPT, PROGRAM_SYSTEM_PROMPT, PROGRAM_USER_PROMPT
from app.models import Exercise, PlannedExercise, ProgramWorkout, TrainingProgram, User, UserProfile
from app.models.enums import FitnessLevel, ProgramStatus
from app.schemas import ProgramGenerateRequest, ProgramUpdate
from app.services import llm_client
from app.services.exercise_service import search_exercises
from app.services.llm_client import LLMError, StructuredLLM

MAX_PLAN_ATTEMPTS = 2
MAX_EXERCISES_PER_WORKOUT = 12
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ProfileRequiredError(Exception):
    """The user has not completed onboarding."""


class ProgramGenerationError(Exception):
    """The LLM could not produce a valid program."""


# --- LLM output schema ----------------------------------------------------


class _GeneratedExercise(BaseModel):
    exercise_name: str
    sets: int
    reps_min: int
    reps_max: int
    target_rpe: float | None
    rest_seconds: int
    notes: str | None


class _GeneratedWorkout(BaseModel):
    day_of_week: int
    name: str
    focus: str
    exercises: list[_GeneratedExercise]


class GeneratedProgram(BaseModel):
    """One-week template returned by the LLM."""

    name: str
    rationale: str
    workouts: list[_GeneratedWorkout]


def build_plan_schema(exercise_names: list[str]) -> type[GeneratedProgram]:
    """Subclass `GeneratedProgram` so `exercise_name` must be one of `exercise_names`."""
    name_type = Literal[tuple(exercise_names)]  # type: ignore[valid-type]
    exercise_model = create_model("PlanExercise", __base__=_GeneratedExercise, exercise_name=(name_type, ...))
    workout_model = create_model(
        "PlanWorkout", __base__=_GeneratedWorkout, exercises=(list[exercise_model], ...)
    )
    return create_model("TrainingPlan", __base__=GeneratedProgram, workouts=(list[workout_model], ...))


def validate_plan(plan: GeneratedProgram, days_per_week: int) -> list[str]:
    """Return human-readable problems with `plan` (empty list if it is acceptable)."""
    errors: list[str] = []
    if len(plan.workouts) != days_per_week:
        errors.append(f"Expected exactly {days_per_week} workouts, got {len(plan.workouts)}.")
    days = [w.day_of_week for w in plan.workouts]
    if any(d not in range(7) for d in days):
        errors.append("day_of_week must be between 0 (Monday) and 6 (Sunday).")
    if len(set(days)) != len(days):
        errors.append("Each workout must be on a different day_of_week.")

    for workout in plan.workouts:
        label = f"Workout '{workout.name}'"
        if not 1 <= len(workout.exercises) <= MAX_EXERCISES_PER_WORKOUT:
            errors.append(f"{label} must have 1-{MAX_EXERCISES_PER_WORKOUT} exercises.")
        names = [e.exercise_name for e in workout.exercises]
        if len(set(names)) != len(names):
            errors.append(f"{label} lists the same exercise more than once.")
        for ex in workout.exercises:
            where = f"{label}, {ex.exercise_name}"
            if not 1 <= ex.sets <= 10:
                errors.append(f"{where}: sets must be 1-10.")
            if not (1 <= ex.reps_min <= ex.reps_max <= 100):
                errors.append(f"{where}: need 1 <= reps_min <= reps_max <= 100.")
            if ex.target_rpe is not None and not 5 <= ex.target_rpe <= 10:
                errors.append(f"{where}: target_rpe must be 5-10.")
            if not 0 <= ex.rest_seconds <= 600:
                errors.append(f"{where}: rest_seconds must be 0-600.")
    return errors


# --- Weekly progression ---------------------------------------------------


def week_prescription(
    sets: int, rpe: float | None, week: int, total_weeks: int, rpe_cap: float
) -> tuple[int, float | None]:
    """Sets and RPE for `week` (1-based): +0.5 RPE per week up to `rpe_cap`; the last week
    of a program of 4+ weeks is a deload (~60% of sets, RPE -2)."""
    base = min(rpe, rpe_cap) if rpe is not None else None
    if total_weeks >= 4 and week == total_weeks:
        return max(1, round(sets * 0.6)), (max(5.0, base - 2) if base is not None else None)
    if base is None:
        return sets, None
    return sets, min(base + 0.5 * (week - 1), rpe_cap)


def rpe_cap_for(profile: UserProfile) -> float:
    if profile.medical_conditions and not profile.medical_clearance:
        return 7.0
    return 8.0 if profile.fitness_level == FitnessLevel.BEGINNER else 9.0


# --- Prompt building ------------------------------------------------------


def describe_profile(profile: UserProfile, today: date) -> str:
    lines = []
    if profile.date_of_birth:
        dob = profile.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        lines.append(f"Age: {age}")
    if profile.sex:
        lines.append(f"Sex: {profile.sex}")
    if profile.height_cm:
        lines.append(f"Height: {profile.height_cm:g} cm")
    if profile.weight_kg:
        lines.append(f"Weight: {profile.weight_kg:g} kg")
    lines.append(f"Experience: {profile.fitness_level}")
    lines.append(f"Equipment: {', '.join(profile.available_equipment) or 'none (bodyweight only)'}")
    lines.append(f"Injuries/limitations: {profile.injuries or 'none reported'}")
    lines.append(f"Medical conditions: {profile.medical_conditions or 'none reported'}")
    if profile.medical_conditions:
        lines.append(f"Doctor clearance for exercise: {'yes' if profile.medical_clearance else 'NO'}")
    return "\n".join(lines)


def describe_exercises(exercises: list[Exercise]) -> str:
    return "\n".join(
        f"- {e.name} | {e.primary_muscle} | {e.category} | "
        f"{', '.join(e.equipment) or 'none'} | {e.contraindications or '-'}"
        for e in exercises
    )


# --- Service --------------------------------------------------------------


class ProgramService:
    def __init__(self, db: Session, llm: StructuredLLM | None = None) -> None:
        self.db = db
        self.llm = llm or llm_client.complete_structured

    # Generation

    def generate(self, user: User, request: ProgramGenerateRequest, today: date | None = None) -> TrainingProgram:
        """Generate and persist a new DRAFT program for `user`.

        Raises:
            ProfileRequiredError: the user has no profile yet.
            ProgramGenerationError: the LLM failed or never produced a valid plan.
        """
        profile = user.profile
        if profile is None:
            raise ProfileRequiredError
        today = today or date.today()
        goal = request.goal or profile.primary_goal
        days_per_week = request.training_days_per_week or profile.training_days_per_week

        candidates, _ = search_exercises(self.db, equipment=profile.available_equipment, limit=1000)
        by_name = {e.name: e for e in candidates}

        user_prompt = PROGRAM_USER_PROMPT.format(
            profile=describe_profile(profile, today),
            days_per_week=days_per_week,
            session_minutes=profile.session_duration_min,
            goal=goal,
            duration_weeks=request.duration_weeks,
            extra_instructions=request.extra_instructions or "none",
            exercise_list=describe_exercises(candidates),
        )
        plan = self._request_plan(user_prompt, list(by_name), days_per_week)

        rpe_cap = rpe_cap_for(profile)
        program = TrainingProgram(
            user_id=user.id,
            name=plan.name[:120],
            goal=goal,
            status=ProgramStatus.DRAFT,
            start_date=request.start_date or today,
            duration_weeks=request.duration_weeks,
            notes=plan.rationale,
        )
        for week in range(1, request.duration_weeks + 1):
            for workout in sorted(plan.workouts, key=lambda w: w.day_of_week):
                planned = []
                for position, ex in enumerate(workout.exercises, start=1):
                    sets, rpe = week_prescription(ex.sets, ex.target_rpe, week, request.duration_weeks, rpe_cap)
                    planned.append(PlannedExercise(
                        exercise_id=by_name[ex.exercise_name].id,
                        position=position,
                        target_sets=sets,
                        target_reps_min=ex.reps_min,
                        target_reps_max=ex.reps_max,
                        target_rpe=rpe,
                        rest_seconds=ex.rest_seconds,
                        notes=ex.notes,
                    ))
                program.workouts.append(ProgramWorkout(
                    week_number=week,
                    day_of_week=workout.day_of_week,
                    name=workout.name[:120],
                    focus=workout.focus[:120] or None,
                    exercises=planned,
                ))

        self.db.add(program)
        self.db.commit()
        return self.get(user.id, program.id)  # type: ignore[return-value]

    def _request_plan(self, user_prompt: str, exercise_names: list[str], days_per_week: int) -> GeneratedProgram:
        schema = build_plan_schema(exercise_names)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": PROGRAM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        errors: list[str] = []
        for _ in range(MAX_PLAN_ATTEMPTS):
            try:
                plan = self.llm(messages, schema)
            except LLMError as exc:
                raise ProgramGenerationError(str(exc)) from exc
            errors = validate_plan(plan, days_per_week)
            if not errors:
                return plan
            messages += [
                {"role": "assistant", "content": json.dumps(plan.model_dump())},
                {"role": "user", "content": PROGRAM_FIX_PROMPT.format(errors="\n".join(f"- {e}" for e in errors))},
            ]
        raise ProgramGenerationError("Generated plan was invalid: " + " ".join(errors))

    # Queries

    def get(self, user_id: uuid.UUID, program_id: uuid.UUID) -> TrainingProgram | None:
        """Load a program with its workouts and exercises, if it belongs to `user_id`."""
        return self.db.scalar(
            select(TrainingProgram)
            .where(TrainingProgram.id == program_id, TrainingProgram.user_id == user_id)
            .options(
                selectinload(TrainingProgram.workouts)
                .selectinload(ProgramWorkout.exercises)
                .selectinload(PlannedExercise.exercise)
            )
            .execution_options(populate_existing=True)
        )

    def list_for_user(self, user_id: uuid.UUID) -> list[TrainingProgram]:
        return list(self.db.scalars(
            select(TrainingProgram)
            .where(TrainingProgram.user_id == user_id)
            .order_by(TrainingProgram.created_at.desc())
        ))

    def get_active(self, user_id: uuid.UUID) -> TrainingProgram | None:
        program_id = self.db.scalar(
            select(TrainingProgram.id).where(
                TrainingProgram.user_id == user_id, TrainingProgram.status == ProgramStatus.ACTIVE
            )
        )
        return self.get(user_id, program_id) if program_id else None

    # Lifecycle

    def activate(self, program: TrainingProgram) -> TrainingProgram:
        """Mark `program` ACTIVE and archive any other active program for the user."""
        self.db.execute(
            update(TrainingProgram)
            .where(
                TrainingProgram.user_id == program.user_id,
                TrainingProgram.status == ProgramStatus.ACTIVE,
                TrainingProgram.id != program.id,
            )
            .values(status=ProgramStatus.ARCHIVED)
        )
        program.status = ProgramStatus.ACTIVE
        self.db.commit()
        return program

    def update(self, program: TrainingProgram, changes: ProgramUpdate) -> TrainingProgram:
        data = changes.model_dump(exclude_unset=True, exclude_none=True)
        status = data.pop("status", None)
        for field, value in data.items():
            setattr(program, field, value)
        if status == ProgramStatus.ACTIVE:
            return self.activate(program)
        if status is not None:
            program.status = status
        self.db.commit()
        return program

    def delete(self, program: TrainingProgram) -> None:
        self.db.delete(program)
        self.db.commit()

    @staticmethod
    def current_week_number(program: TrainingProgram, today: date | None = None) -> int:
        """Week index (1-based) of today within the program, clamped to its duration."""
        days_in = ((today or date.today()) - program.start_date).days
        return min(max(days_in // 7 + 1, 1), program.duration_weeks)

    def this_week(self, program: TrainingProgram, today: date | None = None) -> list[ProgramWorkout]:
        week = self.current_week_number(program, today)
        return [w for w in program.workouts if w.week_number == week]
