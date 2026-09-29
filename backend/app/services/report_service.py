"""Progress overviews (chart data) and monthly progress reports.

`overview` computes everything from logged data (no LLM): training adherence and volume,
estimated-1RM curves for the most-trained exercises, daily calories vs target, body-weight
trend, and flags worth mentioning carefully. `generate` stores a snapshot of the overview
with an LLM-written summary and recommendations.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.prompts import PROGRESS_REPORT_PROMPT
from app.models import (
    BodyMetric,
    Exercise,
    ExerciseSet,
    NutritionLog,
    ProgramWorkout,
    ProgressReport,
    SafetyEvent,
    TrainingProgram,
    User,
    UserProfile,
    WorkoutSession,
)
from app.models.enums import ProgramStatus
from app.schemas import (
    BodyStats,
    CaloriePoint,
    ExerciseProgress,
    MacroTotals,
    NutritionStats,
    ProgressOverview,
    StrengthPoint,
    TrainingStats,
    VolumePoint,
    WeightPoint,
)
from app.services import llm_client
from app.services.llm_client import LLMError, StructuredLLM
from app.services.nutrition_service import NutritionService, suggest_targets
from app.services.overload_service import estimate_1rm

MAX_STRENGTH_EXERCISES = 4
RAPID_LOSS_PCT_PER_WEEK = 1.0
CALORIE_TOLERANCE = 0.10


class ReportGenerationError(Exception):
    """The LLM couldn't write the report."""


class _ReportText(BaseModel):
    summary: str
    highlights: list[str]
    recommendations: list[str]


def previous_month(today: date) -> tuple[date, date]:
    first_this_month = today.replace(day=1)
    last_prev = first_this_month - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def planned_date(program: TrainingProgram, week_number: int, day_of_week: int) -> date:
    """Calendar date of a planned workout: week 1 is the 7 days starting at `start_date`."""
    week_start = program.start_date + timedelta(weeks=week_number - 1)
    return week_start + timedelta(days=(day_of_week - week_start.weekday()) % 7)


