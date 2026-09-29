"""Coach tools that look up the user's past: exercise history and PRs, progress over any period,
logged workouts, and saved monthly reports.

Dates are ISO `YYYY-MM-DD` calendar days in the user's timezone. The model resolves relative
phrases ("in January", "last week") itself using the current date given in its prompt.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import Exercise, ExerciseSet, ProgressReport, WorkoutSession
from app.services.exercise_service import find_exercise
from app.services.overload_service import estimate_1rm
from app.services.report_service import ReportService

if TYPE_CHECKING:
    from app.agent.tools import ToolContext

MAX_EXERCISES = 3
MAX_SESSIONS_LISTED = 20
MAX_PERIOD_DAYS = 400


def _tool_error(message: str) -> Exception:
    from app.agent.tools import ToolError  # local import: tools.py imports this module

    return ToolError(message)


def _parse_day(value: Any, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise _tool_error(f"{name} must be a date like 2026-01-31.") from None


def _period(ctx: "ToolContext", args: dict[str, Any], default_days: int | None = None) -> tuple[date, date]:
    """(start, end) from the arguments; defaults to the user's whole history or `default_days`."""
    today = ctx.now().date()
    end = _parse_day(args.get("end_date"), "end_date") or today
    start = _parse_day(args.get("start_date"), "start_date")
    if start is None:
        if default_days is not None:
            start = end - timedelta(days=default_days - 1)
        else:
            first = ctx.db.scalar(select(func.min(WorkoutSession.started_at)).where(
                WorkoutSession.user_id == ctx.user.id))
            start = first.astimezone(ctx.tz).date() if first else end
    if end < start:
        raise _tool_error("end_date must be on or after start_date.")
    return start, end


def _bounds(ctx: "ToolContext", start: date, end: date) -> tuple[datetime, datetime]:
    return (datetime.combine(start, time.min, tzinfo=ctx.tz).astimezone(UTC),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=ctx.tz).astimezone(UTC))


def _resolve_logged_exercises(ctx: "ToolContext", name: str, start_utc: datetime, end_utc: datetime) -> list[Exercise]:
    """Exercises matching `name`, preferring those the user actually logged in the period.

    "bench press" matches several library exercises; if only one of them was trained in the
    period, that's the one meant. Returns up to MAX_EXERCISES exercises.
    """
    exact, candidates = find_exercise(ctx.db, name)
    if exact is not None:
        return [exact]
    words = [w for w in name.lower().split() if w]
    if not words:
        raise _tool_error("Give an exercise name.")
    stmt = (select(Exercise).join(ExerciseSet, ExerciseSet.exercise_id == Exercise.id)
            .join(WorkoutSession, WorkoutSession.id == ExerciseSet.session_id)
            .where(WorkoutSession.user_id == ctx.user.id, WorkoutSession.started_at >= start_utc,
                   WorkoutSession.started_at < end_utc))
    for word in words:
        escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Exercise.name.ilike(f"%{escaped}%", escape="\\"))
    logged = list(ctx.db.scalars(stmt.group_by(Exercise.id).order_by(func.count(ExerciseSet.id).desc())))
    if logged:
        return logged[:MAX_EXERCISES]
    if candidates:
        raise _tool_error(f"The user didn't log any of these in that period: {', '.join(candidates)}.")
    raise _tool_error(f"No exercise matching '{name}' in the library.")


def _set_text(s: ExerciseSet) -> str:
    return f"{s.weight_kg:g} kg x {s.reps}" if s.weight_kg else f"{s.reps} reps (bodyweight)"


