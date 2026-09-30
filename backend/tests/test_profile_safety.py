"""Tests for the onboarding safety screen and how it affects programs and nutrition."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SafetyEvent, User, UserProfile
from app.models.enums import SafetyAction, SafetyCategory, SafetySeverity
from app.services.nutrition_service import suggest_targets
from app.services.program_service import rpe_cap_for
from app.services.safety_service import blocks_program_generation, needs_clearance, screen_profile_text

PROFILE = "/api/v1/users/me/profile"


@pytest.mark.parametrize(("conditions", "category", "severity"), [
    ("I get chest pain when I run", SafetyCategory.CARDIOVASCULAR, SafetySeverity.CRITICAL),
    ("I fainted twice last month", SafetyCategory.CARDIOVASCULAR, SafetySeverity.CRITICAL),
    ("Heart failure, on medication", SafetyCategory.CARDIOVASCULAR, SafetySeverity.HIGH),
    ("atrial fibrillation", SafetyCategory.CARDIOVASCULAR, SafetySeverity.HIGH),
    ("had a stroke in 2023", SafetyCategory.CARDIOVASCULAR, SafetySeverity.HIGH),
    ("recovering from anorexia", SafetyCategory.EATING_DISORDER, SafetySeverity.HIGH),
    ("chronic kidney disease", SafetyCategory.MEDICAL_CONDITION, SafetySeverity.HIGH),
    ("I'm 20 weeks pregnant", SafetyCategory.PREGNANCY, SafetySeverity.MEDIUM),
    ("type 1 diabetes, insulin pump", SafetyCategory.MEDICAL_CONDITION, SafetySeverity.MEDIUM),
    ("epilepsy, well controlled", SafetyCategory.MEDICAL_CONDITION, SafetySeverity.MEDIUM),
])
def test_conditions_are_flagged(conditions: str, category, severity) -> None:
    assessment = screen_profile_text(None, conditions)
    assert assessment.is_flagged
    assert (assessment.category, assessment.severity) == (category, severity)
    assert "doctor" in assessment.user_facing_message


@pytest.mark.parametrize("text", [
    "Old left ankle sprain", "I love backstroke swimming", "I train in heart rate zones", "Mild asthma",
    "Tight hamstrings", "", None,
])
def test_ordinary_answers_are_not_flagged(text) -> None:
    assert screen_profile_text(text, None).is_flagged is False


def test_red_flags_block_and_clearance_unblocks() -> None:
    symptoms = UserProfile(medical_conditions="chest pain when climbing stairs", medical_clearance=False)
    assert screen_profile_text(None, symptoms.medical_conditions).recommended_action == SafetyAction.BLOCKED
    assert blocks_program_generation(symptoms) and needs_clearance(symptoms)

    cleared = UserProfile(medical_conditions="chest pain when climbing stairs", medical_clearance=True)
    assert not blocks_program_generation(cleared) and not needs_clearance(cleared)
    assert screen_profile_text(None, cleared.medical_conditions, True).recommended_action == SafetyAction.LOGGED


def test_clearance_caps_program_effort() -> None:
    pregnant = UserProfile(injuries="pregnant (second trimester)", fitness_level="advanced", medical_clearance=False)
    assert rpe_cap_for(pregnant) == 7.0          # flagged in `injuries`, not only medical_conditions
    pregnant.medical_clearance = True
    assert rpe_cap_for(pregnant) == 9.0
    assert rpe_cap_for(UserProfile(injuries="old ankle sprain", fitness_level="advanced")) == 9.0


def test_eating_disorder_history_removes_deficit() -> None:
    base = dict(sex="female", date_of_birth=date(1996, 1, 15), height_cm=165, weight_kg=65,
                training_days_per_week=4, primary_goal="fat_loss", fitness_level="beginner")
    normal, _, _ = suggest_targets(UserProfile(**base), date(2026, 9, 30))
    history, note, _ = suggest_targets(UserProfile(**base, medical_conditions="history of bulimia"), date(2026, 9, 30))
    assert history.calories > normal.calories
    assert "eating disorder" in note


# --- API ---------------------------------------------------------------------


def test_profile_save_returns_notice_and_logs_event_once(client: TestClient, auth_headers, db: Session) -> None:
    body = {"medical_conditions": "heart failure", "fitness_level": "beginner"}
    first = client.put(PROFILE, headers=auth_headers, json=body).json()
    assert first["safety_notice"]["severity"] == "high"
    assert "heart condition" in first["safety_notice"]["message"]

    client.put(PROFILE, headers=auth_headers, json=body)           # same answers: no new event
    client.patch(PROFILE, headers=auth_headers, json={"weight_kg": 70})
    user = db.scalar(select(User).where(User.email == "alex@example.com"))
    events = db.scalars(select(SafetyEvent).where(SafetyEvent.user_id == user.id)).all()
    assert len(events) == 1 and events[0].category == SafetyCategory.CARDIOVASCULAR

    fetched = client.get(PROFILE, headers=auth_headers).json()
    assert fetched["safety_notice"]["severity"] == "high"          # standing notice on read

    cleared = client.patch(PROFILE, headers=auth_headers, json={"medical_clearance": True}).json()
    assert cleared["safety_notice"]["action_taken"] == "logged"


def test_ordinary_profile_has_no_notice(client: TestClient, auth_headers) -> None:
    body = client.put(PROFILE, headers=auth_headers, json={"injuries": "old ankle sprain"}).json()
    assert body["safety_notice"] is None


def test_program_generation_blocked_until_cleared(client: TestClient, auth_headers) -> None:
    client.put(PROFILE, headers=auth_headers, json={"medical_conditions": "I passed out during a run last week"})
    response = client.post("/api/v1/programs/generate", headers=auth_headers, json={"duration_weeks": 4})
    assert response.status_code == 409
    assert "doctor" in response.json()["detail"]
