"""Progressive overload: turns logged performance into next-session targets.

Default rule (double progression): when every working set reached the top of the rep range
at or below the target effort, increase the load (see `load_increment`) and restart at the
bottom of the range; otherwise keep the load and add reps. Missing the bottom of the range
at high effort suggests a ~10% reduction.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Exercise, ExerciseSet, PlannedExercise, ProgramWorkout, TrainingProgram, WorkoutSession
from app.models.enums import Equipment, MuscleGroup
from app.schemas import ExerciseHistoryPoint, ExerciseSummary, OverloadRecommendation, WorkoutTargets

LOWER_BODY = {MuscleGroup.QUADRICEPS, MuscleGroup.HAMSTRINGS, MuscleGroup.GLUTES, MuscleGroup.CALVES}
DEFAULT_TARGET_RPE = 8.0
DELOAD_FACTOR = 0.9


@dataclass(frozen=True)
class SetResult:
    reps: int
    weight_kg: float | None = None
    rpe: float | None = None


@dataclass(frozen=True)
class Recommendation:
    weight_kg: float | None
    reps_min: int
    reps_max: int
    rationale: str


def round_weight(kg: float) -> float:
    """Round to the nearest 0.5 kg (the smallest common plate/dumbbell step), halves up.

    Uses floor(x + 0.5) rather than round(), which rounds ties to even (90.25 -> 90.0).
    """
    return math.floor(kg * 2 + 0.5) / 2


def load_increment(exercise: Exercise) -> float:
    """Weight to add when progressing; 0 when load isn't the progression lever."""
    equipment = set(exercise.equipment)
    lower = exercise.primary_muscle in LOWER_BODY
    if equipment & {Equipment.BARBELL, Equipment.MACHINES, Equipment.CABLE_MACHINE}:
        return 5.0 if lower else 2.5
    if Equipment.KETTLEBELLS in equipment:
        return 4.0
    if Equipment.DUMBBELLS in equipment:
        return 2.0
    return 0.0  # bodyweight, bands, cardio machines


def fmt(kg: float) -> str:
    return f"{kg:g} kg"


def recommend(
    exercise: Exercise,
    target_sets: int,
    reps_min: int,
    reps_max: int,
    target_rpe: float | None,
    last_sets: list[SetResult],
) -> Recommendation:
    """Apply double progression to the working sets from the most recent session."""
    working = [s for s in last_sets if s.reps > 0]
    if not working:
        effort = f"RPE {target_rpe:g}" if target_rpe else "a challenging but controlled effort"
        return Recommendation(
            None, reps_min, reps_max,
            f"First time: choose a weight you can lift for {reps_max} reps at about {effort}, with good form.",
        )

    loaded = [s.weight_kg for s in working if s.weight_kg]
    top_weight = max(loaded) if loaded else None
    at_top = [s for s in working if s.weight_kg == top_weight] if top_weight else working
    rpe_limit = (target_rpe or DEFAULT_TARGET_RPE) + 0.5
    max_rpe = max((s.rpe for s in at_top if s.rpe is not None), default=None)
    all_sets_done = len(at_top) >= target_sets
    hit_top = all_sets_done and all(s.reps >= reps_max for s in at_top)
    missed = any(s.reps < reps_min for s in at_top)
    reps_text = ", ".join(str(s.reps) for s in at_top)
    increment = load_increment(exercise)

    if hit_top and (max_rpe is None or max_rpe <= rpe_limit):
        if top_weight and increment:
            new_weight = round_weight(top_weight + increment)
            return Recommendation(
                new_weight, reps_min, reps_max,
                f"All {len(at_top)} sets reached {reps_max}+ reps ({reps_text}) at {fmt(top_weight)}"
                + (f", RPE up to {max_rpe:g}" if max_rpe is not None else "")
                + f". Increase to {fmt(new_weight)} and start again at {reps_min} reps.",
            )
        return Recommendation(
            top_weight, reps_min, reps_max,
            f"You reached the top of the range on every set ({reps_text}). Make it harder: slow the "
            "lowering to 3 seconds, pause at the hardest point, or move to a harder variation"
            + (" or heavier resistance." if not top_weight else "."),
        )

    if missed and (max_rpe is None or max_rpe >= 9):
        if top_weight:
            new_weight = round_weight(top_weight * DELOAD_FACTOR)
            return Recommendation(
                new_weight, reps_min, reps_max,
                f"Some sets fell below {reps_min} reps ({reps_text}) at {fmt(top_weight)} with high effort. "
                f"Drop to {fmt(new_weight)} and build back up.",
            )
        return Recommendation(
            None, reps_min, reps_max,
            f"Some sets fell below {reps_min} reps ({reps_text}). Use an easier variation or a shorter "
            "range of motion until you can reach the rep range with good form.",
        )

    if hit_top:  # reps achieved but effort well above target
        return Recommendation(
            top_weight, reps_min, reps_max,
            f"You hit the reps, but at RPE {max_rpe:g} (target {target_rpe or DEFAULT_TARGET_RPE:g}). "
            + (f"Stay at {fmt(top_weight)}" if top_weight else "Keep the same difficulty")
            + " until it feels easier.",
        )

    keep = f"Stay at {fmt(top_weight)}" if top_weight else "Keep the same variation"
    if not all_sets_done:
        return Recommendation(
            top_weight, reps_min, reps_max,
            f"{keep} and complete all {target_sets} sets before progressing (last time: {reps_text}).",
        )
    return Recommendation(
        top_weight, reps_min, reps_max,
        f"{keep} and add a rep or two per set (last time: {reps_text}). "
        f"Progress when every set reaches {reps_max}.",
    )