def _exercise_summary(ctx: "ToolContext", exercise: Exercise, start_utc: datetime, end_utc: datetime) -> dict[str, Any]:
    rows = ctx.db.execute(
        select(WorkoutSession.started_at, ExerciseSet)
        .join(ExerciseSet, ExerciseSet.session_id == WorkoutSession.id)
        .where(WorkoutSession.user_id == ctx.user.id, ExerciseSet.exercise_id == exercise.id,
               ExerciseSet.is_warmup.is_(False))
        .order_by(WorkoutSession.started_at, ExerciseSet.set_number)
    ).all()
    in_period = [(started, s) for started, s in rows if start_utc <= started < end_utc]

    def records(pairs) -> dict[str, Any] | None:
        if not pairs:
            return None
        day = lambda started: started.astimezone(ctx.tz).date().isoformat()  # noqa: E731
        weighted = [(st, s) for st, s in pairs if s.weight_kg]
        result: dict[str, Any] = {}
        if weighted:
            heaviest = max(weighted, key=lambda p: (p[1].weight_kg, p[1].reps))
            best = max(weighted, key=lambda p: estimate_1rm(p[1].weight_kg, p[1].reps))
            result["heaviest_set"] = {"set": _set_text(heaviest[1]), "date": day(heaviest[0])}
            result["best_estimated_1rm_kg"] = {"value": round(estimate_1rm(best[1].weight_kg, best[1].reps), 1),
                                               "from_set": _set_text(best[1]), "date": day(best[0])}
        most_reps = max(pairs, key=lambda p: (p[1].reps, p[1].weight_kg or 0))
        result["most_reps_in_a_set"] = {"set": _set_text(most_reps[1]), "date": day(most_reps[0])}
        return result

    sessions: dict[date, list[ExerciseSet]] = {}
    for started, s in in_period:
        sessions.setdefault(started.astimezone(ctx.tz).date(), []).append(s)
    listed = [{"date": d.isoformat(), "sets": [_set_text(s) for s in sets]} for d, sets in sessions.items()]
    return {
        "exercise": exercise.name,
        "sessions_in_period": len(sessions),
        "records_in_period": records(in_period),
        "all_time_records": records(rows),
        "first_ever_logged": rows[0][0].astimezone(ctx.tz).date().isoformat() if rows else None,
        "sessions": listed[-MAX_SESSIONS_LISTED:],
        "note": (f"Only the last {MAX_SESSIONS_LISTED} sessions are listed." if len(listed) > MAX_SESSIONS_LISTED
                 else None),
    }


def get_exercise_history(ctx: "ToolContext", args: dict[str, Any]) -> dict[str, Any]:
    start, end = _period(ctx, args)
    start_utc, end_utc = _bounds(ctx, start, end)
    exercises = _resolve_logged_exercises(ctx, str(args.get("exercise_name", "")), start_utc, end_utc)
    return {"period": {"start": start.isoformat(), "end": end.isoformat()},
            "results": [_exercise_summary(ctx, e, start_utc, end_utc) for e in exercises]}


def get_progress_summary(ctx: "ToolContext", args: dict[str, Any]) -> dict[str, Any]:
    start, end = _period(ctx, args, default_days=30)
    if (end - start).days > MAX_PERIOD_DAYS:
        raise _tool_error(f"Periods are limited to {MAX_PERIOD_DAYS} days.")
    overview = ReportService(ctx.db).overview(ctx.user, start, end, ctx.tz_name)
    weights = [p.weight_kg for p in overview.weight_series]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "training": overview.training.model_dump(),
        "strength_changes": [{"exercise": e.name, "start_estimated_1rm_kg": e.start_1rm_kg,
                              "end_estimated_1rm_kg": e.end_1rm_kg, "change_pct": e.change_pct}
                             for e in overview.strength],
        "nutrition": overview.nutrition.model_dump(),
        "body_weight": {**overview.body.model_dump(),
                        "lowest_kg": min(weights) if weights else None,
                        "highest_kg": max(weights) if weights else None,
                        "weigh_ins": len(weights)},
        "flags": overview.flags,
    }


