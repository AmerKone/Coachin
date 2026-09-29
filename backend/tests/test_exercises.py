"""Tests for the exercise library: data file, seeding/upsert, and search API."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Exercise
from app.models.enums import Equipment, ExerciseCategory, MuscleGroup
from app.schemas import ExerciseCreate
from app.services.exercise_service import read_exercise_file, search_exercises, upsert_exercises
from tests.conftest import clear_exercise_library

EXERCISES = "/api/v1/exercises"


def make(name: str, muscle: str = "chest", category: str = "compound", equipment=(), **extra) -> ExerciseCreate:
    return ExerciseCreate(
        name=name, primary_muscle=muscle, category=category, equipment=list(equipment), **extra
    )


SAMPLE = [
    make("Barbell Bench Press", equipment=["barbell", "bench"]),
    make("Push-Up", is_bodyweight=True),
    make("Dumbbell Curl", muscle="biceps", category="isolation", equipment=["dumbbells"]),
    make("Goblet Squat", muscle="quadriceps", equipment=["dumbbells"]),
    make("Pull-Up", muscle="back", equipment=["pull-up bar"], is_bodyweight=True),
    make("100% Effort_Sprint", muscle="cardio", category="cardio"),
]


def names(exercises) -> list[str]:
    return [e.name if isinstance(e, Exercise) else e["name"] for e in exercises]


# --- Data file (no database needed) ---------------------------------------


def test_data_file_is_valid_and_names_are_unique() -> None:
    exercises = read_exercise_file()
    assert len(exercises) >= 80
    lowered = [e.name.lower() for e in exercises]
    assert len(lowered) == len(set(lowered))


def test_data_file_covers_every_muscle_group_category_and_equipment() -> None:
    exercises = read_exercise_file()
    assert {e.primary_muscle for e in exercises} == set(MuscleGroup)
    assert {e.category for e in exercises} == set(ExerciseCategory)
    assert set().union(*(e.equipment for e in exercises)) == set(Equipment)
    assert sum(1 for e in exercises if not e.equipment) >= 20  # plenty for home training


# --- Upsert ---------------------------------------------------------------


@pytest.fixture
def empty_library(db: Session) -> None:
    """Start from an empty exercises table so seeded data can't affect results (rolled back after)."""
    clear_exercise_library(db)


def exercise_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Exercise))


def test_upsert_is_idempotent_and_updates_changes(db: Session, empty_library) -> None:
    first = upsert_exercises(db, SAMPLE)
    assert (first.inserted, first.updated, first.unchanged) == (len(SAMPLE), 0, 0)

    again = upsert_exercises(db, SAMPLE)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, len(SAMPLE))

    changed = [make("push-up", instructions="Keep a straight line.", is_bodyweight=True)]
    result = upsert_exercises(db, changed)
    assert (result.inserted, result.updated) == (0, 1)
    assert exercise_count(db) == len(SAMPLE)

    push_up = db.scalar(select(Exercise).where(Exercise.name == "push-up"))
    assert push_up.instructions == "Keep a straight line."


def test_upsert_rejects_duplicate_names(db: Session) -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        upsert_exercises(db, [make("Plank"), make("PLANK")])


def test_full_data_file_seeds(db: Session) -> None:
    exercises = read_exercise_file()
    result = upsert_exercises(db, exercises)
    assert result.inserted + result.updated + result.unchanged == len(exercises)
    assert upsert_exercises(db, exercises).unchanged == len(exercises)


# --- Search ---------------------------------------------------------------


@pytest.fixture
def sample_ids(db: Session, empty_library) -> dict[str, uuid.UUID]:
    upsert_exercises(db, SAMPLE)
    return {e.name: e.id for e in db.scalars(select(Exercise))}


def test_search_filters(db: Session, sample_ids) -> None:
    def search(**kwargs):
        return names(search_exercises(db, **kwargs)[0])

    assert search(q="PUSH") == ["Push-Up"]
    assert search(muscle=MuscleGroup.QUADRICEPS) == ["Goblet Squat"]
    assert search(category=ExerciseCategory.ISOLATION) == ["Dumbbell Curl"]
    assert search(no_equipment=True) == ["100% Effort_Sprint", "Push-Up"]
    # Equipment means "what I have": bench press also needs a bench, so it's excluded.
    assert search(equipment=[Equipment.DUMBBELLS, Equipment.BARBELL]) == [
        "100% Effort_Sprint", "Dumbbell Curl", "Goblet Squat", "Push-Up",
    ]
    assert "Barbell Bench Press" in search(equipment=[Equipment.BARBELL, Equipment.BENCH])


def test_search_treats_wildcards_literally(db: Session, sample_ids) -> None:
    assert names(search_exercises(db, q="100%")[0]) == ["100% Effort_Sprint"]
    assert names(search_exercises(db, q="_")[0]) == ["100% Effort_Sprint"]


def test_search_pagination(db: Session, sample_ids) -> None:
    page, total = search_exercises(db, limit=2, offset=2)
    assert total == len(SAMPLE)
    assert names(page) == ["Dumbbell Curl", "Goblet Squat"]


def test_list_endpoint(client: TestClient, auth_headers: dict, sample_ids) -> None:
    response = client.get(
        EXERCISES, params={"equipment": ["dumbbells"], "limit": 10}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4
    assert names(body["items"]) == ["100% Effort_Sprint", "Dumbbell Curl", "Goblet Squat", "Push-Up"]
    assert body["items"][1]["equipment"] == ["dumbbells"]


def test_list_endpoint_validation_and_auth(client: TestClient, auth_headers: dict) -> None:
    assert client.get(EXERCISES).status_code == 401
    assert client.get(EXERCISES, params={"muscle": "wings"}, headers=auth_headers).status_code == 422
    assert client.get(EXERCISES, params={"limit": 500}, headers=auth_headers).status_code == 422


def test_get_exercise(client: TestClient, auth_headers: dict, sample_ids) -> None:
    response = client.get(f"{EXERCISES}/{sample_ids['Pull-Up']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["equipment"] == ["pull-up bar"]

    assert client.get(f"{EXERCISES}/{uuid.uuid4()}", headers=auth_headers).status_code == 404
