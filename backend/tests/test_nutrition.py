"""Tests for nutrition targets, meal estimation (fake LLM), logging and daily summaries."""

import copy
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes.nutrition import get_nutrition_service
from app.main import app
from app.models import UserProfile
from app.rag.retriever import KnowledgeRetriever
from app.services.llm_client import LLMError
from app.services.nutrition_service import (
    NutritionService,
    _EstimatedItem,
    clean_item,
    day_bounds,
    suggest_targets,
)

NUTRITION = "/api/v1/nutrition"
PROFILE = "/api/v1/users/me/profile"
TODAY = date(2026, 9, 29)


def profile(**overrides) -> UserProfile:
    fields = dict(sex="female", date_of_birth=date(1996, 1, 15), height_cm=165, weight_kg=65,
                  training_days_per_week=4, primary_goal="fat_loss", fitness_level="beginner")
    fields.update(overrides)
    return UserProfile(**fields)


# --- Targets --------------------------------------------------------------


def test_targets_match_knowledge_base_example() -> None:
    # 30-year-old woman, 165 cm, 65 kg, 4 sessions/week: BMR 1370, TDEE ~2124, fat loss ~1700.
    targets, explanation, missing = suggest_targets(profile(), TODAY)
    assert missing == []
    assert targets.calories == 1700
    assert targets.protein_g == 130  # 2.0 g/kg
    assert targets.fat_g == 47       # 25% of calories
    assert targets.carbs_g == 189    # remainder
    assert "BMR 1370" in explanation


def test_muscle_gain_surplus_for_male() -> None:
    targets, _, _ = suggest_targets(profile(sex="male", date_of_birth=date(2001, 1, 1), height_cm=180,
                                            weight_kg=80, primary_goal="muscle_gain"), TODAY)
    assert targets.calories == 3080  # (1805 BMR x 1.55) x 1.10
    assert targets.protein_g == 144  # 1.8 g/kg


def test_calorie_floor_applies() -> None:
    targets, explanation, _ = suggest_targets(profile(date_of_birth=date(1966, 1, 1), height_cm=150,
                                                      weight_kg=45, training_days_per_week=1), TODAY)
    assert targets.calories == 1200
    assert "safety minimum" in explanation


def test_no_deficit_for_minors_or_underweight() -> None:
    minor, note, _ = suggest_targets(profile(date_of_birth=date(2010, 5, 1)), TODAY)
    adult, _, _ = suggest_targets(profile(date_of_birth=date(1996, 5, 1)), TODAY)
    assert "No calorie deficit" in note and minor.calories > adult.calories

    underweight, note, _ = suggest_targets(profile(weight_kg=48), TODAY)  # BMI 17.6
    assert "No calorie deficit" in note


def test_protein_uses_reference_weight_when_bmi_over_30() -> None:
    targets, explanation, _ = suggest_targets(profile(sex="male", height_cm=175, weight_kg=120), TODAY)
    assert targets.protein_g == 153  # 2.0 g/kg x 76.6 kg (BMI 25 at 175 cm), not 240 g
    assert "healthy-weight reference" in explanation


def test_missing_fields_reported() -> None:
    targets, explanation, missing = suggest_targets(profile(height_cm=None, date_of_birth=None), TODAY)
    assert targets is None
    assert missing == ["height_cm", "date_of_birth"]
    assert "height cm" in explanation


# --- Pure helpers ---------------------------------------------------------


def test_clean_item_trusts_macros_when_calories_disagree() -> None:
    item = _EstimatedItem(food="Rice", portion="200 g", calories=900, protein_g=5.4, carbs_g=56, fat_g=0.6)
    assert clean_item(item).calories == round(5.4 * 4 + 56 * 4 + 0.6 * 9)  # 251, not 900

    close = _EstimatedItem(food="Egg", portion="1 large", calories=72, protein_g=6.3, carbs_g=0.4, fat_g=4.8)
    assert clean_item(close).calories == 72  # within tolerance: kept

    negative = _EstimatedItem(food="x", portion="y", calories=-10, protein_g=-1, carbs_g=0, fat_g=0)
    cleaned = clean_item(negative)
    assert (cleaned.calories, cleaned.protein_g) == (0, 0)


def test_day_bounds_use_local_timezone() -> None:
    start, end = day_bounds(date(2026, 9, 29), "Africa/Algiers")  # UTC+1
    assert start == datetime(2026, 9, 28, 23, 0, tzinfo=UTC)
    assert end - start == timedelta(days=1)


# --- API ------------------------------------------------------------------

MEAL = {
    "meal_type": "lunch",
    "assumptions": "Assumed a typical restaurant portion of rice.",
    "items": [
        {"food": "Chicken breast", "portion": "150 g", "calories": 248, "protein_g": 46.5, "carbs_g": 0, "fat_g": 5.4},
        {"food": "White rice", "portion": "200 g", "calories": 260, "protein_g": 5.4, "carbs_g": 56, "fat_g": 0.6},
        {"food": "Olive oil", "portion": "1 tbsp", "calories": 119, "protein_g": 0, "carbs_g": 0, "fat_g": 13.5},
    ],
}