def get_workouts(ctx: "ToolContext", args: dict[str, Any]) -> dict[str, Any]:
    start, end = _period(ctx, args, default_days=7)
    start_utc, end_utc = _bounds(ctx, start, end)
    sessions = list(ctx.db.scalars(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == ctx.user.id, WorkoutSession.started_at >= start_utc,
               WorkoutSession.started_at < end_utc)
        .order_by(WorkoutSession.started_at)
    ))
    listed = []
    for session in sessions[-10:]:
        exercises: dict[str, list[str]] = {}
        for s in sorted(session.sets, key=lambda s: s.set_number):
            exercises.setdefault(s.exercise.name, []).append(_set_text(s))
        listed.append({"date": session.started_at.astimezone(ctx.tz).strftime("%A %Y-%m-%d"),
                       "session_rpe": session.session_rpe, "notes": session.notes, "exercises": exercises})
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "sessions_found": len(sessions),
            "sessions": listed, "note": "Only the last 10 sessions are listed." if len(sessions) > 10 else None}


def get_monthly_report(ctx: "ToolContext", args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("month", "")).strip()
    try:
        month = date.fromisoformat(f"{raw[:7]}-01")
    except ValueError:
        raise _tool_error("month must look like 2026-06.") from None
    report = ctx.db.scalar(select(ProgressReport).where(
        ProgressReport.user_id == ctx.user.id, ProgressReport.period_start == month))
    if report is None:
        return {"month": month.strftime("%Y-%m"), "report": None,
                "note": "No saved report for that month; get_progress_summary can compute its numbers."}
    return {"month": month.strftime("%Y-%m"), "summary": report.summary,
            "recommendations": (report.recommendations or "").splitlines()}


def history_hint(ctx_db, user_id: uuid.UUID, tz) -> str:
    """One line for the system prompt telling the model how much history exists."""
    first, count = ctx_db.execute(select(func.min(WorkoutSession.started_at), func.count(WorkoutSession.id))
                                  .where(WorkoutSession.user_id == user_id)).one()
    if not count:
        return "Training history: no workouts logged yet."
    return (f"Training history: {count} workouts logged since {first.astimezone(tz):%d %B %Y}. Use the history "
            "tools to answer any question about past workouts, records, progress, weight or reports.")


_DATE = {"type": ["string", "null"], "description": "YYYY-MM-DD in the user's calendar"}

HISTORY_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "get_exercise_history",
        "description": "Look up the user's logged history for an exercise: personal records (heaviest set, best "
                       "estimated 1RM, most reps) in a period and all-time, and the sets of each session. Use for "
                       "questions like 'what was my bench PR in January' or 'how has my squat progressed'. "
                       "Omit dates for the whole history.",
        "parameters": {"type": "object", "properties": {
            "exercise_name": {"type": "string", "description": "e.g. 'bench press', 'Barbell Back Squat'"},
            "start_date": _DATE, "end_date": _DATE}, "required": ["exercise_name"]}}},
    {"type": "function", "function": {
        "name": "get_progress_summary",
        "description": "Summarise progress over any period (up to ~13 months): sessions done vs planned, strength "
                       "changes, average calories/protein vs targets, body-weight change, and flags. Defaults to "
                       "the last 30 days.",
        "parameters": {"type": "object", "properties": {"start_date": _DATE, "end_date": _DATE}}}},
    {"type": "function", "function": {
        "name": "get_workouts",
        "description": "List the workouts the user logged in a period with every exercise and set. Defaults to "
                       "the last 7 days.",
        "parameters": {"type": "object", "properties": {"start_date": _DATE, "end_date": _DATE}}}},
    {"type": "function", "function": {
        "name": "get_monthly_report",
        "description": "Fetch the saved monthly progress report (summary and recommendations) for a month.",
        "parameters": {"type": "object", "properties": {
            "month": {"type": "string", "description": "YYYY-MM"}}, "required": ["month"]}}},
]

HISTORY_TOOL_HANDLERS = {
    "get_exercise_history": get_exercise_history,
    "get_progress_summary": get_progress_summary,
    "get_workouts": get_workouts,
    "get_monthly_report": get_monthly_report,
}