def estimate_1rm(weight_kg: float, reps: int) -> float:
    """Epley estimate: weight * (1 + reps / 30); a single rep is the 1RM itself."""
    return weight_kg if reps <= 1 else weight_kg * (1 + reps / 30)


class OverloadService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def last_session_sets(self, user_id: uuid.UUID, exercise_id: uuid.UUID) -> tuple[datetime | None, list[ExerciseSet]]:
        """Working (non-warm-up) sets of `exercise_id` from the user's most recent session with it."""
        latest = self.db.execute(
            select(WorkoutSession.id, WorkoutSession.started_at)
            .join(ExerciseSet, ExerciseSet.session_id == WorkoutSession.id)
            .where(
                WorkoutSession.user_id == user_id,
                ExerciseSet.exercise_id == exercise_id,
                ExerciseSet.is_warmup.is_(False),
            )
            .order_by(WorkoutSession.started_at.desc())
            .limit(1)
        ).first()
        if latest is None:
            return None, []
        sets = self.db.scalars(
            select(ExerciseSet)
            .where(
                ExerciseSet.session_id == latest.id,
                ExerciseSet.exercise_id == exercise_id,
                ExerciseSet.is_warmup.is_(False),
            )
            .order_by(ExerciseSet.set_number)
        ).all()
        return latest.started_at, list(sets)

    def recommend_for_exercise(self, user_id: uuid.UUID, planned: PlannedExercise) -> OverloadRecommendation:
        performed_at, sets = self.last_session_sets(user_id, planned.exercise_id)
        rec = recommend(
            planned.exercise,
            planned.target_sets,
            planned.target_reps_min,
            planned.target_reps_max,
            planned.target_rpe,
            [SetResult(s.reps, s.weight_kg, s.rpe) for s in sets],
        )
        loaded = [s.weight_kg for s in sets if s.weight_kg]
        return OverloadRecommendation(
            planned_exercise_id=planned.id,
            exercise=ExerciseSummary.model_validate(planned.exercise),
            target_sets=planned.target_sets,
            target_rpe=planned.target_rpe,
            rest_seconds=planned.rest_seconds,
            notes=planned.notes,
            last_performed_at=performed_at,
            last_weight_kg=max(loaded) if loaded else None,
            last_reps=[s.reps for s in sets],
            recommended_weight_kg=rec.weight_kg or planned.target_weight_kg,
            recommended_reps_min=rec.reps_min,
            recommended_reps_max=rec.reps_max,
            rationale=rec.rationale,
        )

    def targets_for_workout(self, user_id: uuid.UUID, workout: ProgramWorkout) -> WorkoutTargets:
        return WorkoutTargets(
            program_workout_id=workout.id,
            week_number=workout.week_number,
            day_of_week=workout.day_of_week,
            name=workout.name,
            focus=workout.focus,
            already_logged=bool(self._logged_workout_ids(user_id, [workout.id])),
            exercises=[self.recommend_for_exercise(user_id, p) for p in workout.exercises],
        )

    def get_program_workout(self, user_id: uuid.UUID, program_workout_id: uuid.UUID) -> ProgramWorkout | None:
        return self.db.scalar(
            select(ProgramWorkout)
            .join(TrainingProgram)
            .where(ProgramWorkout.id == program_workout_id, TrainingProgram.user_id == user_id)
            .options(selectinload(ProgramWorkout.exercises).selectinload(PlannedExercise.exercise))
        )

    def next_workout(self, program: TrainingProgram, today: date | None = None) -> ProgramWorkout | None:
        """First planned workout from today onward (in program order) that hasn't been logged."""
        today = today or date.today()
        week = min(max((today - program.start_date).days // 7 + 1, 1), program.duration_weeks)
        if today < program.start_date:
            week, weekday = 1, -1
        else:
            weekday = today.weekday()
        logged = self._logged_workout_ids(program.user_id, [w.id for w in program.workouts])
        for workout in sorted(program.workouts, key=lambda w: (w.week_number, w.day_of_week)):
            if (workout.week_number, workout.day_of_week) >= (week, weekday) and workout.id not in logged:
                return workout
        return None

    def _logged_workout_ids(self, user_id: uuid.UUID, workout_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        if not workout_ids:
            return set()
        return set(self.db.scalars(
            select(WorkoutSession.program_workout_id).where(
                WorkoutSession.user_id == user_id, WorkoutSession.program_workout_id.in_(workout_ids)
            )
        ))

    def history(self, user_id: uuid.UUID, exercise_id: uuid.UUID, weeks: int) -> list[ExerciseHistoryPoint]:
        """Per-session top set, best estimated 1RM, and working volume, oldest first."""
        since = datetime.now(UTC) - timedelta(weeks=weeks)
        rows = self.db.execute(
            select(WorkoutSession.id, WorkoutSession.started_at, ExerciseSet)
            .join(ExerciseSet, ExerciseSet.session_id == WorkoutSession.id)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.started_at >= since,
                ExerciseSet.exercise_id == exercise_id,
                ExerciseSet.is_warmup.is_(False),
            )
            .order_by(WorkoutSession.started_at, ExerciseSet.set_number)
        ).all()

        by_session: dict[uuid.UUID, tuple[datetime, list[ExerciseSet]]] = {}
        for session_id, started_at, exercise_set in rows:
            by_session.setdefault(session_id, (started_at, []))[1].append(exercise_set)

        points = []
        for started_at, sets in by_session.values():
            top = max(sets, key=lambda s: (s.weight_kg or 0, s.reps))
            one_rms = [estimate_1rm(s.weight_kg, s.reps) for s in sets if s.weight_kg and s.reps > 0]
            points.append(ExerciseHistoryPoint(
                performed_at=started_at,
                top_set_weight_kg=top.weight_kg,
                top_set_reps=top.reps,
                estimated_1rm_kg=round(max(one_rms), 1) if one_rms else None,
                total_volume_kg=sum((s.weight_kg or 0) * s.reps for s in sets),
            ))
        return points