class FakeLLM:
    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def __call__(self, messages, schema):
        self.calls.append(copy.deepcopy(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


class NoKnowledge:
    def similarity_search_with_score(self, query, k=4, filter=None):
        return []


@pytest.fixture
def use_llm(db: Session):
    def install(fake: FakeLLM) -> FakeLLM:
        service = NutritionService(db, llm=fake, retriever=KnowledgeRetriever(store=NoKnowledge()))
        app.dependency_overrides[get_nutrition_service] = lambda: service
        return fake
    yield install
    app.dependency_overrides.pop(get_nutrition_service, None)


def test_estimate_sums_items_and_saves_nothing(client: TestClient, auth_headers, use_llm) -> None:
    fake = use_llm(FakeLLM(MEAL))
    response = client.post(f"{NUTRITION}/estimate", headers=auth_headers,
                           json={"description": "Grilled chicken with rice"})
    assert response.status_code == 200, response.text
    estimate = response.json()
    assert estimate["meal_type"] == "lunch"
    assert estimate["totals"] == {"calories": 627, "protein_g": 51.9, "carbs_g": 56.0, "fat_g": 19.5}
    assert [i["food"] for i in estimate["items"]] == ["Chicken breast", "White rice", "Olive oil"]
    assert "Grilled chicken with rice" in fake.calls[0][1]["content"]

    today = client.get(f"{NUTRITION}/daily/{date.today()}", headers=auth_headers).json()
    assert today["entries"] == []


def test_estimate_errors(client: TestClient, auth_headers, use_llm) -> None:
    use_llm(FakeLLM({"meal_type": "snack", "items": [], "assumptions": ""}, LLMError("timeout")))
    not_food = client.post(f"{NUTRITION}/estimate", headers=auth_headers, json={"description": "hello there"})
    assert not_food.status_code == 422
    assert "Couldn't recognise" in not_food.json()["detail"]

    outage = client.post(f"{NUTRITION}/estimate", headers=auth_headers, json={"description": "an apple"})
    assert outage.status_code == 502


def test_log_and_daily_summary_respect_timezone(client: TestClient, auth_headers) -> None:
    day = date(2026, 9, 29)
    entries = [  # (UTC time, calories)
        (datetime(2026, 9, 28, 23, 30, tzinfo=UTC), 300),  # 00:30 on the 29th in Algiers
        (datetime(2026, 9, 29, 12, 0, tzinfo=UTC), 500),
        (datetime(2026, 9, 29, 23, 30, tzinfo=UTC), 200),  # 00:30 on the 30th in Algiers
    ]
    for eaten_at, calories in entries:
        created = client.post(NUTRITION, headers=auth_headers, json={
            "eaten_at": eaten_at.isoformat(), "meal_type": "snack", "description": f"{calories} kcal snack",
            "calories": calories, "protein_g": 10, "carbs_g": 20, "fat_g": 5, "is_estimated": False,
        })
        assert created.status_code == 201, created.text

    algiers = client.get(f"{NUTRITION}/daily/{day}", params={"tz": "Africa/Algiers"}, headers=auth_headers).json()
    utc = client.get(f"{NUTRITION}/daily/{day}", headers=auth_headers).json()
    assert algiers["totals"]["calories"] == 800 and len(algiers["entries"]) == 2
    assert utc["totals"]["calories"] == 700
    assert algiers["totals"]["protein_g"] == 20

    bad_tz = client.get(f"{NUTRITION}/daily/{day}", params={"tz": "Mars/Olympus"}, headers=auth_headers)
    assert bad_tz.status_code == 422


def test_targets_endpoint_prefers_profile_values(client: TestClient, auth_headers) -> None:
    empty = client.get(f"{NUTRITION}/targets", headers=auth_headers).json()
    assert empty["effective"] is None and empty["missing_profile_fields"] == ["profile"]

    client.put(PROFILE, headers=auth_headers, json={
        "sex": "female", "date_of_birth": "1996-01-15", "height_cm": 165, "weight_kg": 65,
        "training_days_per_week": 4, "primary_goal": "fat_loss", "daily_protein_target_g": 110,
    })
    targets = client.get(f"{NUTRITION}/targets", headers=auth_headers).json()
    assert targets["effective"]["protein_g"] == 110              # from the profile
    assert targets["effective"]["calories"] == targets["suggested"]["calories"]  # filled from suggestion
    assert targets["suggested"]["protein_g"] == 130
    assert targets["explanation"].startswith("Using the targets saved in your profile")

    summary = client.get(f"{NUTRITION}/daily/{date.today()}", headers=auth_headers).json()
    assert summary["targets"]["protein_g"] == 110


def test_update_delete_and_privacy(client: TestClient, auth_headers) -> None:
    entry = client.post(NUTRITION, headers=auth_headers, json={
        "eaten_at": datetime.now(UTC).isoformat(), "meal_type": "breakfast", "description": "Oats",
        "calories": 150, "protein_g": 5, "carbs_g": 27, "fat_g": 2.5,
    }).json()
    url = f"{NUTRITION}/{entry['id']}"
    assert client.patch(url, headers=auth_headers, json={"calories": 190}).json()["calories"] == 190
    assert client.patch(url, headers=auth_headers, json={"calories": -5}).status_code == 422

    client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "other-password"})
    token = client.post("/api/v1/auth/login", data={"username": "other@example.com",
                                                     "password": "other-password"}).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.patch(url, headers=other, json={"calories": 1}).status_code == 404
    assert client.delete(url, headers=other).status_code == 404

    assert client.delete(url, headers=auth_headers).status_code == 204
    assert client.delete(url, headers=auth_headers).status_code == 404
