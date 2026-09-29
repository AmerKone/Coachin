"""Progressive overload: turns logged performance into next-session targets.

Default rule (double progression): if every working set hit the top of the rep range at
RPE <= target, increase load (upper body +2.5 kg, lower body +5 kg) and reset to the bottom
of the range; otherwise add reps. Repeated misses or high RPE trigger a deload suggestion.
"""

import uuid

from sqlalchemy.orm import Session

from app.models import ExerciseSet, PlannedExercise
from app.schemas import ExerciseHistoryPoint, OverloadRecommendation


class OverloadService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def recommend_for_workout(
        self, user_id: uuid.UUID, program_workout_id: uuid.UUID
    ) -> list[OverloadRecommendation]:
        """Targets for every exercise in a planned workout."""
        raise NotImplementedError

    def recommend_for_exercise(
        self, planned: PlannedExercise, recent_sets: list[ExerciseSet]
    ) -> OverloadRecommendation:
        """Apply the progression rule to one exercise's most recent working sets."""
        raise NotImplementedError

    def history(self, user_id: uuid.UUID, exercise_id: uuid.UUID, weeks: int) -> list[ExerciseHistoryPoint]:
        raise NotImplementedError

    @staticmethod
    def estimate_1rm(weight_kg: float, reps: int) -> float:
        """Epley estimate: weight * (1 + reps / 30)."""
        raise NotImplementedError
