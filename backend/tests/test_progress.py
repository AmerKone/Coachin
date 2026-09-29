"""Tests for progress overviews, monthly reports (fake LLM) and body metrics."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.progress import get_report_service
from app.main import app
from app.models import (
    BodyMetric,
    Exercise,
    ExerciseSet,
    NutritionLog,
    PlannedExercise,
    ProgramWorkout,
    TrainingProgram,
    User,
    WorkoutSession,
)
from app.models.enums import ProgramStatus
from app.schemas import ExerciseCreate
from app.services.exercise_service import upsert_exercises
from app.services.llm_client import LLMError
from app.services.report_service import ReportService, planned_date, previous_month
from tests.conftest import clear_exercise_library

PROGRESS = "/api/v1/progress"
SEPT = {"start": "2026-09-01", "end": "2026-09-30"}


def at(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


@pytest.fixture
def user(client: TestClient, auth_headers, db: Session) -> User:
    client.put("/api/v1/users/me/profile", headers=auth_headers, json={
        "sex": "male", "date_of_birth": "1990-01-01", "height_cm": 178, "weight_kg": 70,
        "primary_goal": "strength", "daily_calorie_target": 2000, "daily_protein_target_g": 120})
    return db.scalar(select(User).where(User.email == "alex@example.com"))


@pytest.fixture
def september(db: Session, user: User) -> dict[str, uuid.UUID]:
    """A realistic September: 3 of 4 planned sessions, 3 days of meals, 3 weigh-ins."""
    clear_exercise_library(db)
    upsert_exercises(db, [
        ExerciseCreate(name="Barbell Back Squat", primary_muscle="quadriceps", category="compound", equipment=["barbell"]),
        ExerciseCreate(name="Barbell Bench Press", primary_muscle="chest", category="compound", equipment=["barbell"]),
    ])
    ids = {e.name: e.id for e in db.scalars(select(Exercise))}
    squat, bench = ids["Barbell Back Squat"], ids["Barbell Bench Press"]

    program = TrainingProgram(user_id=user.id, name="Block", goal="strength", status=ProgramStatus.ACTIVE,
                              start_date=date(2026, 9, 7), duration_weeks=2)
    program.workouts = [ProgramWorkout(week_number=w, day_of_week=d, name="W", exercises=[
        PlannedExercise(exercise_id=squat, position=1, target_sets=3, target_reps_min=5, target_reps_max=5)])
        for w in (1, 2) for d in (0, 3)]  # Mon + Thu for 2 weeks = 4 planned in September

    def session(day: str, *sets: tuple) -> WorkoutSession:
        return WorkoutSession(user_id=user.id, started_at=at(day), sets=[
            ExerciseSet(exercise_id=ex, set_number=i, reps=reps, weight_kg=kg, is_warmup=warm)
            for i, (ex, reps, kg, warm) in enumerate(sets, start=1)])

    db.add_all([
        program,
        session("2026-08-28", (squat, 5, 95, False)),  # outside the period
        session("2026-09-07", (squat, 10, 40, True), (squat, 5, 100, False), (squat, 5, 100, False), (squat, 5, 100, False)),
        session("2026-09-10", (squat, 5, 105, False), (squat, 5, 105, False), (bench, 8, 60, False)),
        session("2026-09-14", (squat, 5, 110, False), (squat, 5, 110, False)),
        *[NutritionLog(user_id=user.id, eaten_at=at(day), meal_type="lunch", description="food",
                       calories=kcal, protein_g=protein, carbs_g=0, fat_g=0)
          for day, kcal, protein in [("2026-09-07", 2000, 130), ("2026-09-08", 1500, 80), ("2026-09-09", 2150, 125)]],
        *[BodyMetric(user_id=user.id, recorded_at=at(day), weight_kg=kg)
          for day, kg in [("2026-09-01", 70.0), ("2026-09-15", 69.0), ("2026-09-29", 68.0)]],
    ])
    db.commit()
    return ids


# --- Pure helpers ---------------------------------------------------------


def test_previous_month_and_planned_dates() -> None:
    assert previous_month(date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert previous_month(date(2026, 3, 1)) == (date(2026, 2, 1), date(2026, 2, 28))
    wednesday_start = TrainingProgram(start_date=date(2026, 9, 2), duration_weeks=2)
    assert planned_date(wednesday_start, 1, 2) == date(2026, 9, 2)   # Wednesday of week 1
    assert planned_date(wednesday_start, 1, 0) == date(2026, 9, 7)   # Monday falls 5 days later
    assert planned_date(wednesday_start, 2, 2) == date(2026, 9, 9)


# --- Overview -------------------------------------------------------------


def test_overview_computes_training_nutrition_and_body(client: TestClient, auth_headers, september) -> None:
    response = client.get(f"{PROGRESS}/overview", params=SEPT, headers=auth_headers)
    assert response.status_code == 200, response.text
    o = response.json()

    assert o["training"] == {"sessions_completed": 3, "workouts_planned": 4, "adherence_pct": 75.0,
                             "total_sets": 8, "total_volume_kg": 5 * (300 + 210 + 220) + 480}
    assert [(v["week_start"], v["sessions"], v["sets"]) for v in o["volume_series"]] == [
        ("2026-09-07", 2, 6), ("2026-09-14", 1, 2)]

    squat, bench = o["strength"]  # most-trained first
    assert squat["name"] == "Barbell Back Squat"
    assert [p["estimated_1rm_kg"] for p in squat["points"]] == [116.7, 122.5, 128.3]
    assert squat["change_pct"] == 10.0
    assert bench["points"] == [{"day": "2026-09-10", "estimated_1rm_kg": 76.0}]

    n = o["nutrition"]
    assert (n["days_logged"], n["avg_calories"], n["avg_protein_g"]) == (3, 1883, 111.7)
    assert (n["calorie_target"], n["days_on_calorie_target"], n["days_hit_protein"]) == (2000, 2, 2)

    assert o["body"] == {"start_weight_kg": 70.0, "end_weight_kg": 68.0, "change_kg": -2.0, "weekly_change_pct": -0.71}
    assert [p["weight_kg"] for p in o["weight_series"]] == [70.0, 69.0, 68.0]
    assert o["flags"] == []


def test_overview_flags_rapid_loss_and_low_intake(client: TestClient, auth_headers, user, db: Session) -> None:
    db.add_all([BodyMetric(user_id=user.id, recorded_at=at("2026-09-01"), weight_kg=70),
                BodyMetric(user_id=user.id, recorded_at=at("2026-09-15"), weight_kg=66)])
    db.add_all([NutritionLog(user_id=user.id, eaten_at=at(f"2026-09-0{d}"), meal_type="lunch", description="x",
                             calories=1100, protein_g=60, carbs_g=0, fat_g=0) for d in (2, 3, 4)])
    db.commit()
    o = client.get(f"{PROGRESS}/overview", params=SEPT, headers=auth_headers).json()
    assert o["body"]["weekly_change_pct"] == -2.86
    assert o["flags"] == ["rapid_weight_loss", "low_protein", "eating_far_below_target"]


def test_overview_empty_period_and_validation(client: TestClient, auth_headers, user) -> None:
    o = client.get(f"{PROGRESS}/overview", params=SEPT, headers=auth_headers).json()
    assert o["training"]["sessions_completed"] == 0 and o["training"]["adherence_pct"] is None
    assert o["strength"] == [] and o["nutrition"]["avg_calories"] is None and o["body"]["change_kg"] is None

    backwards = {"start": "2026-09-30", "end": "2026-09-01"}
    assert client.get(f"{PROGRESS}/overview", params=backwards, headers=auth_headers).status_code == 422
    assert client.get(f"{PROGRESS}/overview", params={**SEPT, "tz": "Nowhere/City"},
                      headers=auth_headers).status_code == 422


def test_overview_uses_local_days(client: TestClient, auth_headers, user, db: Session) -> None:
    # 23:30 UTC on Aug 31 is 00:30 on Sept 1 in Algiers (UTC+1): inside September there only.
    db.add(NutritionLog(user_id=user.id, eaten_at=datetime(2026, 8, 31, 23, 30, tzinfo=UTC), meal_type="snack",
                        description="late snack", calories=300, protein_g=10, carbs_g=0, fat_g=0))
    db.commit()
    utc = client.get(f"{PROGRESS}/overview", params=SEPT, headers=auth_headers).json()
    algiers = client.get(f"{PROGRESS}/overview", params={**SEPT, "tz": "Africa/Algiers"}, headers=auth_headers).json()
    assert utc["nutrition"]["days_logged"] == 0
    assert algiers["calorie_series"] == [{"day": "2026-09-01", "calories": 300, "protein_g": 10.0}]


# --- Reports --------------------------------------------------------------

REPORT = {"summary": "A strong month: you trained 3 of 4 planned sessions.",
          "highlights": ["Squat estimated 1RM up 10%"],
          "recommendations": ["Hit all 4 sessions", "Log meals daily", "Add a protein-rich breakfast"]}


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def __call__(self, messages, schema):
        self.prompts.append(messages[0]["content"])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


@pytest.fixture
def use_llm(db: Session):
    def install(fake: FakeLLM) -> FakeLLM:
        app.dependency_overrides[get_report_service] = lambda: ReportService(db, llm=fake)
        return fake
    yield install
    app.dependency_overrides.pop(get_report_service, None)


def test_generate_report_and_regenerate(client: TestClient, auth_headers, september, use_llm) -> None:
    fake = use_llm(FakeLLM(REPORT, {**REPORT, "summary": "Updated summary.", "highlights": []}))
    body = {"period_start": "2026-09-01", "period_end": "2026-09-30"}

    first = client.post(f"{PROGRESS}/reports", headers=auth_headers, json=body)
    assert first.status_code == 201, first.text
    report = first.json()
    assert report["summary"] == "A strong month: you trained 3 of 4 planned sessions.\n\n- Squat estimated 1RM up 10%"
    assert report["recommendations"].splitlines() == REPORT["recommendations"]
    assert report["metrics"]["training"]["adherence_pct"] == 75.0
    assert '"adherence_pct":75.0' in fake.prompts[0] and "Alex" in fake.prompts[0]
    assert "weight_series" not in fake.prompts[0]  # raw series are left out of the prompt

    second = client.post(f"{PROGRESS}/reports", headers=auth_headers, json=body).json()
    assert second["id"] == report["id"] and second["summary"] == "Updated summary."  # upserted
    assert [r["id"] for r in client.get(f"{PROGRESS}/reports", headers=auth_headers).json()] == [report["id"]]


def test_report_defaults_to_previous_month(client: TestClient, auth_headers, user, use_llm) -> None:
    use_llm(FakeLLM(REPORT))
    report = client.post(f"{PROGRESS}/reports", headers=auth_headers, json={}).json()
    expected_start, expected_end = previous_month(date.today())
    assert (report["period_start"], report["period_end"]) == (expected_start.isoformat(), expected_end.isoformat())


def test_report_errors_and_privacy(client: TestClient, auth_headers, user, use_llm) -> None:
    use_llm(FakeLLM(LLMError("down"), REPORT))
    assert client.post(f"{PROGRESS}/reports", headers=auth_headers, json={}).status_code == 502
    bad = {"period_start": "2026-09-30", "period_end": "2026-09-01"}
    assert client.post(f"{PROGRESS}/reports", headers=auth_headers, json=bad).status_code == 422
    assert client.post(f"{PROGRESS}/reports", headers=auth_headers, json={"timezone": "Mars/Base"}).status_code == 422

    report = client.post(f"{PROGRESS}/reports", headers=auth_headers, json={}).json()
    client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "other-password"})
    token = client.post("/api/v1/auth/login", data={"username": "other@example.com",
                                                     "password": "other-password"}).json()["access_token"]
    assert client.get(f"{PROGRESS}/reports/{report['id']}",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 404


# --- Body metrics ---------------------------------------------------------


def test_record_metric_updates_profile_only_when_latest(client: TestClient, auth_headers, user) -> None:
    now = datetime.now(UTC)
    client.post(f"{PROGRESS}/metrics", headers=auth_headers,
                json={"recorded_at": now.isoformat(), "weight_kg": 69.4})
    assert client.get("/api/v1/users/me/profile", headers=auth_headers).json()["weight_kg"] == 69.4

    older = client.post(f"{PROGRESS}/metrics", headers=auth_headers,
                        json={"recorded_at": (now - timedelta(days=10)).isoformat(), "weight_kg": 71.0})
    assert older.status_code == 201
    assert client.get("/api/v1/users/me/profile", headers=auth_headers).json()["weight_kg"] == 69.4  # backfill

    metrics = client.get(f"{PROGRESS}/metrics", headers=auth_headers).json()
    assert [m["weight_kg"] for m in metrics] == [71.0, 69.4]
    assert client.post(f"{PROGRESS}/metrics", headers=auth_headers,
                       json={"recorded_at": now.isoformat(), "weight_kg": 900}).status_code == 422


def test_strength_change_ignores_a_final_deload(client: TestClient, auth_headers, user, db: Session) -> None:
    clear_exercise_library(db)
    upsert_exercises(db, [ExerciseCreate(name="Barbell Back Squat", primary_muscle="quadriceps",
                                         category="compound", equipment=["barbell"])])
    squat = db.scalar(select(Exercise.id))
    # Steady progress, then a lighter deload session on the last day of the month.
    for day, kg in [("2026-09-01", 60), ("2026-09-04", 62.5), ("2026-09-08", 65), ("2026-09-11", 67.5),
                    ("2026-09-15", 70), ("2026-09-26", 55)]:
        db.add(WorkoutSession(user_id=user.id, started_at=at(day),
                              sets=[ExerciseSet(exercise_id=squat, set_number=1, reps=5, weight_kg=kg)]))
    db.commit()
    squat_progress = client.get(f"{PROGRESS}/overview", params=SEPT, headers=auth_headers).json()["strength"][0]
    assert squat_progress["change_pct"] == pytest.approx(12.0, abs=0.1)  # best early (62.5) -> best late (70)
    assert squat_progress["points"][-1]["estimated_1rm_kg"] == 64.2   # the deload is still shown on the curve


def test_strength_change_skips_planned_deload_sessions(client: TestClient, auth_headers, user, db: Session) -> None:
    clear_exercise_library(db)
    upsert_exercises(db, [ExerciseCreate(name="Barbell Back Squat", primary_muscle="quadriceps",
                                         category="compound", equipment=["barbell"])])
    squat = db.scalar(select(Exercise.id))
    program = TrainingProgram(user_id=user.id, name="B", goal="strength", status=ProgramStatus.ACTIVE,
                              start_date=date(2026, 8, 24), duration_weeks=4)
    program.workouts = [ProgramWorkout(week_number=w, day_of_week=0, name=f"W{w}") for w in (1, 2, 3, 4)]
    db.add(program)
    db.flush()
    week = {w.week_number: w.id for w in program.workouts}
    # Only three sessions in the month and the last one is the planned deload (week 4).
    for day, kg, wk in [("2026-09-07", 100, 3), ("2026-09-14", 102.5, 4), ("2026-09-21", 90, 4)]:
        db.add(WorkoutSession(user_id=user.id, started_at=at(day), program_workout_id=week[wk] if day != "2026-09-07" else week[3],
                              sets=[ExerciseSet(exercise_id=squat, set_number=1, reps=5, weight_kg=kg)]))
    db.commit()
    progress = client.get(f"{PROGRESS}/overview", params=SEPT, headers=auth_headers).json()["strength"][0]
    assert len(progress["points"]) == 3                       # deloads are still on the curve
    assert progress["change_pct"] == pytest.approx(0.0)        # only the week-3 session counts: no fake drop


def test_report_uses_goal_of_program_in_that_period(db: Session, user: User) -> None:
    db.add_all([
        TrainingProgram(user_id=user.id, name="Cut", goal="fat_loss", status=ProgramStatus.COMPLETED,
                        start_date=date(2026, 1, 5), duration_weeks=8),
        TrainingProgram(user_id=user.id, name="Build", goal="muscle_gain", status=ProgramStatus.ACTIVE,
                        start_date=date(2026, 3, 2), duration_weeks=8),
        TrainingProgram(user_id=user.id, name="Draft", goal="endurance", status=ProgramStatus.DRAFT,
                        start_date=date(2026, 1, 1), duration_weeks=4),
    ])
    db.commit()
    service = ReportService(db)
    assert service.goal_during(user, date(2026, 1, 1), date(2026, 1, 31)) == "fat_loss"   # drafts ignored
    assert service.goal_during(user, date(2026, 3, 1), date(2026, 3, 31)) == "muscle_gain"
    assert service.goal_during(user, date(2025, 6, 1), date(2025, 6, 30)) == "strength"  # profile fallback


def test_past_month_targets_use_that_periods_goal_and_weight(db: Session, user: User) -> None:
    # Profile today: strength goal, no saved targets. In January she was cutting at 80 kg.
    user.profile.daily_calorie_target = user.profile.daily_protein_target_g = None
    user.profile.weight_kg = 70
    db.add(TrainingProgram(user_id=user.id, name="Cut", goal="fat_loss", status=ProgramStatus.COMPLETED,
                           start_date=date(2026, 1, 5), duration_weeks=8))
    db.commit()
    service = ReportService(db)
    january = service.targets_during(user, date(2026, 1, 1), date(2026, 1, 31), weight_kg=80)
    today = service.targets_during(user, date(2026, 9, 1), date(2026, 9, 30), weight_kg=70)
    assert january.calories < today.calories          # deficit then, maintenance now
    assert january.protein_g == 160                   # 2.0 g/kg x 80 kg for fat loss

    user.profile.daily_calorie_target = 2500          # explicit profile targets always win
    db.commit()
    assert service.targets_during(user, date(2026, 1, 1), date(2026, 1, 31), weight_kg=80).calories == 2500


def test_no_single_target_when_period_spans_different_goals(db: Session, user: User) -> None:
    user.profile.daily_calorie_target = user.profile.daily_protein_target_g = None
    db.add_all([TrainingProgram(user_id=user.id, name="Cut", goal="fat_loss", status=ProgramStatus.COMPLETED,
                                start_date=date(2026, 1, 5), duration_weeks=8),
                TrainingProgram(user_id=user.id, name="Build", goal="muscle_gain", status=ProgramStatus.ACTIVE,
                                start_date=date(2026, 3, 2), duration_weeks=8)])
    db.commit()
    service = ReportService(db)
    assert service.targets_during(user, date(2026, 1, 1), date(2026, 4, 30), weight_kg=75) is None
    assert service.targets_during(user, date(2026, 1, 1), date(2026, 1, 31), weight_kg=75) is not None
