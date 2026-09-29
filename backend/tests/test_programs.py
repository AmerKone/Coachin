"""Tests for program generation and lifecycle, using a fake LLM (no OpenAI calls)."""

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.routes.programs import get_program_service
from app.main import app
from app.models import Exercise
from app.schemas import ExerciseCreate
from app.services.exercise_service import upsert_exercises
from app.services.llm_client import LLMError
from app.services.program_service import (
    ProgramService,
    build_plan_schema,
    validate_plan,
    week_prescription,
)

PROGRAMS = "/api/v1/programs"
PROFILE = "/api/v1/users/me/profile"

LIBRARY = [
    ExerciseCreate(name="Dumbbell Bench Press", primary_muscle="chest", category="compound",
                   equipment=["dumbbells", "bench"]),
    ExerciseCreate(name="Push-Up", primary_muscle="chest", category="compound", is_bodyweight=True),
    ExerciseCreate(name="Goblet Squat", primary_muscle="quadriceps", category="compound", equipment=["dumbbells"]),
    ExerciseCreate(name="Barbell Back Squat", primary_muscle="quadriceps", category="compound",
                   equipment=["barbell", "squat rack"]),
    ExerciseCreate(name="One-Arm Dumbbell Row", primary_muscle="back", category="compound",
                   equipment=["dumbbells", "bench"]),
    ExerciseCreate(name="Plank", primary_muscle="core", category="isolation", is_bodyweight=True),
]


def ex(name: str, sets: int = 3, rpe: float | None = 9.0) -> dict[str, Any]:
    return {"exercise_name": name, "sets": sets, "reps_min": 8, "reps_max": 12,
            "target_rpe": rpe, "rest_seconds": 90, "notes": None}


VALID_PLAN = {
    "name": "Full-Body Foundations",
    "rationale": "Three full-body sessions fit your schedule.",
    "workouts": [
        {"day_of_week": 0, "name": "Full Body A", "focus": "Push + squat",
         "exercises": [ex("Goblet Squat"), ex("Dumbbell Bench Press"), ex("Plank", rpe=None)]},
        {"day_of_week": 2, "name": "Full Body B", "focus": "Pull",
         "exercises": [ex("One-Arm Dumbbell Row", sets=5), ex("Push-Up")]},
        {"day_of_week": 4, "name": "Full Body C", "focus": "Mixed",
         "exercises": [ex("Goblet Squat"), ex("One-Arm Dumbbell Row")]},
    ],
}


class FakeLLM:
    """Returns queued plans in order and records every call."""

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, Any]], type]] = []

    def __call__(self, messages, schema):
        self.calls.append((copy.deepcopy(messages), schema))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


@pytest.fixture
def library(db: Session) -> None:
    db.execute(Exercise.__table__.delete())  # rolled back after the test
    upsert_exercises(db, LIBRARY)