class ReportService:
    def __init__(self, db: Session, llm: StructuredLLM | None = None) -> None:
        self.db = db
        self.llm = llm or llm_client.complete_structured

    # --- Overview ---------------------------------------------------------

    def overview(self, user: User, start: date, end: date, tz_name: str = "UTC") -> ProgressOverview:
        tz = ZoneInfo(tz_name)
        start_utc = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
        end_utc = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)

        def local_day(moment: datetime) -> date:
            return moment.astimezone(tz).date()

        training, volume, strength = self._training(user, start, end, start_utc, end_utc, local_day)
        body, weights = self._body(user, start_utc, end_utc, local_day)
        targets = self.targets_during(user, start, end, body.start_weight_kg)
        nutrition, calories = self._nutrition(user, start_utc, end_utc, local_day, targets)
        safety_events = self.db.scalar(select(func.count()).select_from(SafetyEvent).where(
            SafetyEvent.user_id == user.id, SafetyEvent.created_at >= start_utc, SafetyEvent.created_at < end_utc)) or 0

        flags = []
        if body.weekly_change_pct is not None and body.weekly_change_pct < -RAPID_LOSS_PCT_PER_WEEK:
            flags.append("rapid_weight_loss")
        if (nutrition.protein_target_g and nutrition.avg_protein_g is not None
                and nutrition.days_logged >= 3 and nutrition.avg_protein_g < 0.8 * nutrition.protein_target_g):
            flags.append("low_protein")
        if (nutrition.calorie_target and nutrition.avg_calories is not None and nutrition.days_logged >= 3
                and nutrition.avg_calories < 0.75 * nutrition.calorie_target):
            flags.append("eating_far_below_target")
        if training.adherence_pct is not None and training.workouts_planned >= 4 and training.adherence_pct < 50:
            flags.append("low_adherence")
        if safety_events:
            flags.append("safety_events")

        return ProgressOverview(
            period_start=start, period_end=end, timezone=tz_name, training=training, nutrition=nutrition,
            body=body, weight_series=weights, calorie_series=calories, volume_series=volume,
            strength=strength, safety_events=safety_events, flags=flags,
        )

    def _training(self, user, start, end, start_utc, end_utc, local_day):
        rows = self.db.execute(
            select(WorkoutSession.id, WorkoutSession.started_at, ExerciseSet.exercise_id, ExerciseSet.reps,
                   ExerciseSet.weight_kg, ExerciseSet.is_warmup,
                   (ProgramWorkout.week_number == TrainingProgram.duration_weeks)
                   & (TrainingProgram.duration_weeks >= 4))
            .join(ExerciseSet, ExerciseSet.session_id == WorkoutSession.id, isouter=True)
            .join(ProgramWorkout, ProgramWorkout.id == WorkoutSession.program_workout_id, isouter=True)
            .join(TrainingProgram, TrainingProgram.id == ProgramWorkout.program_id, isouter=True)
            .where(WorkoutSession.user_id == user.id, WorkoutSession.started_at >= start_utc,
                   WorkoutSession.started_at < end_utc)
            .order_by(WorkoutSession.started_at)
        ).all()

        sessions: dict[uuid.UUID, date] = {}
        weeks: dict[date, dict] = defaultdict(lambda: {"sessions": set(), "sets": 0, "volume": 0.0})
        best_1rm: dict[uuid.UUID, dict[date, float]] = defaultdict(dict)
        deload_days: dict[uuid.UUID, set[date]] = defaultdict(set)
        sets_per_exercise: dict[uuid.UUID, int] = defaultdict(int)
        total_sets, total_volume = 0, 0.0
        for session_id, started_at, exercise_id, reps, weight, warmup, is_deload in rows:
            day = local_day(started_at)
            sessions[session_id] = day
            week = weeks[day - timedelta(days=day.weekday())]
            week["sessions"].add(session_id)
            if exercise_id is None or warmup or not reps:
                continue
            total_sets += 1
            week["sets"] += 1
            sets_per_exercise[exercise_id] += 1
            if weight:
                total_volume += weight * reps
                week["volume"] += weight * reps
                e1rm = estimate_1rm(weight, reps)
                best_1rm[exercise_id][day] = max(best_1rm[exercise_id].get(day, 0), e1rm)
                if is_deload:
                    deload_days[exercise_id].add(day)

        volume = [VolumePoint(week_start=w, sessions=len(v["sessions"]), sets=v["sets"],
                              volume_kg=round(v["volume"], 1)) for w, v in sorted(weeks.items())]

        weighted = [ex for ex in sorted(sets_per_exercise, key=sets_per_exercise.get, reverse=True) if best_1rm.get(ex)]
        names = dict(self.db.execute(select(Exercise.id, Exercise.name).where(
            Exercise.id.in_(weighted[:MAX_STRENGTH_EXERCISES]))).all()) if weighted else {}
        strength = []
        for exercise_id in weighted[:MAX_STRENGTH_EXERCISES]:
            by_day = sorted(best_1rm[exercise_id].items())
            # The % change ignores planned deload sessions (still drawn on the curve) and compares
            # the best of the first third of sessions with the best of the last third, so a light
            # week or one off day at either end doesn't flip the trend. Unrounded values.
            trend = [(d, v) for d, v in by_day if d not in deload_days[exercise_id]] or by_day
            window = max(1, len(trend) // 3)
            first = max(v for _, v in trend[:window])
            last = max(v for _, v in trend[-window:])
            strength.append(ExerciseProgress(
                exercise_id=exercise_id, name=names.get(exercise_id, "Exercise"),
                points=[StrengthPoint(day=d, estimated_1rm_kg=round(v, 1)) for d, v in by_day],
                start_1rm_kg=round(first, 1), end_1rm_kg=round(last, 1),
                change_pct=round((last - first) / first * 100, 1)))

        planned = 0
        programs = self.db.scalars(select(TrainingProgram).where(
            TrainingProgram.user_id == user.id,
            TrainingProgram.status.in_([ProgramStatus.ACTIVE, ProgramStatus.COMPLETED])))
        for program in programs:
            planned += sum(1 for w in program.workouts if start <= planned_date(program, w.week_number, w.day_of_week) <= end)

        completed = len(sessions)
        return (
            TrainingStats(sessions_completed=completed, workouts_planned=planned,
                          adherence_pct=round(min(completed / planned, 1.0) * 100, 1) if planned else None,
                          total_sets=total_sets, total_volume_kg=round(total_volume, 1)),
            volume,
            strength,
        )

    def targets_during(self, user: User, start: date, end: date, weight_kg: float | None) -> MacroTotals | None:
        """Nutrition targets that applied in the period (None if its programs had different goals).

        Targets saved in the profile win (their history isn't recorded). Otherwise the suggestion
        is computed for the goal the user had then and their weight at the start of the period,
        so a past fat-loss month isn't judged against today's maintenance calories.
        """
        profile = user.profile
        if profile is None:
            return None
        if any(v is not None for v in (profile.daily_calorie_target, profile.daily_protein_target_g,
                                        profile.daily_carbs_target_g, profile.daily_fat_target_g)):
            return NutritionService(self.db).targets(profile).effective
        if len(self.goals_during(user, start, end)) > 1:
            return None  # e.g. a year spanning a cut and a build has no single meaningful target
        then = UserProfile(
            sex=profile.sex, date_of_birth=profile.date_of_birth, height_cm=profile.height_cm,
            weight_kg=weight_kg or profile.weight_kg, training_days_per_week=profile.training_days_per_week,
            primary_goal=self.goal_during(user, start, end), fitness_level=profile.fitness_level,
        )  # transient: never added to the session
        suggested, _, _ = suggest_targets(then, today=end)
        return suggested

    def _nutrition(self, user, start_utc, end_utc, local_day, targets: MacroTotals | None):
        entries = self.db.scalars(select(NutritionLog).where(
            NutritionLog.user_id == user.id, NutritionLog.eaten_at >= start_utc, NutritionLog.eaten_at < end_utc))
        per_day: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for entry in entries:
            totals = per_day[local_day(entry.eaten_at)]
            totals[0] += entry.calories
            totals[1] += entry.protein_g
        series = [CaloriePoint(day=d, calories=round(c), protein_g=round(p, 1)) for d, (c, p) in sorted(per_day.items())]

        calorie_target = targets.calories if targets and targets.calories else None
        protein_target = targets.protein_g if targets and targets.protein_g else None
        days = len(series)
        return NutritionStats(
            days_logged=days,
            avg_calories=round(sum(p.calories for p in series) / days) if days else None,
            avg_protein_g=round(sum(p.protein_g for p in series) / days, 1) if days else None,
            calorie_target=calorie_target,
            protein_target_g=protein_target,
            days_on_calorie_target=sum(1 for p in series if calorie_target
                                       and abs(p.calories - calorie_target) <= CALORIE_TOLERANCE * calorie_target),
            days_hit_protein=sum(1 for p in series if protein_target and p.protein_g >= protein_target),
        ), series

    def _body(self, user, start_utc, end_utc, local_day):
        metrics = self.db.scalars(select(BodyMetric).where(
            BodyMetric.user_id == user.id, BodyMetric.weight_kg.is_not(None),
            BodyMetric.recorded_at >= start_utc, BodyMetric.recorded_at < end_utc,
        ).order_by(BodyMetric.recorded_at))
        by_day: dict[date, float] = {}
        for metric in metrics:  # last weigh-in of each day wins
            by_day[local_day(metric.recorded_at)] = metric.weight_kg
        series = [WeightPoint(day=d, weight_kg=w) for d, w in sorted(by_day.items())]
        if not series:
            return BodyStats(start_weight_kg=None, end_weight_kg=None, change_kg=None, weekly_change_pct=None), series

        first, last = series[0], series[-1]
        change = round(last.weight_kg - first.weight_kg, 1)
        weeks = (last.day - first.day).days / 7
        weekly = round(change / first.weight_kg * 100 / weeks, 2) if weeks >= 1 else None
        return BodyStats(start_weight_kg=first.weight_kg, end_weight_kg=last.weight_kg,
                         change_kg=change, weekly_change_pct=weekly), series

    # --- Reports ----------------------------------------------------------

    def generate(self, user: User, start: date | None, end: date | None, tz_name: str = "UTC") -> ProgressReport:
        """Compute the overview, have the LLM write the narrative, and upsert the report
        (one per user and period start). Defaults to the previous calendar month.

        Raises:
            ReportGenerationError: the LLM failed.
        """
        today = datetime.now(ZoneInfo(tz_name)).date()
        if start is None or end is None:
            default_start, default_end = previous_month(today)
            start, end = start or default_start, end or default_end
        overview = self.overview(user, start, end, tz_name)
        metrics_json = overview.model_dump_json(exclude={"weight_series", "calorie_series"})
        messages = [{"role": "user", "content": PROGRESS_REPORT_PROMPT.format(
            name=(user.full_name or "the user").split(" ")[0],
            period_start=start.isoformat(), period_end=end.isoformat(),
            goal=str(self.goal_during(user, start, end)).replace("_", " "),
            metrics_json=metrics_json,
        )}]
        try:
            text = self.llm(messages, _ReportText)
        except LLMError as exc:
            raise ReportGenerationError(str(exc)) from exc

        summary = text.summary.strip()
        if text.highlights:
            summary += "\n\n" + "\n".join(f"- {h.strip()}" for h in text.highlights)
        report = self.db.scalar(select(ProgressReport).where(
            ProgressReport.user_id == user.id, ProgressReport.period_start == start))
        if report is None:
            report = ProgressReport(user_id=user.id, period_start=start)
            self.db.add(report)
        report.period_end = end
        report.metrics = overview.model_dump(mode="json")
        report.summary = summary
        report.recommendations = "\n".join(r.strip() for r in text.recommendations[:5]) or None
        self.db.commit()
        self.db.refresh(report)
        return report

    def goals_during(self, user: User, start: date, end: date) -> list[str]:
        """Goals of the (non-draft) programs overlapping the period, most recently started first."""
        programs = self.db.scalars(
            select(TrainingProgram)
            .where(TrainingProgram.user_id == user.id, TrainingProgram.start_date <= end,
                   TrainingProgram.status != ProgramStatus.DRAFT)
            .order_by(TrainingProgram.start_date.desc())
        )
        goals: list[str] = []
        for program in programs:
            if program.start_date + timedelta(weeks=program.duration_weeks) > start and program.goal not in goals:
                goals.append(program.goal)
        return goals

    def goal_during(self, user: User, start: date, end: date) -> str:
        """The goal the user was training for in the period: the goal of the most recently started
        program that overlaps it, falling back to the profile's current goal."""
        goals = self.goals_during(user, start, end)
        if goals:
            return goals[0]
        return user.profile.primary_goal if user.profile else "not set"

    def list_reports(self, user_id: uuid.UUID) -> list[ProgressReport]:
        return list(self.db.scalars(select(ProgressReport).where(ProgressReport.user_id == user_id)
                                    .order_by(ProgressReport.period_start.desc())))

    def get_report(self, user_id: uuid.UUID, report_id: uuid.UUID) -> ProgressReport | None:
        return self.db.scalar(select(ProgressReport).where(
            ProgressReport.id == report_id, ProgressReport.user_id == user_id))

    # --- Body metrics -----------------------------------------------------

    def record_metric(self, user: User, **fields) -> BodyMetric:
        """Store a body measurement; a weight also updates the profile when it's the latest."""
        metric = BodyMetric(user_id=user.id, **fields)
        self.db.add(metric)
        latest = self.db.scalar(select(func.max(BodyMetric.recorded_at)).where(
            BodyMetric.user_id == user.id, BodyMetric.weight_kg.is_not(None)))
        if metric.weight_kg and user.profile is not None and (latest is None or metric.recorded_at >= latest):
            user.profile.weight_kg = metric.weight_kg
        self.db.commit()
        self.db.refresh(metric)
        return metric

    def list_metrics(self, user_id: uuid.UUID, start: date | None, end: date | None) -> list[BodyMetric]:
        stmt = select(BodyMetric).where(BodyMetric.user_id == user_id)
        if start:
            stmt = stmt.where(BodyMetric.recorded_at >= datetime.combine(start, time.min, tzinfo=UTC))
        if end:
            stmt = stmt.where(BodyMetric.recorded_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC))
        return list(self.db.scalars(stmt.order_by(BodyMetric.recorded_at)))
