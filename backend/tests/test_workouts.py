"""Tests for workout logging, progressive overload, and exercise history."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise, PlannedExercise, ProgramWorkout, TrainingProgram
from app.models.enums import ProgramStatus
from app.schemas import ExerciseCreate
from app.services.exercise_service import upsert_exercises
from app.services.overload_service import (
    OverloadService,
    SetResult,
    estimate_1rm,
    load_increment,
    recommend,
    round_weight,
)
from tests.conftest import clear_exercise_library

WORKOUTS = "/api/v1/workouts"

LIBRARY = [
    ExerciseCreate(name="Barbell Bench Press", primary_muscle="chest", category="compound",
                   equipment=["barbell", "bench"]),
    ExerciseCreate(name="Barbell Back Squat", primary_muscle="quadriceps", category="compound",
                   equipment=["barbell", "squat rack"]),
    ExerciseCreate(name="Dumbbell Curl", primary_muscle="biceps", category="isolation", equipment=["dumbbells"]),
    ExerciseCreate(name="Goblet Squat", primary_muscle="quadriceps", category="compound", equipment=["kettlebells"]),
    ExerciseCreate(name="Push-Up", primary_muscle="chest", category="compound", is_bodyweight=True),
]


def exercise(name: str) -> Exercise:
    data = next(e for e in LIBRARY if e.name == name).model_dump()
    return Exercise(**data)


def sets(*specs: tuple) -> list[SetResult]:
    return [SetResult(*spec) for spec in specs]


# --- Pure progression rules -----------------------------------------------


def test_first_time_has_no_weight_and_explains() -> None:
    rec = recommend(exercise("Barbell Bench Press"), 3, 8, 12, 8.0, [])
    assert rec.weight_kg is None
    assert (rec.reps_min, rec.reps_max) == (8, 12)
    assert "First time" in rec.rationale and "12 reps" in rec.rationale


@pytest.mark.parametrize(("name", "weight", "expected"), [
    ("Barbell Bench Press", 60.0, 62.5),   # upper-body barbell +2.5
    ("Barbell Back Squat", 100.0, 105.0),  # lower-body barbell +5
    ("Dumbbell Curl", 12.0, 14.0),         # dumbbells +2
    ("Goblet Squat", 16.0, 20.0),          # kettlebells +4
])
def test_hitting_top_of_range_adds_load(name: str, weight: float, expected: float) -> None:
    rec = recommend(exercise(name), 3, 8, 12, 8.0, sets((12, weight, 7.5), (12, weight, 8), (12, weight, 8.5)))
    assert rec.weight_kg == expected
    assert rec.reps_min == 8
    assert f"Increase to {expected:g} kg" in rec.rationale


def test_top_of_range_but_too_hard_keeps_load() -> None:
    rec = recommend(exercise("Barbell Bench Press"), 3, 8, 12, 7.0, sets((12, 60, 9), (12, 60, 9.5), (12, 60, 10)))
    assert rec.weight_kg == 60
    assert "RPE 10" in rec.rationale


def test_mid_range_keeps_load_and_adds_reps() -> None:
    rec = recommend(exercise("Barbell Bench Press"), 3, 8, 12, 8.0, sets((10, 60, 8), (9, 60, 8), (9, 60, 8.5)))
    assert rec.weight_kg == 60
    assert "add a rep or two" in rec.rationale and "10, 9, 9" in rec.rationale


def test_incomplete_sets_keep_load() -> None:
    rec = recommend(exercise("Barbell Bench Press"), 3, 8, 12, 8.0, sets((12, 60, 8), (12, 60, 8)))
    assert rec.weight_kg == 60
    assert "complete all 3 sets" in rec.rationale


def test_missing_reps_at_high_effort_reduces_load() -> None:
    rec = recommend(exercise("Barbell Back Squat"), 3, 8, 12, 8.0, sets((8, 100, 9.5), (6, 100, 10), (5, 100, 10)))
    assert rec.weight_kg == 90.0
    assert "Drop to 90 kg" in rec.rationale


def test_only_heaviest_sets_count() -> None:
    # Back-off sets at a lighter weight shouldn't block progression at the top weight.
    rec = recommend(exercise("Barbell Bench Press"), 2, 8, 12, 8.0,
                    sets((12, 60, 8), (12, 60, 8), (15, 50, 7)))
    assert rec.weight_kg == 62.5


def test_bodyweight_progresses_by_difficulty_not_load() -> None:
    rec = recommend(exercise("Push-Up"), 3, 10, 15, 8.0, sets((15,), (15,), (16,)))
    assert rec.weight_kg is None
    assert "harder variation" in rec.rationale


def test_helpers() -> None:
    assert round_weight(61.3) == 61.5
    assert round_weight(90.25) == 90.5  # ties round up, not to even
    assert round_weight(90.2) == 90.0
    assert load_increment(exercise("Push-Up")) == 0
    assert estimate_1rm(100, 1) == 100
    assert estimate_1rm(100, 5) == pytest.approx(116.67, abs=0.01)


# --- API ------------------------------------------------------------------


@pytest.fixture
def library(db: Session) -> dict[str, uuid.UUID]:
    clear_exercise_library(db)
    upsert_exercises(db, LIBRARY)
    return {e.name: e.id for e in db.scalars(select(Exercise))}


@pytest.fixture
def program(db: Session, registered_user: dict, library: dict[str, uuid.UUID]) -> TrainingProgram:
    """An active 2-week program starting last Monday: Mon = bench + curl, Thu = squat."""
    today = date.today()
    program = TrainingProgram(
        user_id=uuid.UUID(registered_user["id"]), name="Test Block", goal="strength",
        status=ProgramStatus.ACTIVE, start_date=today - timedelta(days=today.weekday()), duration_weeks=2,
    )
    for week in (1, 2):
        program.workouts += [
            ProgramWorkout(week_number=week, day_of_week=0, name="Upper", exercises=[
                PlannedExercise(exercise_id=library["Barbell Bench Press"], position=1, target_sets=3,
                                target_reps_min=8, target_reps_max=12, target_rpe=8, rest_seconds=120,
                                notes="Pause on the chest"),
                PlannedExercise(exercise_id=library["Dumbbell Curl"], position=2, target_sets=2,
                                target_reps_min=10, target_reps_max=15, target_rpe=8, rest_seconds=60),
            ]),
            ProgramWorkout(week_number=week, day_of_week=3, name="Lower", exercises=[
                PlannedExercise(exercise_id=library["Barbell Back Squat"], position=1, target_sets=3,
                                target_reps_min=5, target_reps_max=8, target_rpe=8, rest_seconds=180),
            ]),
        ]
    db.add(program)
    db.commit()
    return program


def workout_id(program: TrainingProgram, week: int, day: int) -> str:
    return str(next(w.id for w in program.workouts if w.week_number == week and w.day_of_week == day))


def session_body(exercise_id: uuid.UUID, reps: list[int], weight: float | None, rpe: float | None = 8,
                 program_workout_id: str | None = None, days_ago: int = 0) -> dict:
    started = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "program_workout_id": program_workout_id,
        "started_at": started.isoformat(),
        "completed_at": (started + timedelta(minutes=50)).isoformat(),
        "session_rpe": 7,
        "sets": [{"exercise_id": str(exercise_id), "set_number": i, "reps": r, "weight_kg": weight, "rpe": rpe}
                 for i, r in enumerate(reps, start=1)],
    }


def test_log_and_read_session(client: TestClient, auth_headers, library, program) -> None:
    body = session_body(library["Barbell Bench Press"], [12, 12, 11], 60, program_workout_id=workout_id(program, 1, 0))
    created = client.post(WORKOUTS, json=body, headers=auth_headers)
    assert created.status_code == 201, created.text
    session = created.json()
    assert [s["reps"] for s in session["sets"]] == [12, 12, 11]
    assert session["sets"][0]["exercise"]["name"] == "Barbell Bench Press"

    fetched = client.get(f"{WORKOUTS}/{session['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["program_workout_id"] == body["program_workout_id"]


def test_log_session_validation(client: TestClient, auth_headers, library) -> None:
    unknown = session_body(uuid.uuid4(), [10], 50)
    assert client.post(WORKOUTS, json=unknown, headers=auth_headers).status_code == 422

    foreign_workout = session_body(library["Push-Up"], [10], None, program_workout_id=str(uuid.uuid4()))
    assert client.post(WORKOUTS, json=foreign_workout, headers=auth_headers).status_code == 404

    backwards = session_body(library["Push-Up"], [10], None)
    backwards["completed_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert client.post(WORKOUTS, json=backwards, headers=auth_headers).status_code == 422

    negative = session_body(library["Push-Up"], [-1], None)
    assert client.post(WORKOUTS, json=negative, headers=auth_headers).status_code == 422


def test_list_filters_and_paginates(client: TestClient, auth_headers, library) -> None:
    for days_ago in (0, 3, 10):
        client.post(WORKOUTS, json=session_body(library["Push-Up"], [10], None, days_ago=days_ago), headers=auth_headers)

    page = client.get(WORKOUTS, params={"limit": 2}, headers=auth_headers).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["started_at"] > page["items"][1]["started_at"]  # newest first

    recent = client.get(WORKOUTS, params={"start": (date.today() - timedelta(days=5)).isoformat()},
                        headers=auth_headers).json()
    assert recent["total"] == 2


def test_update_add_sets_and_delete(client: TestClient, auth_headers, library) -> None:
    session = client.post(WORKOUTS, json=session_body(library["Push-Up"], [10], None), headers=auth_headers).json()
    url = f"{WORKOUTS}/{session['id']}"

    updated = client.patch(url, json={"notes": "Felt strong", "session_rpe": 8}, headers=auth_headers).json()
    assert (updated["notes"], updated["session_rpe"]) == ("Felt strong", 8)

    more = [{"exercise_id": str(library["Push-Up"]), "set_number": 2, "reps": 9}]
    assert len(client.post(f"{url}/sets", json=more, headers=auth_headers).json()["sets"]) == 2
    bad = [{"exercise_id": str(uuid.uuid4()), "set_number": 3, "reps": 5}]
    assert client.post(f"{url}/sets", json=bad, headers=auth_headers).status_code == 422

    assert client.delete(url, headers=auth_headers).status_code == 204
    assert client.get(url, headers=auth_headers).status_code == 404


def test_sessions_are_private(client: TestClient, auth_headers, library) -> None:
    session = client.post(WORKOUTS, json=session_body(library["Push-Up"], [10], None), headers=auth_headers).json()
    client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "other-password"})
    token = client.post("/api/v1/auth/login", data={"username": "other@example.com",
                                                     "password": "other-password"}).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{WORKOUTS}/{session['id']}", headers=other).status_code == 404
    assert client.delete(f"{WORKOUTS}/{session['id']}", headers=other).status_code == 404
    assert client.get(WORKOUTS, headers=other).json()["total"] == 0


def test_recommendations_use_logged_performance(client: TestClient, auth_headers, library, program) -> None:
    upper = workout_id(program, 1, 0)
    first = client.get(f"{WORKOUTS}/recommendations/next", params={"program_workout_id": upper},
                       headers=auth_headers).json()
    bench = first["exercises"][0]
    assert bench["exercise"]["name"] == "Barbell Bench Press"
    assert bench["recommended_weight_kg"] is None and bench["last_reps"] == []
    assert bench["notes"] == "Pause on the chest" and bench["target_sets"] == 3
    assert first["already_logged"] is False

    client.post(WORKOUTS, json=session_body(library["Barbell Bench Press"], [12, 12, 12], 60, rpe=8,
                                            program_workout_id=upper), headers=auth_headers)

    after = client.get(f"{WORKOUTS}/recommendations/next", params={"program_workout_id": upper},
                       headers=auth_headers).json()
    bench = after["exercises"][0]
    assert after["already_logged"] is True
    assert bench["last_weight_kg"] == 60 and bench["last_reps"] == [12, 12, 12]
    assert bench["recommended_weight_kg"] == 62.5
    assert after["exercises"][1]["recommended_weight_kg"] is None  # curl never logged


def test_next_workout_skips_logged_ones(db: Session, library, program) -> None:
    overload = OverloadService(db)
    monday = program.start_date
    assert overload.next_workout(program, today=monday).name == "Upper"

    # After logging Monday's workout, the next one is Thursday's.
    from app.models import WorkoutSession
    db.add(WorkoutSession(user_id=program.user_id, program_workout_id=uuid.UUID(workout_id(program, 1, 0)),
                          started_at=datetime.now(UTC)))
    db.commit()
    assert overload.next_workout(program, today=monday).name == "Lower"
    # On Friday of week 2 there is nothing left.
    assert overload.next_workout(program, today=monday + timedelta(days=11)) is None


def test_next_endpoint_without_active_program(client: TestClient, auth_headers) -> None:
    response = client.get(f"{WORKOUTS}/recommendations/next", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "No active program"


def test_exercise_history(client: TestClient, auth_headers, library) -> None:
    squat = library["Barbell Back Squat"]
    client.post(WORKOUTS, json=session_body(squat, [8, 8, 7], 100, days_ago=7), headers=auth_headers)
    client.post(WORKOUTS, json=session_body(squat, [5, 5], 110, days_ago=1), headers=auth_headers)

    history = client.get(f"{WORKOUTS}/history/{squat}", headers=auth_headers).json()
    assert [p["top_set_weight_kg"] for p in history] == [100, 110]  # oldest first
    assert history[0]["total_volume_kg"] == 100 * 23
    assert history[0]["estimated_1rm_kg"] == pytest.approx(126.7, abs=0.1)
    assert history[1]["estimated_1rm_kg"] == pytest.approx(128.3, abs=0.1)