@pytest.fixture
def profile(client: TestClient, auth_headers: dict) -> dict:
    response = client.put(PROFILE, headers=auth_headers, json={
        "fitness_level": "beginner", "primary_goal": "general_fitness", "training_days_per_week": 3,
        "available_equipment": ["dumbbells", "bench"], "injuries": "Sore left wrist",
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def use_llm(db: Session):
    """Call with a FakeLLM to route program generation through it."""
    def install(fake: FakeLLM) -> FakeLLM:
        app.dependency_overrides[get_program_service] = lambda: ProgramService(db, llm=fake)
        return fake
    yield install
    app.dependency_overrides.pop(get_program_service, None)


def generate(client: TestClient, headers: dict, **body) -> Any:
    return client.post(f"{PROGRAMS}/generate", json={"duration_weeks": 4, **body}, headers=headers)


# --- Pure functions -------------------------------------------------------


def test_plan_schema_only_allows_listed_exercises() -> None:
    schema = build_plan_schema(["Push-Up", "Plank"])
    bad = copy.deepcopy(VALID_PLAN)
    with pytest.raises(ValidationError):
        schema.model_validate(bad)  # uses exercises outside the allowed list
    ok = {"name": "x", "rationale": "y", "workouts": [
        {"day_of_week": 0, "name": "A", "focus": "", "exercises": [ex("Push-Up"), ex("Plank")]}]}
    assert schema.model_validate(ok).workouts[0].exercises[1].exercise_name == "Plank"


def test_validate_plan_reports_problems() -> None:
    schema = build_plan_schema([e.name for e in LIBRARY])
    assert validate_plan(schema.model_validate(VALID_PLAN), days_per_week=3) == []

    broken = copy.deepcopy(VALID_PLAN)
    broken["workouts"][1]["day_of_week"] = 0
    broken["workouts"][2]["exercises"][0]["reps_min"] = 20  # above reps_max
    broken["workouts"][2]["exercises"].append(ex("Goblet Squat"))  # duplicate in a day
    errors = validate_plan(schema.model_validate(broken), days_per_week=4)
    assert any("Expected exactly 4" in e for e in errors)
    assert any("different day_of_week" in e for e in errors)
    assert any("reps_min" in e for e in errors)
    assert any("more than once" in e for e in errors)


def test_week_prescription_progresses_caps_and_deloads() -> None:
    assert week_prescription(3, 7.0, week=1, total_weeks=4, rpe_cap=9) == (3, 7.0)
    assert week_prescription(3, 7.0, week=3, total_weeks=4, rpe_cap=9) == (3, 8.0)
    assert week_prescription(3, 8.5, week=3, total_weeks=6, rpe_cap=9) == (3, 9.0)  # capped
    assert week_prescription(5, 10.0, week=4, total_weeks=4, rpe_cap=7) == (3, 5.0)  # deload from cap
    assert week_prescription(3, None, week=2, total_weeks=3, rpe_cap=9) == (3, None)  # no deload < 4 weeks


# --- Generation endpoint --------------------------------------------------


def test_generate_program(client, auth_headers, library, profile, use_llm) -> None:
    fake = use_llm(FakeLLM(VALID_PLAN))
    response = generate(client, auth_headers, extra_instructions="Keep sessions short")
    assert response.status_code == 201, response.text
    program = response.json()

    assert program["status"] == "draft"
    assert program["name"] == "Full-Body Foundations"
    assert program["notes"] == VALID_PLAN["rationale"]
    assert len(program["workouts"]) == 4 * 3
    assert [w["day_of_week"] for w in program["workouts"][:3]] == [0, 2, 4]

    week1 = [w for w in program["workouts"] if w["week_number"] == 1]
    week4 = [w for w in program["workouts"] if w["week_number"] == 4]
    squat_w1 = week1[0]["exercises"][0]
    assert squat_w1["exercise"]["name"] == "Goblet Squat"
    assert squat_w1["target_rpe"] == 8.0  # beginner cap applied to the model's RPE 9
    assert week4[1]["exercises"][0]["target_sets"] == 3  # deload: 5 sets -> 3
    assert week1[0]["exercises"][2]["target_rpe"] is None

    # The prompt carries the profile and only exercises the user's equipment allows.
    messages, schema = fake.calls[0]
    prompt = messages[1]["content"]
    assert "Sore left wrist" in prompt and "Keep sessions short" in prompt
    assert "Goblet Squat" in prompt and "Barbell Back Squat" not in prompt
    bad_plan = copy.deepcopy(VALID_PLAN)
    bad_plan["workouts"][0]["exercises"][0]["exercise_name"] = "Barbell Back Squat"
    with pytest.raises(ValidationError):
        schema.model_validate(bad_plan)


def test_generate_asks_model_to_fix_an_invalid_plan(client, auth_headers, library, profile, use_llm) -> None:
    two_days = copy.deepcopy(VALID_PLAN)
    two_days["workouts"] = two_days["workouts"][:2]
    fake = use_llm(FakeLLM(two_days, VALID_PLAN))

    response = generate(client, auth_headers)
    assert response.status_code == 201, response.text
    assert len(fake.calls) == 2
    fix_request = fake.calls[1][0][-1]["content"]
    assert "Expected exactly 3 workouts, got 2" in fix_request


def test_generate_gives_up_after_repeated_invalid_plans(client, auth_headers, library, profile, use_llm) -> None:
    two_days = copy.deepcopy(VALID_PLAN)
    two_days["workouts"] = two_days["workouts"][:2]
    use_llm(FakeLLM(two_days, two_days))
    response = generate(client, auth_headers)
    assert response.status_code == 502
    assert client.get(PROGRAMS, headers=auth_headers).json() == []  # nothing saved


def test_generate_reports_llm_failure(client, auth_headers, library, profile, use_llm) -> None:
    use_llm(FakeLLM(LLMError("OpenAI request failed: timeout")))
    response = generate(client, auth_headers)
    assert response.status_code == 502
    assert "timeout" in response.json()["detail"]


def test_generate_requires_profile(client, auth_headers, library, use_llm) -> None:
    fake = use_llm(FakeLLM(VALID_PLAN))
    assert generate(client, auth_headers).status_code == 409
    assert fake.calls == []


def test_request_overrides_profile_days(client, auth_headers, library, profile, use_llm) -> None:
    fake = use_llm(FakeLLM(VALID_PLAN))
    # Asking for 4 days: the 3-day plan is invalid, so the model is asked to fix it...
    fake.responses.append(VALID_PLAN)
    response = generate(client, auth_headers, training_days_per_week=4)
    assert response.status_code == 502
    assert "4 training days" in fake.calls[0][0][1]["content"]


# --- Lifecycle ------------------------------------------------------------


def test_activate_list_this_week_and_delete(client, auth_headers, library, profile, use_llm) -> None:
    use_llm(FakeLLM(VALID_PLAN, VALID_PLAN))
    first = generate(client, auth_headers).json()
    second = generate(client, auth_headers).json()
    assert client.get(f"{PROGRAMS}/active", headers=auth_headers).status_code == 404

    activated = client.patch(f"{PROGRAMS}/{first['id']}", json={"status": "active"}, headers=auth_headers)
    assert activated.json()["status"] == "active"
    client.patch(f"{PROGRAMS}/{second['id']}", json={"status": "active", "name": "Block 2"}, headers=auth_headers)

    listed = {p["id"]: p for p in client.get(PROGRAMS, headers=auth_headers).json()}
    assert listed[first["id"]]["status"] == "archived"
    assert listed[second["id"]]["status"] == "active"
    assert listed[second["id"]]["name"] == "Block 2"

    active = client.get(f"{PROGRAMS}/active", headers=auth_headers).json()
    assert active["id"] == second["id"]
    this_week = client.get(f"{PROGRAMS}/active/this-week", headers=auth_headers).json()
    assert [w["week_number"] for w in this_week] == [1, 1, 1]  # starts today -> week 1

    assert client.delete(f"{PROGRAMS}/{second['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"{PROGRAMS}/{second['id']}", headers=auth_headers).status_code == 404


def test_programs_are_private(client, auth_headers, library, profile, use_llm) -> None:
    use_llm(FakeLLM(VALID_PLAN))
    program = generate(client, auth_headers).json()

    client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "other-password"})
    token = client.post("/api/v1/auth/login", data={"username": "other@example.com",
                                                     "password": "other-password"}).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{PROGRAMS}/{program['id']}", headers=other).status_code == 404
    assert client.patch(f"{PROGRAMS}/{program['id']}", json={"name": "mine"}, headers=other).status_code == 404
    assert client.delete(f"{PROGRAMS}/{program['id']}", headers=other).status_code == 404
    assert client.get(PROGRAMS, headers=other).json() == []
