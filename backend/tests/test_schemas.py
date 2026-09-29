"""Validation tests for Pydantic schemas (no database or network required)."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas import PlannedExerciseCreate


def test_planned_exercise_rejects_inverted_rep_range() -> None:
    with pytest.raises(ValidationError):
        PlannedExerciseCreate(
            exercise_id=uuid.uuid4(), position=1, target_sets=3, target_reps_min=12, target_reps_max=8
        )
