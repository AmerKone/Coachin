"""API tests for the fitness profile (onboarding and updates)."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

PROFILE = "/api/v1/users/me/profile"

ONBOARDING = {
    "date_of_birth": "1995-04-12",
    "sex": "female",
    "height_cm": 168,
    "weight_kg": 64.5,
    "fitness_level": "intermediate",
    "primary_goal": "strength",
    "training_days_per_week": 4,
    "session_duration_min": 75,
    "available_equipment": ["barbell", "dumbbells", "pull-up bar"],
    "injuries": "Old left ankle sprain",
}


def test_profile_missing_before_onboarding(client: TestClient, auth_headers: dict) -> None:
    assert client.get(PROFILE, headers=auth_headers).status_code == 404
    assert client.patch(PROFILE, json={"weight_kg": 70}, headers=auth_headers).status_code == 404


def test_profile_requires_auth(client: TestClient) -> None:
    assert client.get(PROFILE).status_code == 401


def test_create_and_read_profile(client: TestClient, auth_headers: dict) -> None:
    created = client.put(PROFILE, json=ONBOARDING, headers=auth_headers)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["primary_goal"] == "strength"
    assert body["available_equipment"] == ["barbell", "dumbbells", "pull-up bar"]
    assert body["medical_clearance"] is False  # default applied

    fetched = client.get(PROFILE, headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_put_replaces_whole_profile(client: TestClient, auth_headers: dict) -> None:
    first = client.put(PROFILE, json=ONBOARDING, headers=auth_headers).json()
    second = client.put(PROFILE, json={"primary_goal": "fat_loss"}, headers=auth_headers).json()

    assert second["id"] == first["id"]  # same row, not a second profile
    assert second["primary_goal"] == "fat_loss"
    assert second["injuries"] is None  # omitted fields reset to defaults
    assert second["training_days_per_week"] == 3


def test_patch_updates_only_given_fields(client: TestClient, auth_headers: dict) -> None:
    client.put(PROFILE, json=ONBOARDING, headers=auth_headers)
    response = client.patch(PROFILE, json={"weight_kg": 63, "injuries": None}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["weight_kg"] == 63
    assert body["injuries"] is None
    assert body["primary_goal"] == "strength"  # untouched


def test_patch_rejects_null_for_required_fields(client: TestClient, auth_headers: dict) -> None:
    client.put(PROFILE, json=ONBOARDING, headers=auth_headers)
    response = client.patch(PROFILE, json={"primary_goal": None}, headers=auth_headers)
    assert response.status_code == 422


def test_profile_validation(client: TestClient, auth_headers: dict) -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for bad in (
        {"date_of_birth": tomorrow},
        {"training_days_per_week": 8},
        {"height_cm": 20},
        {"primary_goal": "get_huge"},
        {"unknown_field": 1},
    ):
        response = client.put(PROFILE, json=bad, headers=auth_headers)
        assert response.status_code == 422, bad


def test_deleting_account_deletes_profile(client: TestClient, auth_headers: dict, db) -> None:
    from sqlalchemy import func, select

    from app.models import UserProfile

    client.put(PROFILE, json=ONBOARDING, headers=auth_headers)
    assert db.scalar(select(func.count()).select_from(UserProfile)) >= 1
    before = db.scalar(select(func.count()).select_from(UserProfile))

    client.delete("/api/v1/users/me", headers=auth_headers)
    assert db.scalar(select(func.count()).select_from(UserProfile)) == before - 1
